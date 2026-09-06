"""生ログ。追記専用。ここだけは何があっても失わない。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .db import Database, now

ROLE_USER = "user"
ROLE_COMPANION = "companion"
ROLE_WORLD = "world"  # 外部から取り込んだ情報（無意識の ingest 由来）


@dataclass
class Event:
    id: int
    ts: float
    session_id: str
    role: str
    content: str
    meta: dict[str, Any]
    episode_id: int | None

    @classmethod
    def from_row(cls, row) -> "Event":
        return cls(
            id=row["id"],
            ts=row["ts"],
            session_id=row["session_id"],
            role=row["role"],
            content=row["content"],
            meta=json.loads(row["meta_json"]),
            episode_id=row["episode_id"],
        )


def append(
    db: Database,
    session_id: str,
    role: str,
    content: str,
    meta: dict[str, Any] | None = None,
    ts: float | None = None,
) -> Event:
    ts = now() if ts is None else ts
    cursor = db.execute(
        "INSERT INTO events(ts, session_id, role, content, meta_json) VALUES(?,?,?,?,?)",
        (ts, session_id, role, content, json.dumps(meta or {}, ensure_ascii=False)),
    )
    return Event(cursor.lastrowid, ts, session_id, role, content, meta or {}, None)


def pending(db: Database, limit: int = 500) -> list[Event]:
    """まだエピソード化されていない生ログ＝無意識の未処理分。"""
    rows = db.query(
        "SELECT * FROM events WHERE episode_id IS NULL ORDER BY ts, id LIMIT ?", (limit,)
    )
    return [Event.from_row(row) for row in rows]


def recent(db: Database, session_id: str, limit: int = 12) -> list[Event]:
    rows = db.query(
        "SELECT * FROM events WHERE session_id=? ORDER BY ts DESC, id DESC LIMIT ?",
        (session_id, limit),
    )
    return [Event.from_row(row) for row in reversed(rows)]


def assign_episode(db: Database, event_ids: list[int], episode_id: int) -> None:
    db.conn.executemany(
        "UPDATE events SET episode_id=? WHERE id=?", [(episode_id, eid) for eid in event_ids]
    )
