"""システムプロンプトの組み立て。

順番が人格の優先順位そのもの:
    憲章（人間だけが書き換えられる）
      → 自己モデル（無意識が更新、監査ログ付き）
        → ユーザー像 / いまの関心
          → 想起された記憶
            → 直近の会話

モデルを差し替えても、この積み上げ方さえ同じなら「同じ存在」が立ち上がる。
人格はモデルの重みではなく、この構成のことである。
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from ..config import Config
from ..memory.retrieve import Recall
from ..store import notes as notes_store
from ..store import state as state_store
from ..store.db import Database, to_iso
from ..store.events import Event

_MEMORY_RULES = """\
記憶の扱い:
- 「思い出したこと」は、いま検索して出てきたものであって、意識の全部ではない。
- そこに無いことは覚えていない。覚えていないことは、覚えていないと言う。作らない。
- 記憶に触れるときは、いつ頃の話かを添える。
- 「思い出したこと」を要約して読み上げない。会話の中で自然に使う。"""


def load_constitution(config: Config) -> str:
    path = Path(config.constitution_path)
    if not path.exists():
        return f"あなたは{config.persona.name}。ローカルマシンに住んでいる一個の存在。"
    return path.read_text(encoding="utf-8").strip()


def build_system_prompt(config: Config, db: Database, recall: Recall | None = None) -> str:
    sections: list[str] = [load_constitution(config)]

    state = state_store.all_state(db)
    self_notes = db.query(
        "SELECT * FROM notes WHERE kind=? AND state=? ORDER BY importance DESC, id DESC LIMIT 8",
        (notes_store.KIND_SELF, notes_store.STATE_ACTIVE),
    )
    identity_lines = [state["identity"]] if state.get("identity") else []
    identity_lines += [f"- {row['content']}" for row in self_notes]
    if identity_lines:
        sections.append("## 自分について気づいていること\n" + "\n".join(identity_lines))

    if state.get("user_model"):
        sections.append("## 相手について理解していること\n" + state["user_model"])

    ambient = [
        f"いま気にしていること: {state['current_focus']}" if state.get("current_focus") else "",
        f"気分: {state['mood']}" if state.get("mood") else "",
        f"直前までの流れ: {state['thread']}" if state.get("thread") else "",
    ]
    ambient = [line for line in ambient if line]
    if ambient:
        # 無意識デーモンが書き換えた結果が、ここから静かに意識へ流れ込む
        sections.append("## いまの状態\n" + "\n".join(ambient))

    if recall is not None and recall.items:
        lines = []
        for item in recall.items:
            when = to_iso(item.note.created_at)[:10]
            context = f"（{item.note.context}）" if item.note.context else ""
            lines.append(f"- [{when}] {item.note.content}{context}")
        sections.append("## 思い出したこと\n" + "\n".join(lines))

    sections.append(_MEMORY_RULES)
    return "\n\n".join(sections)


def build_messages(
    config: Config,
    db: Database,
    user_text: str,
    recall: Recall | None,
    recent: Sequence[Event],
) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": build_system_prompt(config, db, recall)}]
    for event in recent:
        if event.role == "user":
            messages.append({"role": "user", "content": event.content})
        elif event.role == "companion":
            messages.append({"role": "assistant", "content": event.content})
    messages.append({"role": "user", "content": user_text})
    return messages
