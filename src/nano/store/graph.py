"""記憶グラフ。Neo4j は使わない — 1〜2ホップしか辿らないので SQLite で足りる。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .db import Database, now

RELATIONS = (
    "similar",       # 意味が近い
    "elaborates",    # 詳しくしている
    "causes",        # 原因→結果
    "contradicts",   # 矛盾している（無意識が後で解決を試みる）
    "temporal_next", # 時間的に続く
    "about_entity",  # 同じ固有名詞について
    "merged_from",   # 統合ノート → 元ノート
)


@dataclass
class Link:
    src_id: int
    dst_id: int
    relation: str
    weight: float


def add(
    db: Database,
    src_id: int,
    dst_id: int,
    relation: str = "similar",
    weight: float = 0.5,
    created_by: str = "unconscious",
    symmetric: bool = False,
) -> None:
    if src_id == dst_id:
        return
    pairs = [(src_id, dst_id)]
    if symmetric:
        pairs.append((dst_id, src_id))
    for a, b in pairs:
        db.execute(
            """INSERT INTO links(src_id, dst_id, relation, weight, created_by, created_at)
               VALUES(?,?,?,?,?,?)
               ON CONFLICT(src_id, dst_id, relation)
               DO UPDATE SET weight=max(links.weight, excluded.weight)""",
            (a, b, relation, weight, created_by, now()),
        )


def neighbors(db: Database, note_id: int, fanout: int = 3, states: Sequence[str] = ("active",)) -> list[Link]:
    placeholders = ",".join("?" * len(states))
    rows = db.query(
        f"""SELECT l.src_id, l.dst_id, l.relation, l.weight
            FROM links l JOIN notes n ON n.id = l.dst_id
            WHERE l.src_id = ? AND n.state IN ({placeholders})
            ORDER BY l.weight DESC LIMIT ?""",
        [note_id, *states, fanout],
    )
    return [Link(row["src_id"], row["dst_id"], row["relation"], row["weight"]) for row in rows]


def expand(
    db: Database,
    seed_ids: Sequence[int],
    hops: int = 1,
    fanout: int = 2,
    states: Sequence[str] = ("active",),
) -> dict[int, tuple[int, int]]:
    """種ノートから連想を広げる。返り値: {note_id: (ホップ数, 辿り元)}。

    種そのものは含めない。ここで拾われた記憶が「連想で思い出したこと」になる。
    """
    seen = set(seed_ids)
    found: dict[int, tuple[int, int]] = {}
    frontier = list(seed_ids)
    for hop in range(1, hops + 1):
        next_frontier: list[int] = []
        for note_id in frontier:
            for link in neighbors(db, note_id, fanout=fanout, states=states):
                if link.dst_id in seen:
                    continue
                seen.add(link.dst_id)
                found[link.dst_id] = (hop, note_id)
                next_frontier.append(link.dst_id)
        frontier = next_frontier
        if not frontier:
            break
    return found


def degrees(db: Database, note_ids: Iterable[int]) -> dict[int, int]:
    note_ids = list(note_ids)
    if not note_ids:
        return {}
    placeholders = ",".join("?" * len(note_ids))
    # 相互リンクを二重に数えないよう、相手ノートの異なり数を取る
    rows = db.query(
        f"""SELECT id, (
                SELECT COUNT(*) FROM (
                    SELECT dst_id AS other FROM links WHERE src_id = notes.id
                    UNION
                    SELECT src_id AS other FROM links WHERE dst_id = notes.id
                )
            ) AS degree
            FROM notes WHERE id IN ({placeholders})""",
        note_ids,
    )
    return {row["id"]: row["degree"] for row in rows}
