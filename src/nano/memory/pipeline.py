"""書き込みパイプライン（無意識の中核）。

  生ログ → ① セグメント化 → ② 要約 → ③ 原子化 → ④ 属性付与 → ⑤ 埋め込み
        → ⑥ リンク形成（既存記憶の文脈も書き換える） → ⑦ 固有名詞

A-MEM の要点は⑥c、「新しい記憶が入ると既存の記憶の意味も変わる」こと。
記憶は貯める箱ではなく、入るたびに全体が組み変わるもの。

LLM コール数の設計: 1エピソードあたり
  要約 1 + 原子化/属性/固有名詞 1 + 関係判定 最大 link_judge_budget 回。
VRAM 8〜16GB ではコール数がそのまま体感速度なので、予算を超えた分は
ベクトル類似度だけで similar リンクを張って済ませる。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

from ..config import Config
from ..embed import Embedder
from ..llm import LLM
from ..store import entities as entities_store
from ..store import episodes as episodes_store
from ..store import events as events_store
from ..store import graph as graph_store
from ..store import notes as notes_store
from ..store.db import Database, to_iso
from ..store.events import Event
from ..store.notes import VectorIndex
from . import prompts
from .decay import initial_half_life


@dataclass
class IngestReport:
    episodes: int = 0
    notes: int = 0
    links: int = 0
    revisions: int = 0  # 既存記憶の文脈が書き換わった回数
    note_ids: list[int] = field(default_factory=list)

    def __str__(self) -> str:
        return (
            f"エピソード {self.episodes} / 新しい記憶 {self.notes} / リンク {self.links} / "
            f"既存記憶の書き換え {self.revisions}"
        )


def format_transcript(events: Sequence[Event], companion_name: str) -> str:
    labels = {"user": "ユーザー", "companion": companion_name, "world": "外界"}
    return "\n".join(
        f"[{to_iso(event.ts)}] {labels.get(event.role, event.role)}: {event.content}"
        for event in events
    )


def segment(
    events: Sequence[Event],
    embedder: Embedder,
    config: Config,
    calibration=None,
) -> list[list[Event]]:
    """話題の切れ目で会話を切る。時間の空白と、意味のドリフトの2つを見る。"""
    if not events:
        return []
    pipeline = config.pipeline
    drift_cut = (
        calibration.drift_threshold(pipeline.segment_drift_sigma)
        if calibration is not None and calibration.has_drift
        else pipeline.segment_drift
    )
    vectors_by_index = embedder.embed_documents([event.content for event in events])

    from .. import vectors as vector_math

    segments: list[list[Event]] = []
    current: list[Event] = [events[0]]
    current_vectors = [vectors_by_index[0]]

    for index in range(1, len(events)):
        event = events[index]
        gap_minutes = (event.ts - current[-1].ts) / 60.0
        centroid = vector_math.centroid(current_vectors)
        drift = 1.0 - vector_math.cosine(vectors_by_index[index], centroid)

        cut = gap_minutes > pipeline.segment_gap_minutes
        cut = cut or (len(current) >= pipeline.min_segment_events and drift > drift_cut)
        cut = cut or len(current) >= pipeline.max_segment_events
        if cut:
            segments.append(current)
            current, current_vectors = [event], [vectors_by_index[index]]
        else:
            current.append(event)
            current_vectors.append(vectors_by_index[index])
    segments.append(current)
    return segments


def ingest_pending(
    db: Database,
    llm: LLM,
    embedder: Embedder,
    index: VectorIndex,
    config: Config,
    limit: int = 500,
    calibration=None,
) -> IngestReport:
    """未処理の生ログを記憶に変える。会話の直後、またはアイドル時に呼ばれる。"""
    pending = events_store.pending(db, limit=limit)
    report = IngestReport()
    if not pending:
        return report
    for chunk in segment(pending, embedder, config, calibration):
        _ingest_segment(db, llm, embedder, index, config, chunk, report, calibration)
    return report


def _ingest_segment(
    db: Database,
    llm: LLM,
    embedder: Embedder,
    index: VectorIndex,
    config: Config,
    chunk: Sequence[Event],
    report: IngestReport,
    calibration=None,
) -> None:
    companion = config.persona.name
    # リンクを張るかどうかの足切り。キャリブレーション済みなら、そのモデルの
    # 分布に対する相対位置で決める。絶対コサインはモデルを替えると意味が変わる。
    link_floor = (
        calibration.similarity_threshold(config.pipeline.link_min_sigma)
        if calibration is not None
        else config.pipeline.link_min_similarity
    )
    transcript = format_transcript(chunk, companion)

    # ② 要約
    summary_payload = llm.chat_json(
        prompts.summarize_episode(transcript, companion), task="summarize_episode"
    )
    summary = str(summary_payload.get("summary", "")).strip()
    episode = episodes_store.create(
        db,
        session_id=chunk[0].session_id,
        started_at=chunk[0].ts,
        ended_at=chunk[-1].ts,
        summary=summary,
        salience=float(summary_payload.get("salience", 0.5)),
        mood=str(summary_payload.get("mood", "")),
    )
    events_store.assign_episode(db, [event.id for event in chunk], episode.id)
    report.episodes += 1

    # ③④⑦ 原子化・属性付与・固有名詞抽出（1コールにまとめる）
    extraction = llm.chat_json(
        prompts.extract_notes(transcript, summary, companion, config.pipeline.max_notes_per_episode),
        task="extract_notes",
    )
    raw_notes = list(extraction.get("notes", []))[: config.pipeline.max_notes_per_episode]
    created: list[notes_store.Note] = []

    for raw in raw_notes:
        content = str(raw.get("content", "")).strip()
        if not content:
            continue
        importance = _clamp(raw.get("importance", 0.5))
        note = notes_store.insert(
            db,
            content,
            kind=str(raw.get("kind", notes_store.KIND_FACT)),
            context=str(raw.get("context", "")),
            keywords=[str(k) for k in raw.get("keywords", []) or []],
            tags=[str(t) for t in raw.get("tags", []) or []],
            category=str(raw.get("category", "")),
            importance=importance,
            half_life_days=initial_half_life(importance, config.decay),
            source_episode_id=episode.id,
            created_at=episode.ended_at,
        )
        created.append(note)

    if not created:
        return

    # ⑤ 埋め込み
    payloads = [note.content + ("\n" + note.context if note.context else "") for note in created]
    embeddings = embedder.embed_documents(payloads)
    for note, vector in zip(created, embeddings):
        notes_store.set_vector(db, note.id, vector)

    # ⑦ 固有名詞: 名前が本文に現れるノートに紐づける
    for raw_entity in extraction.get("entities", []) or []:
        name = str(raw_entity.get("name", "")).strip()
        if not name:
            continue
        entity_id = entities_store.upsert(db, name, str(raw_entity.get("kind", "")))
        for note in created:
            if name in note.content or name in note.context:
                entities_store.attach(db, note.id, entity_id)

    # ⑥ リンク形成。新ノートは既存ノート（＋既に入れた新ノート）と関係づける。
    #    近傍探索の前に index へ入れると自分自身が候補に混ざるので、判定後に入れる。
    budget = config.pipeline.link_judge_budget
    order = sorted(range(len(created)), key=lambda i: created[i].importance, reverse=True)
    judged = set(order[:budget])

    for position, (note, vector) in enumerate(zip(created, embeddings)):
        neighbours = index.search(
            vector, config.pipeline.link_top_k, states=(notes_store.STATE_ACTIVE,)
        )
        neighbours = [
            (note_id, score)
            for note_id, score in neighbours
            if score >= link_floor
        ]
        cap = config.pipeline.link_max_per_note
        if neighbours and position in judged:
            _judge_and_link(db, llm, index, embedder, note, neighbours, companion, report, cap)
        else:
            # 予算外はベクトル類似だけで素朴に繋ぐ（無いよりずっとよい）
            for note_id, score in neighbours[:cap]:
                graph_store.add(db, note.id, note_id, "similar", score, created_by="vector", symmetric=True)
                report.links += 1

        # 連想による強化: 関連する話題がまた出てきたら、古い記憶も呼び起こされる。
        # これが無いと、一度話しただけの事実は二度と触れられずに薄れて消える。
        # ただし効き方は関連の強さに比例させる。弱い繋がりでも一律に強化すると、
        # どうでもいい記憶が連想の巻き添えで生き延びてしまう（ベンチで実際に起きた）。
        for note_id, score in neighbours:
            notes_store.touch(
                db,
                [note_id],
                gain=config.decay.recall_gain * 0.5 * score,
                cap=config.decay.max_half_life_days,
                at=episode.ended_at,
            )
        index.add(note.id, vector, notes_store.STATE_ACTIVE)

    # 同じエピソード内の時間順リンク（物語としての繋がり）
    for previous, following in zip(created, created[1:]):
        graph_store.add(db, previous.id, following.id, "temporal_next", 0.4, created_by="pipeline")
        report.links += 1

    report.notes += len(created)
    report.note_ids += [note.id for note in created]


def _judge_and_link(
    db: Database,
    llm: LLM,
    index: VectorIndex,
    embedder: Embedder,
    note: notes_store.Note,
    neighbours: Sequence[tuple[int, float]],
    companion: str,
    report: IngestReport,
    cap: int,
) -> None:
    candidates = []
    for note_id, score in neighbours:
        existing = notes_store.get(db, note_id)
        if existing is not None:
            candidates.append((existing, score))
    if not candidates:
        return

    payload = llm.chat_json(prompts.judge_links(note, candidates, companion), task="judge_links")
    known = {existing.id for existing, _ in candidates}

    accepted: list[tuple[int, str, float, object]] = []
    for link in payload.get("links", []) or []:
        try:
            target = int(link["id"])
        except (KeyError, TypeError, ValueError):
            continue
        if target not in known:
            continue
        accepted.append(
            (target, str(link.get("relation", "similar")), _clamp(link.get("weight", 0.5)), link)
        )
    # 関係が強い順に上限まで。LLM が10件繋げと言っても、記憶は何にでも
    # 結びついてはいけない（結びつきすぎたグラフは何も語らない）。
    accepted.sort(key=lambda item: item[2], reverse=True)

    for target, relation, weight, link in accepted[:cap]:
        graph_store.add(db, note.id, target, relation, weight, created_by="llm", symmetric=True)
        report.links += 1

        # A-MEM の肝: 新しい記憶が既存の記憶の文脈を書き換える
        revised = link.get("revised_context")
        if revised:
            notes_store.update_context(db, target, str(revised))
            existing = notes_store.get(db, target)
            if existing is not None:
                vector = embedder.embed_documents([existing.content + "\n" + existing.context])[0]
                notes_store.set_vector(db, target, vector)
                index.add(target, vector, existing.state)
            report.revisions += 1


def _clamp(value, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return 0.5
