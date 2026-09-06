"""LLM クライアント。OpenAI 互換エンドポイント（llama-server / Ollama など）を叩く。

依存は httpx だけ。フレームワークを噛ませないのは、抽象化の寿命が
このプロジェクトの寿命（＝一生）より短いから。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterator, Protocol, Sequence

import httpx

from .gate import CancelToken

Message = dict[str, str]


class LLMError(RuntimeError):
    pass


class LLM(Protocol):
    """`task` は実サーバーには送らないメタ情報。ログとテスト用スタブの分岐に使う。"""

    def chat(
        self,
        messages: Sequence[Message],
        *,
        task: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        cancel: CancelToken | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str: ...

    def chat_json(
        self,
        messages: Sequence[Message],
        *,
        task: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        cancel: CancelToken | None = None,
    ) -> Any: ...


@dataclass
class LlamaServerLLM:
    base_url: str
    model: str = "local"
    api_key: str = ""
    timeout_s: float = 300.0
    temperature: float = 0.8
    max_tokens: int = 1024

    def __post_init__(self) -> None:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        self._client = httpx.Client(
            base_url=self.base_url.rstrip("/"), headers=headers, timeout=self.timeout_s
        )

    def close(self) -> None:
        self._client.close()

    def chat(
        self,
        messages: Sequence[Message],
        *,
        task: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        cancel: CancelToken | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        chunks: list[str] = []
        for piece in self.stream(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            cancel=cancel,
        ):
            chunks.append(piece)
            if on_token is not None:
                on_token(piece)
        return "".join(chunks).strip()

    def stream(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        cancel: CancelToken | None = None,
    ) -> Iterator[str]:
        """SSE ストリーム。cancel が立ったら接続を切る＝サーバー側の生成も止まる。"""
        payload = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "stream": True,
        }
        try:
            with self._client.stream("POST", "/chat/completions", json=payload) as response:
                if response.status_code >= 400:
                    response.read()
                    raise LLMError(f"{response.status_code}: {response.text[:400]}")
                for line in response.iter_lines():
                    if cancel is not None:
                        cancel.raise_if_cancelled()
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0].get("delta", {})
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    content = delta.get("content")
                    if content:
                        yield content
        except httpx.HTTPError as exc:  # 接続不能はここに来る（サーバー未起動など）
            raise LLMError(f"cannot reach LLM at {self.base_url}: {exc}") from exc

    def chat_json(
        self,
        messages: Sequence[Message],
        *,
        task: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        cancel: CancelToken | None = None,
    ) -> Any:
        """JSON を返させる。ローカルモデルは前後に喋りがちなので必ず抽出＋1回だけ修復。"""
        raw = self.chat(
            messages,
            task=task,
            temperature=0.2 if temperature is None else temperature,
            max_tokens=max_tokens,
            cancel=cancel,
        )
        parsed = extract_json(raw)
        if parsed is not None:
            return parsed
        repair = [
            *messages,
            {"role": "assistant", "content": raw[:2000]},
            {"role": "user", "content": "JSONとして解釈できませんでした。JSONのみを再出力してください。"},
        ]
        parsed = extract_json(
            self.chat(repair, task=task, temperature=0.0, max_tokens=max_tokens, cancel=cancel)
        )
        if parsed is None:
            raise LLMError(f"model did not return JSON for task={task!r}")
        return parsed


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def extract_json(text: str) -> Any | None:
    """素の JSON / コードフェンス / 前後に喋りがある場合のいずれからも拾う。"""
    candidates = [match.strip() for match in _FENCE.findall(text)]
    candidates.append(text.strip())
    # 括弧で囲まれた部分。入れ子を取りこぼさないよう長い方を先に試す。
    spans = []
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = text.find(opener), text.rfind(closer)
        if 0 <= start < end:
            spans.append(text[start : end + 1])
    candidates += sorted(spans, key=len, reverse=True)
    for candidate in candidates:
        if not candidate:
            continue
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue
    return None
