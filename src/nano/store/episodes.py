"""エピソード＝会話の塊。要約の単位であり、ノートの出所。"""

from __future__ import annotations

from dataclasses import dataclass

from .db import Database, now


@dataclass
class Episode:
    id: int
    session_id: str
    started_at: float
    ended_at: float
    summary: str
    salience: float
    mood: str

    @classmethod
    def from_row(cls, row) -> "Episode":
        return cls(
            id=row["id"],
            session_id=row["session_id"],
            started_at=row["started_at"],
            ended_at=row["ended_at"],
            summary=row["summary"],
            salience=row["salience"],
            mood=row["mood"],
        )


def create(
    db: Database,
    session_id: str,
    started_at: float,
    ended_at: float,
    summary: str = "",
    salience: float = 0.5,
    mood: str = "",
) -> Episode:
    cursor = db.execute(
        """INSERT INTO episodes(session_id, started_at, ended_at, summary, salience, mood, created_at)
           VALUES(?,?,?,?,?,?,?)""",
        (session_id, started_at, ended_at, summary, salience, mood, now()),
    )
    return Episode(cursor.lastrowid, session_id, started_at, ended_at, summary, salience, mood)


def get(db: Database, episode_id: int) -> Episode | None:
    row = db.one("SELECT * FROM episodes WHERE id=?", (episode_id,))
    return None if row is None else Episode.from_row(row)


def recent(db: Database, limit: int = 10) -> list[Episode]:
    rows = db.query("SELECT * FROM episodes ORDER BY ended_at DESC LIMIT ?", (limit,))
    return [Episode.from_row(row) for row in rows]
