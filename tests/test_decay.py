"""忘却の性質を固定するテスト。

ここが壊れると「消えて困る記憶が消える」ので、最も厳しく守る。
"""

from __future__ import annotations

import pytest

from nano.config import DecayConfig
from nano.memory import decay
from nano.store import notes as notes_store
from nano.store.notes import Note

from conftest import DAY, converse


def make_note(**kwargs) -> Note:
    base = dict(
        id=1, created_at=0.0, kind="fact", content="x", importance=0.5,
        half_life_days=3.0, last_accessed_at=0.0,
    )
    base.update(kwargs)
    return Note(**base)


def test_retrievability_decreases_over_time():
    config = DecayConfig()
    note = make_note()
    values = [decay.retrievability(note, days * DAY, config) for days in (0, 1, 3, 10, 30)]
    assert values[0] == pytest.approx(1.0)
    assert values == sorted(values, reverse=True)
    assert values[2] == pytest.approx(0.3679, abs=1e-3)  # 半減期ちょうどで 1/e


def test_important_memories_start_with_longer_half_life():
    config = DecayConfig()
    assert decay.initial_half_life(0.9, config) > decay.initial_half_life(0.1, config)


def test_pinned_memories_never_fade():
    config = DecayConfig()
    note = make_note(pinned=True, last_accessed_at=0.0)
    assert decay.retrievability(note, 3650 * DAY, config) == 1.0


def test_recall_extends_half_life(app):
    """使う記憶ほど忘れにくくなる（間隔反復）。"""
    note = notes_store.insert(app.db, "テスト記憶", importance=0.5, half_life_days=3.0)
    before = notes_store.get(app.db, note.id).half_life_days
    notes_store.touch(app.db, [note.id], gain=0.8, cap=3650.0)
    after = notes_store.get(app.db, note.id)
    assert after.half_life_days > before
    assert after.access_count == 1


def test_faded_memories_go_cold_not_deleted(app):
    config = app.config.decay
    note = notes_store.insert(app.db, "薄れる記憶", importance=0.1, half_life_days=1.0)
    cooled = decay.cool_faded(app.db, config, app.index, at=note.created_at + 30 * DAY)
    assert note.id in cooled

    stored = notes_store.get(app.db, note.id)
    assert stored is not None, "cold 化で行が消えてはいけない"
    assert stored.state == notes_store.STATE_COLD
    assert stored.content == "薄れる記憶"


def test_cold_memories_are_still_findable_explicitly(app):
    note = notes_store.insert(app.db, "ミオはトランペットを吹く", importance=0.1, half_life_days=1.0)
    decay.cool_faded(app.db, app.config.decay, app.index, at=note.created_at + 30 * DAY)
    found = notes_store.text_search(app.db, "トランペット")
    assert [n.id for n in found] == [note.id], "cold でも明示検索では掘り起こせること"


def test_cold_memories_are_excluded_from_normal_recall(app):
    from nano.memory.retrieve import recall

    note = notes_store.insert(app.db, "薄れる記憶", importance=0.1, half_life_days=1.0)
    vector = app.embedder.embed_documents([note.content])[0]
    notes_store.set_vector(app.db, note.id, vector)
    app.index.add(note.id, vector)

    at = note.created_at + 30 * DAY
    decay.cool_faded(app.db, app.config.decay, app.index, at=at)
    result = recall(
        app.db, app.index, app.embedder, "薄れる記憶",
        app.config.retrieval, app.config.decay, at=at, touch=False,
    )
    assert result.items == []


def test_consolidation_keeps_originals_traceable(app):
    """統合しても元ノートは merged として残り、親から辿れること。"""
    at = 0.0
    ids = []
    for index in range(4):
        note = notes_store.insert(
            app.db, f"散歩に行った記録その{index}", importance=0.1, half_life_days=1.0, created_at=at
        )
        vector = app.embedder.embed_documents(["散歩に行った"])[0]  # 同じベクトル＝必ず1クラスタ
        notes_store.set_vector(app.db, note.id, vector)
        app.index.add(note.id, vector)
        ids.append(note.id)

    report = app.run_decay(at=at + 60 * DAY)
    assert report.consolidated, "クラスタは統合されるはず"

    parent_id = report.consolidated[0]
    for note_id in ids:
        member = notes_store.get(app.db, note_id)
        assert member is not None, "統合で元ノートが消えてはいけない"
        assert member.state == notes_store.STATE_MERGED
        assert member.merged_into == parent_id

    children = app.db.query(
        "SELECT dst_id FROM links WHERE src_id=? AND relation='merged_from'", (parent_id,)
    )
    assert {row["dst_id"] for row in children} == set(ids)


def test_raw_events_survive_everything(app):
    """生ログは何をしても減らない。魂の一次資料だから。"""
    converse(app, ["妹の名前はミオ", "クロは12歳の猫", "今日は雨だった"])
    before = app.db.scalar("SELECT COUNT(*) FROM events")
    app.ingest()
    app.run_decay(at=app.db.scalar("SELECT MAX(ts) FROM events") + 3650 * DAY)
    after = app.db.scalar("SELECT COUNT(*) FROM events")
    assert after == before > 0
