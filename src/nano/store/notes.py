"""記憶ノートの CRUD とベクトル検索。

ベクトル検索は素朴な総当たり。個人の生涯分（10^5〜10^6ノート）なら
1024次元でも数十ms で終わるので、専用のベクトルDBは導入しない。
将来 sqlite-vec を差し込むとしても、保存形式(BLOB)はそのまま使える。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from .. import vectors
from .db import Database, now

STATE_ACTIVE = "active"
STATE_COLD = "cold"
STATE_MERGED = "merged"

KIND_FACT = "fact"
KIND_PREFERENCE = "preference"
KIND_EPISODE = "episode"
KIND_REFLECTION = "reflection"
KIND_SELF = "self"


@dataclass
class Note:
    id: int
    created_at: float
    kind: str
    content: str
    context: str = ""
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    category: str = ""
    importance: float = 0.5
    half_life_days: float = 3.0
    last_accessed_at: float = 0.0
    access_count: int = 0
    state: str = STATE_ACTIVE
    merged_into: int | None = None
    pinned: bool = False
    source_episode_id: int | None = None

    @classmethod
    def from_row(cls, row) -> "Note":
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            kind=row["kind"],
            content=row["content"],
            context=row["context"],
            keywords=json.loads(row["keywords_json"]),
            tags=json.loads(row["tags_json"]),
            category=row["category"],
            importance=row["importance"],
            half_life_days=row["half_life_days"],
            last_accessed_at=row["last_accessed_at"],
            access_count=row["access_count"],
            state=row["state"],
            merged_into=row["merged_into"],
            pinned=bool(row["pinned"]),
            source_episode_id=row["source_episode_id"],
        )

    def searchable_text(self) -> str:
        parts = [self.content, self.context, " ".join(self.keywords), " ".join(self.tags)]
        return "\n".join(part for part in parts if part)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at,
            "kind": self.kind,
            "content": self.content,
            "context": self.context,
            "keywords": self.keywords,
            "tags": self.tags,
            "category": self.category,
            "importance": self.importance,
            "half_life_days": self.half_life_days,
            "last_accessed_at": self.last_accessed_at,
            "access_count": self.access_count,
            "state": self.state,
            "merged_into": self.merged_into,
            "pinned": self.pinned,
            "source_episode_id": self.source_episode_id,
        }


def insert(
    db: Database,
    content: str,
    *,
    kind: str = KIND_FACT,
    context: str = "",
    keywords: Sequence[str] = (),
    tags: Sequence[str] = (),
    category: str = "",
    importance: float = 0.5,
    half_life_days: float = 3.0,
    pinned: bool = False,
    source_episode_id: int | None = None,
    created_at: float | None = None,
) -> Note:
    created_at = now() if created_at is None else created_at
    cursor = db.execute(
        """INSERT INTO notes(created_at, kind, content, context, keywords_json, tags_json,
                             category, importance, half_life_days, last_accessed_at,
                             pinned, source_episode_id)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            created_at,
            kind,
            content,
            context,
            json.dumps(list(keywords), ensure_ascii=False),
            json.dumps(list(tags), ensure_ascii=False),
            category,
            importance,
            half_life_days,
            created_at,
            int(pinned),
            source_episode_id,
        ),
    )
    note = get(db, cursor.lastrowid)
    assert note is not None
    _index_fts(db, note)
    return note


def get(db: Database, note_id: int) -> Note | None:
    row = db.one("SELECT * FROM notes WHERE id=?", (note_id,))
    return None if row is None else Note.from_row(row)


def get_many(db: Database, note_ids: Sequence[int]) -> list[Note]:
    if not note_ids:
        return []
    placeholders = ",".join("?" * len(note_ids))
    rows = db.query(f"SELECT * FROM notes WHERE id IN ({placeholders})", list(note_ids))
    by_id = {row["id"]: Note.from_row(row) for row in rows}
    return [by_id[note_id] for note_id in note_ids if note_id in by_id]


def iter_notes(db: Database, states: Sequence[str] = (STATE_ACTIVE,)) -> list[Note]:
    placeholders = ",".join("?" * len(states))
    rows = db.query(f"SELECT * FROM notes WHERE state IN ({placeholders}) ORDER BY id", list(states))
    return [Note.from_row(row) for row in rows]


def update_context(db: Database, note_id: int, context: str) -> None:
    """A-MEM の肝: 新しい記憶が入ると、既存記憶の文脈も書き換わる。"""
    db.execute("UPDATE notes SET context=? WHERE id=?", (context, note_id))
    note = get(db, note_id)
    if note is not None:
        _index_fts(db, note)


def set_state(db: Database, note_id: int, state: str, merged_into: int | None = None) -> None:
    db.execute(
        "UPDATE notes SET state=?, merged_into=? WHERE id=?", (state, merged_into, note_id)
    )


def set_half_life(db: Database, note_id: int, half_life_days: float) -> None:
    db.execute("UPDATE notes SET half_life_days=? WHERE id=?", (half_life_days, note_id))


