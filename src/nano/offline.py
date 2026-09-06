"""オフライン用のスタブLLM。

GPU もモデルも無い環境で、記憶パイプラインの配線・忘却・想起・CUI を
最後まで通して確かめるためのもの。意味は理解しないが、
各タスクが期待する形の JSON を規則的に返す。

テストと CI がこれで完結する（＝ローカルモデルの有無に関係なく回帰を検出できる）
ことが、長く手を入れ続けるうえで効いてくる。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .gate import CancelToken

_TOKEN = re.compile(r"[ァ-ヴー]{2,}|[一-龥]{2,}|[A-Za-z][A-Za-z0-9]+|[0-9]+[年月日時分]?")
_SPEAKER = re.compile(r"^\[[^\]]*\]\s*([^:]+):\s*(.*)$")
# 重要度の目安に使う語。本物のLLMは文脈から判断するが、スタブは語で近似する。
# ここは「意味の理解」ではなく配線検証用の粗い代用であることを忘れないこと。
_IMPORTANT = (
    "名前", "約束", "好き", "嫌い", "苦手", "誕生日", "大事", "大切", "決め", "予定",
    "妹", "姉", "兄", "弟", "父", "母", "住ん", "職場", "引っ越", "歳",
)


def keywords_of(text: str, limit: int = 5) -> list[str]:
    seen: list[str] = []
    for match in _TOKEN.findall(text):
        if match not in seen:
            seen.append(match)
    return seen[:limit]


def _importance(text: str) -> float:
    score = 0.15 + 0.18 * sum(1 for marker in _IMPORTANT if marker in text)
    return round(min(0.95, score), 2)


def _user_lines(transcript: str) -> list[str]:
    lines: list[str] = []
    for raw in transcript.splitlines():
        match = _SPEAKER.match(raw.strip())
        if match is None:
            continue
        speaker, content = match.group(1).strip(), match.group(2).strip()
        if speaker == "ユーザー" and content:
            lines.append(content)
    return lines


def _sentences(text: str) -> list[str]:
    parts = [part.strip() for part in re.split(r"[。\n]", text) if part.strip()]
    return parts or [text.strip()]


@dataclass
class OfflineLLM:
    """LLM プロトコルのスタブ実装。task 名で分岐する。"""

    max_notes: int = 12
    handlers: dict[str, Callable[[Sequence[dict]], Any]] = field(default_factory=dict)

    def chat(
        self,
        messages: Sequence[dict[str, str]],
        *,
        task: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        cancel: CancelToken | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        if cancel is not None:
            cancel.raise_if_cancelled()
        text = self._dispatch(task, messages)
        if not isinstance(text, str):
            text = json.dumps(text, ensure_ascii=False)
        if on_token is not None:
            for chunk in text:
                on_token(chunk)
        return text

    def chat_json(
        self,
        messages: Sequence[dict[str, str]],
        *,
        task: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        cancel: CancelToken | None = None,
    ) -> Any:
        payload = self._dispatch(task, messages)
        return json.loads(payload) if isinstance(payload, str) else payload

    # --- 内部 ---
    def _dispatch(self, task: str, messages: Sequence[dict[str, str]]) -> Any:
        handler = self.handlers.get(task)
        if handler is not None:
            return handler(messages)
        method = getattr(self, f"_task_{task}", None)
        if method is not None:
            return method(messages)
        return self._task_reply(messages)

    @staticmethod
    def _last_user(messages: Sequence[dict[str, str]]) -> str:
        for message in reversed(messages):
            if message["role"] == "user":
                return message["content"]
        return ""

    def _task_summarize_episode(self, messages) -> dict:
        content = self._last_user(messages)
        lines = _user_lines(content)
        summary = " / ".join(lines[:3]) or "(内容なし)"
        return {"summary": summary, "salience": _importance(content), "mood": "平常"}

    def _task_extract_notes(self, messages) -> dict:
        content = self._last_user(messages)
        notes = []
        for line in _user_lines(content):
            for sentence in _sentences(line):
                if len(sentence) < 4:
                    continue
                notes.append(
                    {
                        "content": sentence,
                        "context": "ユーザーが話したこと",
                        "keywords": keywords_of(sentence),
                        "tags": ["offline"],
                        "category": "会話",
                        "kind": "fact",
                        "importance": _importance(sentence),
                    }
                )
                if len(notes) >= self.max_notes:
                    break
            if len(notes) >= self.max_notes:
                break
        entities = []
        for note in notes:
            for keyword in note["keywords"][:2]:
                if keyword not in [entity["name"] for entity in entities]:
                    entities.append({"name": keyword, "kind": "concept"})
        return {"notes": notes, "entities": entities[:8]}

    def _task_judge_links(self, messages) -> dict:
        content = self._last_user(messages)
        links = []
        for note_id, similarity in re.findall(r"\[(\d+)\] \(類似度([0-9.]+)\)", content):
            links.append(
                {
                    "id": int(note_id),
                    "relation": "similar",
                    "weight": float(similarity),
                    "revised_context": None,
                }
            )
        return {"links": links}

    def _task_consolidate(self, messages) -> dict:
        content = self._last_user(messages)
        items = [line[2:] for line in content.splitlines() if line.startswith("- ")]
        joined = " / ".join(items[:5])
        return {
            "content": f"かつて話した内容のまとまり: {joined}",
            "context": "薄れた記憶を統合したもの",
            "keywords": keywords_of(joined),
            "tags": ["offline"],
            "category": "統合",
            "importance": 0.5,
        }

    def _task_reflect(self, messages) -> dict:
        content = self._last_user(messages)
        items = [line[2:] for line in content.splitlines() if line.startswith("- ")]
        if not items:
            return {"insights": []}
        return {
            "insights": [
                {
                    "content": f"最近は「{keywords_of(' '.join(items), 3)}」に関する話が多い",
                    "importance": 0.5,
                    "evidence": [],
                }
            ]
        }

    def _task_reply(self, messages) -> str:
        system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        recalled = []
        capture = False
        for line in system.splitlines():
            if line.startswith("## 思い出したこと"):
                capture = True
                continue
            if capture:
                if line.startswith("##") or not line.strip():
                    break
                recalled.append(line.strip("- ").strip())
        user = self._last_user(messages)
        if recalled:
            return f"（オフライン応答）{user} — 思い出したこと: {recalled[0]}"
        return f"（オフライン応答）{user}"
