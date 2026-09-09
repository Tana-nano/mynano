"""OpenAI 互換サーバーの偽物。

実機の llama-server に火を入れる前に、HTTP 経路そのものを確かめるための足場。
`OfflineLLM` はクライアントを丸ごと飛ばしてしまうので、SSE の解釈も
JSON の拾い方もエラーの出方も、ここを通さないと一度も実行されない。

依存は増やさない。`http.server` は標準ライブラリ（禁則3）。
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable


@dataclass
class Script:
    """テストが差し込む挙動。"""

    # 呼ばれるたびに1つ消費される応答。文字列なら本文、intならそのHTTPステータス。
    replies: list = field(default_factory=list)
    # 埋め込みの次元。dim 不一致を再現したいときに変える。
    embedding_dim: int = 8
    # 受け取ったリクエストの記録
    seen: list[dict] = field(default_factory=list)
    # 1トークンぶん流すたびに呼ばれる（中断の再現用）
    on_chunk: Callable[[], None] | None = None
    # GET /lora-adapters の応答。None = そのエンドポイントを持たないサーバー（404）。
    lora_adapters: list | None = None

    def next_reply(self):
        return self.replies.pop(0) if self.replies else "（応答）"


class _Handler(BaseHTTPRequestHandler):
    script: Script

    def log_message(self, *_args) -> None:  # テスト出力を汚さない
        pass

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler の規約
        try:
            self._dispatch()
        except (BrokenPipeError, ConnectionResetError):
            # クライアントが中断で接続を切った。実機でも同じことが起きる（そして
            # それが狙い: 接続が切れれば llama-server 側の生成も止まる）。
            pass

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler の規約
        if self.path.endswith("/lora-adapters"):
            self._lora_adapters()
        else:
            self.send_error(404)

    def _lora_adapters(self) -> None:
        # サーバー直下（/v1 の外）のエンドポイント。llama-server 固有で OpenAI 互換 API には無い。
        if self.script.lora_adapters is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.script.lora_adapters).encode("utf-8"))

    def _dispatch(self) -> None:
        payload = self._body()
        self.script.seen.append({"path": self.path, "payload": payload, "headers": dict(self.headers)})
        if self.path.endswith("/chat/completions"):
            self._chat(payload)
        elif self.path.endswith("/embeddings"):
            self._embeddings(payload)
        else:
            self.send_error(404)

    def _chat(self, payload: dict) -> None:
        reply = self.script.next_reply()
        if isinstance(reply, int):
            self.send_response(reply)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"error": "模擬エラー"}).encode("utf-8"))
            return

        if not payload.get("stream"):
            body = {"choices": [{"message": {"role": "assistant", "content": reply}}]}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(body).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        # 実機と同じく1文字ずつ delta で流す
        for character in reply:
            frame = {"choices": [{"delta": {"content": character}}]}
            self.wfile.write(f"data: {json.dumps(frame, ensure_ascii=False)}\n\n".encode("utf-8"))
            self.wfile.flush()
            if self.script.on_chunk is not None:
                self.script.on_chunk()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _embeddings(self, payload: dict) -> None:
        inputs = payload.get("input") or []
        dim = self.script.embedding_dim
        data = []
        for index, text in enumerate(inputs):
            # 決定的だが内容に依存するベクトル。実機の e5 と違い意味は持たない。
            vector = [((hash_char(text, position) % 200) - 100) / 100.0 for position in range(dim)]
            data.append({"index": index, "embedding": vector})
        # 実機は index 順とは限らない。並べ替えが効いているか見たいので逆順で返す。
        data.reverse()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"data": data}).encode("utf-8"))


def hash_char(text: str, position: int) -> int:
    total = position * 31 + 7
    for character in text:
        total = (total * 131 + ord(character)) % 100_003
    return total


class FakeServer:
    def __init__(self) -> None:
        self.script = Script()
        handler = type("Handler", (_Handler,), {"script": self.script})
        self._httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
        self._thread.start()

    @property
    def base_url(self) -> str:
        host, port = self._httpd.server_address[:2]
        return f"http://{host}:{port}/v1"

    def close(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        self._thread.join(timeout=5)
