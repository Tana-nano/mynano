"""⭐ — 人間が「これがわたしだ」と認めた応答の印。

M4（人格の固定）の入口。QLoRA の教師データは、ここに集まったものだけから作る。
自動で付けない。無意識にも付けさせない。人格を書き換えうる材料を機械が選び始めた
時点で、承認フロー（禁則5）と同じ穴が開くため。

保存するのは「応答」ではなく「そのとき実際にモデルへ渡した messages と応答の対」。
理由は schema.sql に書いた通りで、あとからプロンプトを組み直すと想起される記憶が
変わっており、モデルが見ていない材料から答えを出す訓練になってしまう。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from .db import Database, now

RATING_KEEP = 1  # こう在ってほしい（教師データ）
RATING_AVOID = -1  # こうは喋ってほしくない


@dataclass
class Star:
    event_id: int
    rating: int
    reason: str
    prompt: list[dict[str, str]]
    created_at: float
    updated_at: float
    created_by: str
    model: str = ""    # この応答を出した対話モデル
    adapter: str = ""  # そのとき当てていた LoRA アダプタ（無ければ空）

    @classmethod
    def from_row(cls, row) -> "Star":
        keys = row.keys()
        return cls(
            event_id=row["event_id"],
            rating=row["rating"],
            reason=row["reason"],
            prompt=json.loads(row["prompt_json"] or "[]"),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            created_by=row["created_by"],
            model=row["model"] if "model" in keys else "",
            adapter=row["adapter"] if "adapter" in keys else "",
        )


@dataclass
class StarredTurn:
    """⭐ と、それが指している会話。教師データ1件分の材料がすべてここに揃う。"""

    star: Star
    session_id: str
    ts: float
    user_text: str
    answer: str

    @classmethod
    def from_row(cls, row) -> "StarredTurn":
        return cls(
            star=Star.from_row(row),
            session_id=row["session_id"],
            ts=row["ts"],
            # 直前の user 発話は prompt の末尾に必ず居る（compose.build_messages の形）
            user_text=_last_user_text(json.loads(row["prompt_json"] or "[]")),
            answer=row["content"],
        )


def _last_user_text(prompt: Sequence[dict[str, Any]]) -> str:
    for message in reversed(list(prompt)):
        if message.get("role") == "user":
            return str(message.get("content", ""))
    return ""


def put(
    db: Database,
    event_id: int,
    rating: int,
    prompt: Sequence[dict[str, str]],
    reason: str = "",
    created_by: str = "human",
    model: str = "",
    adapter: str = "",
) -> Star:
    """印を付ける（付け直しも同じ経路）。

    model / adapter は「この応答を出したのは誰か」。⭐ は応答への印なので、
    LoRA を当てた前後で同じ意味を持たない。混ぜたまま次の教師データにすると、
    当てたはずの訛りを自分自身から学び直すことになる（docs/finetune.md）。
    """
    timestamp = now()
    prompt_json = json.dumps(list(prompt), ensure_ascii=False)
    db.execute(
        "INSERT INTO stars(event_id, rating, reason, prompt_json, created_at, updated_at, "
        "                  created_by, model, adapter) "
        "VALUES(?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(event_id) DO UPDATE SET "
        "  rating=excluded.rating, reason=excluded.reason, "
        "  prompt_json=excluded.prompt_json, updated_at=excluded.updated_at",
        (event_id, rating, reason, prompt_json, timestamp, timestamp, created_by, model, adapter),
    )
    row = db.one("SELECT * FROM stars WHERE event_id=?", (event_id,))
    return Star.from_row(row)


def remove(db: Database, event_id: int) -> bool:
    """印を外す。消えるのは印だけで、生ログ（events）には指一本触れない（禁則1）。

    外した記録は平文ミラー（archive/stars.jsonl）に追記されるので、
    「いつ ⭐ を取り消したか」も後から辿れる。
    """
    cursor = db.execute("DELETE FROM stars WHERE event_id=?", (event_id,))
    return cursor.rowcount > 0


def get(db: Database, event_id: int) -> Star | None:
    row = db.one("SELECT * FROM stars WHERE event_id=?", (event_id,))
    return Star.from_row(row) if row else None


def recent(db: Database, limit: int = 20, rating: int | None = None) -> list[StarredTurn]:
    sql = (
        "SELECT s.*, e.session_id, e.ts, e.content FROM stars s "
        "JOIN events e ON e.id = s.event_id "
    )
    params: list[Any] = []
    if rating is not None:
        sql += "WHERE s.rating = ? "
        params.append(rating)
    sql += "ORDER BY e.ts DESC, e.id DESC LIMIT ?"
    params.append(limit)
    return [StarredTurn.from_row(row) for row in db.query(sql, params)]


def counts(db: Database) -> dict[str, int]:
    rows = db.query("SELECT rating, COUNT(*) AS n FROM stars GROUP BY rating")
    by_rating = {row["rating"]: row["n"] for row in rows}
    return {
        "keep": by_rating.get(RATING_KEEP, 0),
        "avoid": by_rating.get(RATING_AVOID, 0),
    }
