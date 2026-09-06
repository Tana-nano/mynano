"""書き込みパイプラインのテスト。生ログが記憶に変わるまで。"""

from __future__ import annotations

import json

from nano.app import App
from nano.config import Config, PathsConfig
from nano.memory import pipeline
from nano.store import events as events_store
from nano.store import notes as notes_store

from conftest import converse

CONVERSATION = [
    "妹の名前はミオ。ミオは高校生で吹奏楽部にいる",
    "ミオはトランペットを吹いている。来月コンクールがあるらしい",
    "僕は猫を飼っている。名前はクロで、もう12歳になる",
    "クロは最近あまり動かなくなってきた。少し心配している",
]


def test_ingest_turns_events_into_memory(app):
    converse(app, CONVERSATION)
    report = app.ingest()

    assert report.episodes >= 1
    assert report.notes > 0
    assert app.db.scalar("SELECT COUNT(*) FROM events WHERE episode_id IS NULL") == 0
    assert len(app.index) == report.notes


def test_every_note_gets_a_vector(app):
    converse(app, CONVERSATION)
    app.ingest()
    orphans = app.db.scalar(
        "SELECT COUNT(*) FROM notes WHERE id NOT IN (SELECT note_id FROM note_vectors)"
    )
    assert orphans == 0


def test_notes_carry_attributes_and_provenance(app):
    converse(app, CONVERSATION)
    app.ingest()
    for note in notes_store.iter_notes(app.db):
        assert note.content.strip()
        assert note.source_episode_id is not None, "どのエピソード由来か辿れること"
        assert 0.0 <= note.importance <= 1.0
        assert note.half_life_days > 0


def test_notes_are_linked_into_a_graph(app):
    converse(app, CONVERSATION)
    app.ingest()
    assert app.db.scalar("SELECT COUNT(*) FROM links") > 0
    linked = app.db.scalar(
        "SELECT COUNT(DISTINCT src_id) FROM links WHERE src_id IN (SELECT id FROM notes)"
    )
    assert linked > 1


def test_entities_are_extracted_and_attached(app):
    converse(app, CONVERSATION)
    app.ingest()
    assert app.db.scalar("SELECT COUNT(*) FROM entities") > 0
    assert app.db.scalar("SELECT COUNT(*) FROM note_entities") > 0


def test_ingest_is_idempotent(app):
    converse(app, CONVERSATION)
    first = app.ingest()
    second = app.ingest()
    assert second.notes == 0, "処理済みの生ログを二度記憶に変えてはいけない"
    assert first.notes > 0


def test_segmentation_splits_on_time_gap(app):
    """時間が大きく空いたら別の話題として切る。"""
    base = 1_000_000.0
    for index, text in enumerate(CONVERSATION[:2]):
        events_store.append(app.db, "s1", "user", text, ts=base + index)
    for index, text in enumerate(CONVERSATION[2:]):
        events_store.append(app.db, "s1", "user", text, ts=base + 86400 + index)

    segments = pipeline.segment(events_store.pending(app.db), app.embedder, app.config)
    assert len(segments) == 2
    assert len(segments[0]) == 2


def test_link_count_per_note_is_capped(app):
    """密度を決めるのは上限であって、しきい値ではない。

    実際の埋め込みモデルで測ると、類似度のしきい値だけで密度を制御しようとすると
    崖になる（σ 2.0→2.5 で 1記憶あたり 2.5本→0.3本）。乱数ペアで測った分布を
    「上位k件」という偏ったペアに当てているため。上限はモデルに依らず効く。
    """
    def links_with(cap: int) -> int:
        instance = App.build(
            Config(root=app.config.root / f"cap{cap}", paths=PathsConfig(soul_dir="soul")),
            offline=True,
        )
        try:
            instance.config.pipeline.link_max_per_note = cap
            instance.config.pipeline.link_judge_budget = 99  # 全ノートをLLM判定に回す
            converse(instance, CONVERSATION)
            instance.ingest()
            return instance.db.scalar(
                "SELECT COUNT(*) FROM links WHERE relation != 'temporal_next'"
            )
        finally:
            instance.close()

    assert links_with(1) < links_with(5), "上限がリンク数に効いていない"


def test_existing_note_context_can_be_revised(app):
    """A-MEM の肝: 新しい記憶が既存の記憶の文脈を書き換える経路が生きていること。"""
    converse(app, CONVERSATION[:2])
    app.ingest()
    target = notes_store.iter_notes(app.db)[0]

    # 関係判定が revised_context を返す状況を作る
    app.llm.handlers["judge_links"] = lambda messages: {
        "links": [
            {"id": target.id, "relation": "elaborates", "weight": 0.9,
             "revised_context": "書き換えられた文脈"}
        ]
    }
    converse(app, CONVERSATION[2:])
    report = app.ingest()

    assert report.revisions > 0
    assert notes_store.get(app.db, target.id).context == "書き換えられた文脈"


def test_raw_log_is_mirrored_to_plain_text(app):
    """コードが滅びても読める形で残っていること。"""
    converse(app, CONVERSATION[:1])
    files = list(app.config.archive_dir.glob("*.jsonl"))
    assert files, "JSONL ミラーが作られていない"
    records = [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines()]
    assert any(record["content"] == CONVERSATION[0] for record in records)
    assert {"ts", "role", "session_id", "content"} <= set(records[0])
