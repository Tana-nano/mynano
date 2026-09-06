"""グラフ描画用のデータを soul.db から組み立てる。

方針:
- **merged なノートは畳む。** 統合された記憶は親に吸収して1つの点として描き、
  リンクも親へ付け替える。畳まないと、統合の履歴がグラフを埋め尽くす。
- **cold なノートは残す。** 薄く描く。忘れかけている記憶が見えることに意味がある。
- 大きくなりすぎたら重要度と想起可能性で上位を切り出す。全部描いても読めない。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from ..memory.decay import retrievability
from ..store import notes as notes_store
from ..store.db import Database, now, to_iso
from ..store.notes import Note

DEFAULT_LIMIT = 400

# 無意識が自分で作った記憶。「寝ている間に考えていたこと」がこれで見分けられる。
UNCONSCIOUS_TAGS = frozenset({"associate", "reflection", "consolidated"})

# 色を割り当てる唯一の軸は「その記憶を誰が作ったか」。
# 分類やタグで塗り分けたくなるが、色数が増えると色覚特性のある人には
# 区別できなくなる（全ペア検証を通るのは3色まで）。そして実際に見たいのは
# 「これは自分が話したこと / これは nano が寝ている間に考えたこと」の区別である。
ORIGIN_SELF = "self"            # あなたが話したこと
ORIGIN_UNCONSCIOUS = "unconscious"  # 無意識が作ったこと
ORIGIN_WORLD = "world"          # 外界から入ってきたこと


@dataclass
class GraphPayload:
    nodes: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    stats: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"nodes": self.nodes, "edges": self.edges, "stats": self.stats}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def _fold_target(note_id: int, merged_into: dict[int, int]) -> int:
    """merged の連鎖を辿って、最終的に生き残っている親を返す。"""
    seen = {note_id}
    current = note_id
    while current in merged_into:
        current = merged_into[current]
        if current in seen:  # 万一の循環（あってはならないが、描画で固まらせない）
            break
        seen.add(current)
    return current


def world_episodes(db: Database) -> set[int]:
    """外界から取り込んだイベントを含むエピソード。そこから出た記憶は「外来」。"""
    return {
        row["episode_id"]
        for row in db.query(
            "SELECT DISTINCT episode_id FROM events WHERE role='world' AND episode_id IS NOT NULL"
        )
    }


def _origin(note: Note, from_world: set[int]) -> str:
    if UNCONSCIOUS_TAGS & set(note.tags) or note.kind == notes_store.KIND_REFLECTION:
        return ORIGIN_UNCONSCIOUS
    if note.source_episode_id in from_world:
        return ORIGIN_WORLD
    return ORIGIN_SELF


def _node(
    note: Note,
    at: float,
    decay_config,
    degree: int,
    children: list[int],
    from_world: set[int],
) -> dict[str, Any]:
    tags = note.tags
    return {
        "id": note.id,
        "content": note.content,
        "context": note.context,
        "kind": note.kind,
        "category": note.category or "(未分類)",
        "tags": tags,
        "keywords": note.keywords,
        "importance": round(note.importance, 3),
        "halfLife": round(note.half_life_days, 2),
        # 想起可能性がそのまま「記憶の濃さ」になる。薄れている記憶は薄く描かれる。
        "retrievability": round(retrievability(note, at, decay_config), 4),
        "accessCount": note.access_count,
        "state": note.state,
        "pinned": note.pinned,
        "created": to_iso(note.created_at)[:10],
        "lastAccessed": to_iso(note.last_accessed_at)[:10],
        "episode": note.source_episode_id,
        "degree": degree,
        "mergedChildren": children,
        "origin": _origin(note, from_world),
    }


def build(db: Database, decay_config, limit: int = DEFAULT_LIMIT, at: float | None = None) -> GraphPayload:
    at = now() if at is None else at

    every = notes_store.iter_notes(
        db, states=(notes_store.STATE_ACTIVE, notes_store.STATE_COLD, notes_store.STATE_MERGED)
    )
    by_id = {note.id: note for note in every}
    merged_into = {
        note.id: note.merged_into
        for note in every
        if note.state == notes_store.STATE_MERGED and note.merged_into
    }

    visible = [note for note in every if note.state != notes_store.STATE_MERGED]
    children: dict[int, list[int]] = {}
    for note_id in merged_into:
        parent = _fold_target(note_id, merged_into)
        if parent in by_id and parent != note_id:
            children.setdefault(parent, []).append(note_id)

    # 描ききれない量になったら、いま効いている記憶から順に切り出す
    if len(visible) > limit:
        visible.sort(
            key=lambda note: (
                note.state == notes_store.STATE_ACTIVE,
                note.importance * retrievability(note, at, decay_config),
            ),
            reverse=True,
        )
        visible = visible[:limit]

    kept = {note.id for note in visible}
    edges = _edges(db, kept, merged_into, by_id)

    degree: dict[int, int] = {}
    for edge in edges:
        degree[edge["source"]] = degree.get(edge["source"], 0) + 1
        degree[edge["target"]] = degree.get(edge["target"], 0) + 1

    from_world = world_episodes(db)
    nodes = [
        _node(note, at, decay_config, degree.get(note.id, 0), children.get(note.id, []), from_world)
        for note in visible
    ]
    nodes.sort(key=lambda node: node["id"])

    return GraphPayload(nodes=nodes, edges=edges, stats=_stats(db, every, nodes, edges, at))


def _edges(
    db: Database, kept: set[int], merged_into: dict[int, int], by_id: dict[int, Note]
) -> list[dict[str, Any]]:
    """リンクを集める。merged なノートへの線は親へ付け替える。"""
    seen: dict[tuple[int, int, str], float] = {}
    for row in db.query("SELECT src_id, dst_id, relation, weight FROM links"):
        if row["relation"] == "merged_from":
            continue  # 統合の履歴は線ではなく、親ノードのバッジとして表す
        source = _fold_target(row["src_id"], merged_into)
        target = _fold_target(row["dst_id"], merged_into)
        if source == target or source not in kept or target not in kept:
            continue
        # 相互リンクは1本にまとめる（両方向に張ってあるので二重に描かない）
        key = (min(source, target), max(source, target), row["relation"])
        seen[key] = max(seen.get(key, 0.0), row["weight"])

    return [
        {"source": source, "target": target, "relation": relation, "weight": round(weight, 3)}
        for (source, target, relation), weight in seen.items()
    ]


def _stats(
    db: Database, every: list[Note], nodes: list[dict], edges: list[dict], at: float
) -> dict[str, Any]:
    states: dict[str, int] = {}
    for note in every:
        states[note.state] = states.get(note.state, 0) + 1
    relations: dict[str, int] = {}
    for edge in edges:
        relations[edge["relation"]] = relations.get(edge["relation"], 0) + 1
    return {
        "generatedAt": to_iso(at),
        "notesTotal": len(every),
        "shown": len(nodes),
        "edges": len(edges),
        "states": states,
        "relations": relations,
        "episodes": db.scalar("SELECT COUNT(*) FROM episodes") or 0,
        "origins": {
            origin: sum(1 for node in nodes if node["origin"] == origin)
            for origin in (ORIGIN_SELF, ORIGIN_UNCONSCIOUS, ORIGIN_WORLD)
        },
        "categories": sorted({node["category"] for node in nodes}),
        "kinds": sorted({node["kind"] for node in nodes}),
    }


def note_detail(db: Database, note_id: int, decay_config, at: float | None = None) -> dict[str, Any] | None:
    """クリックしたときに出す1件の詳細。統合された記憶の系譜も含める。"""
    at = now() if at is None else at
    note = notes_store.get(db, note_id)
    if note is None:
        return None

    detail = _node(note, at, decay_config, 0, [], world_episodes(db))
    detail["lineage"] = [
        {"id": row["id"], "content": row["content"], "created": to_iso(row["created_at"])[:10]}
        for row in db.query(
            """SELECT n.id, n.content, n.created_at FROM links l
               JOIN notes n ON n.id = l.dst_id
               WHERE l.src_id=? AND l.relation='merged_from' ORDER BY n.created_at""",
            (note_id,),
        )
    ]
    episode = db.one("SELECT summary FROM episodes WHERE id=?", (note.source_episode_id,))
    detail["episodeSummary"] = episode["summary"] if episode else ""
    return detail
