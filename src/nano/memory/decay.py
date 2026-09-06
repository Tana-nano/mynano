"""忘却曲線。

このプロジェクトで最も重要な設計判断がここにある:
    **忘却は削除ではない。** active → cold →（統合されて）merged と状態が遷移するだけで、
    ノートも生ログも消えない。人間らしく忘れつつ、取り返しがつく。
    不可逆な削除はユーザーが明示的に命じたときだけ行う。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

from .. import vectors
from ..config import DecayConfig
from ..embed import Embedder
from ..llm import LLM
from ..store import graph as graph_store
from ..store import notes as notes_store
from ..store.db import Database, now as clock
from ..store.notes import Note, VectorIndex
from . import prompts

SECONDS_PER_DAY = 86400.0


def initial_half_life(importance: float, config: DecayConfig) -> float:
    """重要な記憶は最初から桁違いに半減期が長い。

        half_life = base * (1 + span * importance^2)

    線形（base + bonus*importance）にしていたときは、重要度0.5の
    「職場は代々木」が30日で cold になった。人間はそうは忘れない。
    重要度を二乗で効かせて、雑事は数日・生活の事実は数百日と桁を分ける。

        importance 0.1 → 約  6日
        importance 0.3 → 約 38日
        importance 0.5 → 約102日
        importance 0.9 → 約326日
    """
    importance = max(0.0, min(1.0, importance))
    half_life = config.base_half_life_days * (1.0 + config.importance_span * importance**2)
    return min(half_life, config.max_half_life_days)


def retrievability(note: Note, at: float, config: DecayConfig) -> float:
    """いまこの記憶がどれくらい思い出しやすいか（0〜1）。

    retrievability(t) = exp(-(t - last_accessed) / half_life)
    """
    if note.pinned:
        return 1.0
    half_life = max(note.half_life_days, 1e-6) * SECONDS_PER_DAY
    elapsed = max(0.0, at - note.last_accessed_at)
    return math.exp(-elapsed / half_life)


@dataclass
class DecayReport:
    cooled: list[int] = field(default_factory=list)
    consolidated: list[int] = field(default_factory=list)
    merged: list[int] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"cold化 {len(self.cooled)}件 / 統合ノート {len(self.consolidated)}件 "
            f"(元ノート {len(self.merged)}件を merged 化)"
        )


def cool_faded(
    db: Database,
    config: DecayConfig,
    index: VectorIndex | None = None,
    at: float | None = None,
) -> list[int]:
    """しきい値を割った記憶を能動インデックスから外す。中身は残る。"""
    at = clock() if at is None else at
    cooled: list[int] = []
    for note in notes_store.iter_notes(db, states=(notes_store.STATE_ACTIVE,)):
        if note.pinned:
            continue
        if retrievability(note, at, config) < config.cold_threshold:
            notes_store.set_state(db, note.id, notes_store.STATE_COLD)
            if index is not None:
                index.set_state(note.id, notes_store.STATE_COLD)
            cooled.append(note.id)
    return cooled


def _cluster(cold: Sequence[Note], vecs: dict[int, list[float]], threshold: float, minimum: int) -> list[list[Note]]:
    """素朴な貪欲クラスタリング。個人規模ではこれで十分。"""
    unassigned = [note for note in cold if note.id in vecs]
    clusters: list[list[Note]] = []
    used: set[int] = set()
    for seed in unassigned:
        if seed.id in used:
            continue
        members = [seed]
        for other in unassigned:
            if other.id in used or other.id == seed.id:
                continue
            if vectors.cosine(vecs[seed.id], vecs[other.id]) >= threshold:
                members.append(other)
        if len(members) >= minimum:
            clusters.append(members)
            used.update(member.id for member in members)
    return clusters


def consolidate(
    db: Database,
    llm: LLM,
    embedder: Embedder,
    config: DecayConfig,
    index: VectorIndex,
    companion_name: str = "nano",
    at: float | None = None,
    calibration=None,
) -> DecayReport:
    """cold な記憶の群れを1枚の上位ノートにまとめる（圧縮・統合）。

    元ノートは merged 状態で残り、統合ノートから merged_from リンクで辿れる。
    """
    at = clock() if at is None else at
    report = DecayReport()
    cold = notes_store.iter_notes(db, states=(notes_store.STATE_COLD,))
    if len(cold) < config.consolidate_min_cluster:
        return report

    vecs = {note.id: index.vector_of(note.id) for note in cold}
    vecs = {note_id: vector for note_id, vector in vecs.items() if vector}
    similarity_floor = (
        calibration.similarity_threshold(config.consolidate_sigma)
        if calibration is not None
        else config.consolidate_similarity
    )
    clusters = _cluster(cold, vecs, similarity_floor, config.consolidate_min_cluster)

    for members in clusters:
        payload = llm.chat_json(
            prompts.consolidate(members, companion_name), task="consolidate"
        )
        content = str(payload.get("content", "")).strip()
        if not content:
            continue
        importance = max(float(payload.get("importance", 0.5)), max(m.importance for m in members))
        summary_note = notes_store.insert(
            db,
            content,
            kind=notes_store.KIND_REFLECTION,
            context=str(payload.get("context", "")),
            keywords=payload.get("keywords", []) or [],
            tags=list(payload.get("tags", []) or []) + ["consolidated"],
            category=str(payload.get("category", "")),
            importance=importance,
            half_life_days=initial_half_life(importance, config),
            created_at=at,
        )
        vector = embedder.embed_documents([content + "\n" + summary_note.context])[0]
        notes_store.set_vector(db, summary_note.id, vector)
        index.add(summary_note.id, vector, notes_store.STATE_ACTIVE)

        for member in members:
            notes_store.set_state(db, member.id, notes_store.STATE_MERGED, merged_into=summary_note.id)
            index.set_state(member.id, notes_store.STATE_MERGED)
            graph_store.add(db, summary_note.id, member.id, "merged_from", 1.0, created_by="decay")
            report.merged.append(member.id)
        report.consolidated.append(summary_note.id)
    return report


def run(
    db: Database,
    llm: LLM,
    embedder: Embedder,
    config: DecayConfig,
    index: VectorIndex,
    companion_name: str = "nano",
    at: float | None = None,
    calibration=None,
) -> DecayReport:
    """1晩ぶんの忘却処理。M2 の無意識デーモンからも、手動コマンドからも呼ばれる。"""
    at = clock() if at is None else at
    report = DecayReport(cooled=cool_faded(db, config, index, at))
    consolidation = consolidate(db, llm, embedder, config, index, companion_name, at, calibration)
    report.consolidated = consolidation.consolidated
    report.merged = consolidation.merged
    return report
