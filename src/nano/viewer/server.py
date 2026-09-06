"""記憶グラフをローカルで見るための小さなサーバー。

標準ライブラリの http.server だけで足りる。FastAPI も uvicorn も要らない。
外に公開するものではないので、既定で 127.0.0.1 にしか listen しない。
"""

from __future__ import annotations

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse

from . import data as graph_data
from . import page

DEFAULT_PORT = 8765


def make_handler(app, limit: int):
    class Handler(BaseHTTPRequestHandler):
        # 既定のアクセスログは邪魔なので黙らせる（起動メッセージだけ出す）
        def log_message(self, *args) -> None:
            return

        def _send(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload) -> None:
            self._send(json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802 - http.server の規約
            path = urlparse(self.path).path

            if path in ("/", "/index.html"):
                html = page.render(f"{app.config.persona.name} の記憶", api_base="/api")
                self._send(html.encode("utf-8"), "text/html; charset=utf-8")
                return

            if path == "/api/graph":
                self._json(graph_data.build(app.db, app.config.decay, limit=limit).to_dict())
                return

            if path.startswith("/api/note/"):
                try:
                    note_id = int(path.rsplit("/", 1)[1])
                except ValueError:
                    self.send_error(400, "bad note id")
                    return
                detail = graph_data.note_detail(app.db, note_id, app.config.decay)
                if detail is None:
                    self.send_error(404, "no such note")
                    return
                self._json(detail)
                return

            self.send_error(404)

    return Handler


def serve(
    app,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    limit: int = graph_data.DEFAULT_LIMIT,
    open_browser: bool = True,
) -> int:
    server = HTTPServer((host, port), make_handler(app, limit))
    url = f"http://{host}:{server.server_port}/"
    print(f"記憶グラフ: {url}")
    print("Ctrl-C で終了します。")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:  # noqa: BLE001 - ブラウザが無くても困らない
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n終了しました。")
    finally:
        server.server_close()
    return 0
