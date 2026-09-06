"""固有名詞インデックス。人名・作品名・場所などで記憶を横断できるようにする。"""

from __future__ import annotations

import json
from typing import Sequence

from .db import Database, now


def upsert(db: Database, name: str, kind: str = "", aliases: Sequence[str] = ()) -> int:
    name = name.strip()
    row = db.one("SELECT id, aliases_json FROM entities WHERE name=?", (name,))
    if row is not None:
        if aliases:
            merged = sorted(set(json.loads(row["aliases_json"])) | set(aliases))
            db.execute(
                "UPDATE entities SET aliases_json=? WHERE id=?",
                (json.dumps(merged, ensure_ascii=False), row["id"]),
            )
        return row["id"]
    cursor = db.execute(
        "INSERT INTO entities(name, kind, aliases_json, created_at) VALUES(?,?,?,?)",
        (name, kind, json.dumps(list(aliases), ensure_ascii=False), now()),
    )
    return cursor.lastrowid


def attach(db: Database, note_id: int, entity_id: int) -> None:
    db.execute(
        "INSERT OR IGNORE INTO note_entities(note_id, entity_id) VALUES(?,?)", (note_id, entity_id)
    )


def notes_for(db: Database, name: str) -> list[int]:
    rows = db.query(
        """SELECT ne.note_id FROM note_entities ne
           JOIN entities e ON e.id = ne.entity_id
           WHERE e.name = ?""",
        (name.strip(),),
    )
    return [row["note_id"] for row in rows]


def counts(db: Database, limit: int = 20) -> list[tuple[str, int]]:
    rows = db.query(
        """SELECT e.name, COUNT(ne.note_id) AS n FROM entities e
           LEFT JOIN note_entities ne ON ne.entity_id = e.id
           GROUP BY e.id ORDER BY n DESC, e.name LIMIT ?""",
        (limit,),
    )
    return [(row["name"], row["n"]) for row in rows]
