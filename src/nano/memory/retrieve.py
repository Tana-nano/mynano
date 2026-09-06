"""想起。

score = w_sim*類似度 + w_imp*重要度 + w_rec*想起可能性 + w_con*log1p(リンク次数)

Stanford の Generative Agents（relevance/recency/importance）に、
「よく繋がった記憶ほど思い出しやすい」という次数の項を足したもの。
さらに上位ノートからグラフを1ホップ辿る＝連想で芋づる式に思い出す。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from .. import vectors
from ..config import DecayConfig, RetrievalConfig
from ..embed import Embedder
from ..store import graph as graph_store
from ..store import notes as notes_store
from ..store.db import Database, now as clock
from ..store.notes import Note, VectorIndex
from .decay import retrievability


@dataclass
class Recalled:
    note: Note
    similarity: float
    retrievability: float
    degree: int
    score: float
    via: str  # "vector" | "graph←<id>"

    def explain(self) -> str:
        return (
            f"#{self.note.id} score={self.score:.3f} "
            f"(類似{self.similarity:.2f} 重要{self.note.importance:.2f} "
            f"想起{self.retrievability:.2f} 次数{self.degree} 経路={self.via})"
        )


@dataclass
class Recall:
    query: str
    items: list[Recalled] = field(default_factory=list)
    considered: int = 0

    @property
    def notes(self) -> list[Note]:
        return [item.note for item in self.items]

    def trace(self) -> str:
        """CUI の /why で出す。記憶が効いているか目視できないとチューニングできない。"""
        if not self.items:
            return f"想起なし（候補 {self.considered} 件を検討）"
        lines = [f"クエリ: {self.query}", f"候補 {self.considered} 件から {len(self.items)} 件を想起:"]
        for item in self.items:
            lines.append("  " + item.explain())
            lines.append(f"      {item.note.content}")
        return "\n".join(lines)


@dataclass
class _Candidate:
    note: Note
    similarity: float
    recall_prob: float
    degree: int
    via: str
    discount: float = 1.0


def _min_max(values: Sequence[float]) -> list[float]:
    """候補集合の中で 0..1 に正規化する。

    これをやらないと重みが意味を失う。埋め込みモデルのコサインは
    たいてい狭い帯（e5 なら 0.7〜0.9 など）に固まるので、生の値のまま
    重要度や想起可能性と足すと、関連度の差が他の項に押し潰される。
    Generative Agents が各成分を正規化しているのはこのため。
    """
    if not values:
        return []
    low, high = min(values), max(values)
    if high - low < 1e-9:
        return [0.5] * len(values)  # 差が無い＝順位に寄与しない
    return [(value - low) / (high - low) for value in values]


def _rank(
    candidates: list[_Candidate], retrieval: RetrievalConfig
) -> list[Recalled]:
    similarity = _min_max([c.similarity for c in candidates])
    importance = _min_max([c.note.importance for c in candidates])
    recall_prob = _min_max([c.recall_prob for c in candidates])
    connectivity = _min_max([math.log1p(c.degree) for c in candidates])

    ranked: list[Recalled] = []
    for index, candidate in enumerate(candidates):
        score = (
            retrieval.w_sim * similarity[index]
            + retrieval.w_imp * importance[index]
            + retrieval.w_rec * recall_prob[index]
            + retrieval.w_con * connectivity[index]
        ) * candidate.discount
        ranked.append(
            Recalled(
                note=candidate.note,
                similarity=candidate.similarity,
                retrievability=candidate.recall_prob,
                degree=candidate.degree,
                score=score,
                via=candidate.via,
            )
        )
    return ranked


def _mmr(
    candidates: list[Recalled], index: VectorIndex, top_k: int, lambda_: float
) -> list[Recalled]:
    """内容が重複した記憶で枠を潰さないための多様性選択。"""
    selected: list[Recalled] = []
    pool = sorted(candidates, key=lambda item: item.score, reverse=True)
    if not pool:
        return []
    best = max(item.score for item in pool) or 1.0
    while pool and len(selected) < top_k:
        best_item, best_value = None, -1e9
        for item in pool:
            vector = index.vector_of(item.note.id)
            redundancy = 0.0
            if vector is not None:
                for chosen in selected:
                    other = index.vector_of(chosen.note.id)
                    if other is not None:
                        redundancy = max(redundancy, vectors.cosine(vector, other))
            value = lambda_ * (item.score / best) - (1.0 - lambda_) * redundancy
            if value > best_value:
                best_item, best_value = item, value
        assert best_item is not None
        selected.append(best_item)
        pool.remove(best_item)
    return selected


def recall(
    db: Database,
    index: VectorIndex,
    embedder: Embedder,
    query: str,
    retrieval: RetrievalConfig,
    decay: DecayConfig,
    at: float | None = None,
    touch: bool = True,
) -> Recall:
    at = clock() if at is None else at
    if not query.strip() or len(index) == 0:
        return Recall(query=query)

    query_vector = embedder.embed_query(query)
    hits = index.search(query_vector, retrieval.candidates, states=(notes_store.STATE_ACTIVE,))
    if not hits:
        return Recall(query=query)

    similarity_by_id = {note_id: score for note_id, score in hits}
    notes = {note.id: note for note in notes_store.get_many(db, list(similarity_by_id))}
    degree = graph_store.degrees(db, notes)

    candidates = [
        _Candidate(
            note=notes[note_id],
            similarity=similarity,
            recall_prob=retrievability(notes[note_id], at, decay),
            degree=degree.get(note_id, 0),
            via="vector",
        )
        for note_id, similarity in hits
        if note_id in notes
    ]

    # 連想展開: 上位の記憶から links を辿る＝「そういえば」で芋づる式に出てくる部分
    if retrieval.graph_hops > 0 and candidates:
        provisional = sorted(_rank(candidates, retrieval), key=lambda item: item.score, reverse=True)
        seeds = [item.note.id for item in provisional[: max(3, retrieval.top_k // 2)]]
        expanded = graph_store.expand(
            db, seeds, hops=retrieval.graph_hops, fanout=retrieval.graph_fanout
        )
        extra_ids = [note_id for note_id in expanded if note_id not in similarity_by_id]
        extra_degree = graph_store.degrees(db, extra_ids)
        for note in notes_store.get_many(db, extra_ids):
            vector = index.vector_of(note.id)
            hop, source = expanded[note.id]
            candidates.append(
                _Candidate(
                    note=note,
                    similarity=vectors.cosine(query_vector, vector) if vector else 0.0,
                    recall_prob=retrievability(note, at, decay),
                    degree=extra_degree.get(note.id, 0),
                    via=f"graph←#{source}",
                    # 連想で来た記憶は少し割り引く（本人が探しに行った訳ではないので）
                    discount=0.9 ** hop,
                )
            )

    chosen = _mmr(_rank(candidates, retrieval), index, retrieval.top_k, retrieval.mmr_lambda)
    if touch:
        notes_store.touch(
            db,
            [item.note.id for item in chosen],
            gain=decay.recall_gain,
            cap=decay.max_half_life_days,
            at=at,
        )
    return Recall(query=query, items=chosen, considered=len(candidates))


def recall_explicit(db: Database, query: str, limit: int = 20) -> list[Note]:
    """「〇〇覚えてる?」— cold や merged になった記憶も掘り起こす明示検索。"""
    return notes_store.text_search(db, query, limit=limit, include_cold=True)
