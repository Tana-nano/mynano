"""想起のふるまいを固定するテスト。"""

from __future__ import annotations

import pytest

from nano.memory.retrieve import _min_max, recall
from nano.store import graph as graph_store
from nano.store import notes as notes_store
from nano.store.db import now

from conftest import DAY


def add_note(app, content, *, importance=0.5, half_life_days=30.0, created_at=None):
    created_at = now() if created_at is None else created_at
    note = notes_store.insert(
        app.db, content, importance=importance, half_life_days=half_life_days, created_at=created_at
    )
    vector = app.embedder.embed_documents([content])[0]
    notes_store.set_vector(app.db, note.id, vector)
    app.index.add(note.id, vector)
    return note


def test_min_max_normalizes_to_unit_range():
    assert _min_max([0.70, 0.80, 0.90]) == [0.0, pytest.approx(0.5), 1.0]


def test_min_max_is_neutral_when_no_spread():
    """差が無い成分は順位に寄与してはいけない（全部同じ値になる）。"""
    assert _min_max([0.8, 0.8, 0.8]) == [0.5, 0.5, 0.5]


def test_similarity_drives_ranking(app):
    target = add_note(app, "妹の名前はミオ")
    add_note(app, "コーヒーは苦手で紅茶ばかり飲む")
    add_note(app, "来週の金曜に歯医者の予約を入れた")

    result = recall(
        app.db, app.index, app.embedder, "妹の名前はなんだっけ",
        app.config.retrieval, app.config.decay, touch=False,
    )
    assert result.items[0].note.id == target.id


def test_graph_expansion_surfaces_associated_memories(app):
    """直接ヒットしない記憶が、リンク経由で連想的に出てくること。"""
    seed = add_note(app, "妹の名前はミオ")
    associated = add_note(app, "紫陽花は梅雨に咲く花である")  # 語としては全く重ならない
    graph_store.add(app.db, seed.id, associated.id, "elaborates", 0.9, symmetric=True)

    # ベクトル検索では seed しか拾わない状況を作り、リンク経由の到達だけを見る
    app.config.retrieval.candidates = 1
    result = recall(
        app.db, app.index, app.embedder, "妹の名前はなんだっけ",
        app.config.retrieval, app.config.decay, touch=False,
    )
    found = {item.note.id: item for item in result.items}
    assert associated.id in found
    assert found[associated.id].via.startswith("graph←")


def test_recall_strengthens_what_it_touches(app):
    created = now()
    note = add_note(app, "妹の名前はミオ", half_life_days=3.0, created_at=created)
    recall(
        app.db, app.index, app.embedder, "妹の名前はなんだっけ",
        app.config.retrieval, app.config.decay, at=created + DAY, touch=True,
    )
    refreshed = notes_store.get(app.db, note.id)
    assert refreshed.access_count == 1
    assert refreshed.half_life_days > 3.0
    assert refreshed.last_accessed_at == created + DAY


def test_recall_respects_top_k(app):
    for index in range(20):
        add_note(app, f"記憶その{index}についての話")
    result = recall(
        app.db, app.index, app.embedder, "記憶の話",
        app.config.retrieval, app.config.decay, touch=False,
    )
    assert len(result.items) == app.config.retrieval.top_k


def test_mmr_avoids_returning_identical_memories(app):
    """同じ内容が枠を埋め尽くさないこと。"""
    for index in range(6):
        add_note(app, "散歩に行った")  # 完全に同一のベクトル
    add_note(app, "散歩の途中でクロに似た猫を見た")

    app.config.retrieval.top_k = 3
    app.config.retrieval.mmr_lambda = 0.5
    result = recall(
        app.db, app.index, app.embedder, "散歩の話",
        app.config.retrieval, app.config.decay, touch=False,
    )
    contents = [item.note.content for item in result.items]
    assert len(set(contents)) > 1, "多様性選択が効いていない"


def test_trace_is_human_readable(app):
    add_note(app, "妹の名前はミオ")
    result = recall(
        app.db, app.index, app.embedder, "妹",
        app.config.retrieval, app.config.decay, touch=False,
    )
    trace = result.trace()
    assert "クエリ" in trace and "score=" in trace and "妹の名前はミオ" in trace


def test_empty_memory_returns_nothing(app):
    result = recall(
        app.db, app.index, app.embedder, "何か",
        app.config.retrieval, app.config.decay, touch=False,
    )
    assert result.items == []