def touch(db: Database, note_ids: Iterable[int], *, gain: float, cap: float, at: float | None = None) -> None:
    """想起されたノートを強化する（間隔反復）。使う記憶ほど忘れにくくなる。"""
    at = now() if at is None else at
    for note_id in note_ids:
        note = get(db, note_id)
        if note is None:
            continue
        grown = note.half_life_days * (1.0 + gain * (0.5 + note.importance))
        db.execute(
            """UPDATE notes
               SET last_accessed_at=?, access_count=access_count+1, half_life_days=?
               WHERE id=?""",
            (at, min(grown, cap), note_id),
        )


def set_vector(db: Database, note_id: int, vector: Sequence[float]) -> None:
    db.execute(
        "INSERT INTO note_vectors(note_id, dim, vec) VALUES(?,?,?) "
        "ON CONFLICT(note_id) DO UPDATE SET dim=excluded.dim, vec=excluded.vec",
        (note_id, len(vector), vectors.pack(vector)),
    )


def get_vector(db: Database, note_id: int) -> list[float] | None:
    row = db.one("SELECT vec FROM note_vectors WHERE note_id=?", (note_id,))
    return None if row is None else vectors.unpack(row["vec"])


def _index_fts(db: Database, note: Note) -> None:
    db.execute("DELETE FROM notes_fts WHERE note_id=?", (note.id,))
    db.execute(
        "INSERT INTO notes_fts(note_id, text) VALUES(?,?)", (note.id, note.searchable_text())
    )


def text_search(db: Database, query: str, limit: int = 20, include_cold: bool = True) -> list[Note]:
    """「〇〇覚えてる?」用の明示検索。cold な記憶もここでは掘り起こせる。

    trigram トークナイザは3文字未満を索引できないため、短い語（「мио」「猫」など
    日本語では珍しくない）は LIKE で拾う。日本語を捨てない方を優先する。
    """
    states = (STATE_ACTIVE, STATE_COLD, STATE_MERGED) if include_cold else (STATE_ACTIVE,)
    placeholders = ",".join("?" * len(states))
    found: dict[int, Note] = {}

    if len(query.strip()) >= 3:
        rows = db.query(
            f"""SELECT n.* FROM notes_fts f
                JOIN notes n ON n.id = f.note_id
                WHERE notes_fts MATCH ? AND n.state IN ({placeholders})
                ORDER BY rank LIMIT ?""",
            [_fts_escape(query), *states, limit],
        )
        found = {row["id"]: Note.from_row(row) for row in rows}

    if len(found) < limit:
        like = "%" + query.strip().replace("%", r"\%").replace("_", r"\_") + "%"
        rows = db.query(
            f"""SELECT * FROM notes
                WHERE state IN ({placeholders})
                  AND (content LIKE ? ESCAPE '\\' OR context LIKE ? ESCAPE '\\'
                       OR keywords_json LIKE ? ESCAPE '\\' OR tags_json LIKE ? ESCAPE '\\')
                ORDER BY importance DESC, id DESC LIMIT ?""",
            [*states, like, like, like, like, limit],
        )
        for row in rows:
            found.setdefault(row["id"], Note.from_row(row))

    return list(found.values())[:limit]


def _fts_escape(query: str) -> str:
    return '"' + query.replace('"', '""') + '"'


class VectorIndex:
    """総当たり kNN。プロセス内にベクトルを保持し、追加は追記で済ませる。"""

    def __init__(self, db: Database) -> None:
        self.db = db
        self._ids: list[int] = []
        self._vecs: list[list[float]] = []
        self._states: list[str] = []
        self._pos: dict[int, int] = {}
        self._loaded = False

    def load(self) -> None:
        rows = self.db.query(
            "SELECT v.note_id, v.vec, n.state FROM note_vectors v JOIN notes n ON n.id = v.note_id"
        )
        self._ids = [row["note_id"] for row in rows]
        self._vecs = [vectors.unpack(row["vec"]) for row in rows]
        self._states = [row["state"] for row in rows]
        self._pos = {note_id: index for index, note_id in enumerate(self._ids)}
        self._loaded = True

    def _ensure(self) -> None:
        if not self._loaded:
            self.load()

    def add(self, note_id: int, vector: Sequence[float], state: str = STATE_ACTIVE) -> None:
        self._ensure()
        if note_id in self._pos:
            position = self._pos[note_id]
            self._vecs[position] = list(vector)
            self._states[position] = state
            return
        self._pos[note_id] = len(self._ids)
        self._ids.append(note_id)
        self._vecs.append(list(vector))
        self._states.append(state)

    def set_state(self, note_id: int, state: str) -> None:
        self._ensure()
        position = self._pos.get(note_id)
        if position is not None:
            self._states[position] = state

    def search(
        self,
        query: Sequence[float],
        k: int,
        states: Sequence[str] = (STATE_ACTIVE,),
        exclude: Sequence[int] = (),
    ) -> list[tuple[int, float]]:
        self._ensure()
        if not self._ids:
            return []
        allowed = set(states)
        blocked = set(exclude)
        scores = vectors.similarities(query, self._vecs)
        hits = [
            (note_id, score)
            for note_id, score, state in zip(self._ids, scores, self._states)
            if state in allowed and note_id not in blocked
        ]
        hits.sort(key=lambda item: item[1], reverse=True)
        return hits[:k]

    def vector_of(self, note_id: int) -> list[float] | None:
        self._ensure()
        position = self._pos.get(note_id)
        return None if position is None else self._vecs[position]

    def __len__(self) -> int:
        self._ensure()
        return len(self._ids)
