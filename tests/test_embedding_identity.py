"""埋め込みモデルの同一性のテスト。

「モデルは交換可能な臓器で、記憶ストアが本体」を成立させているのは、
実のところこの照合と reembed の組み合わせである。
記録が無ければ、交換ではなく破壊になる。
"""

from __future__ import annotations

import pytest

from nano.app import App
from nano.embed import HashEmbedder, ServerEmbedder
from nano.memory import reembed
from nano.memory.retrieve import recall
from nano.store import identity as identity_store
from nano.store import notes as notes_store

from conftest import converse

CONVERSATION = ["妹の名前はミオ", "クロは12歳の猫で最近元気がない", "来週の金曜に歯医者の予約"]


def test_embedders_name_their_vector_space():
    assert HashEmbedder(dim=1024).identity == "hash@1024"
    assert ServerEmbedder(base_url="http://x", model="multilingual-e5-large").identity == (
        "multilingual-e5-large@1024"
    )


def test_offline_and_real_embedders_never_share_a_name():
    """オフラインで作った記憶と実機の記憶が混ざらないこと。"""
    assert HashEmbedder(dim=1024).identity != ServerEmbedder(
        base_url="http://x", model="multilingual-e5-large", dim=1024
    ).identity


def test_first_run_records_the_identity(app):
    assert identity_store.recorded(app.db) == "hash@1024"


def test_reopening_with_the_same_model_is_fine(app, config):
    converse(app, CONVERSATION)
    app.ingest()
    app.close()

    revived = App.build(config, offline=True)
    revived.close()  # 例外が出なければよい


def test_swapping_the_model_stops_startup(app, config):
    """静かに壊れるくらいなら、起動を止めて人間に判断させる。"""
    converse(app, CONVERSATION)
    app.ingest()
    app.close()

    config.embed.dim = 768  # 別のモデルに差し替えたことにする
    with pytest.raises(identity_store.EmbeddingMismatch) as raised:
        App.build(config, offline=True)

    message = str(raised.value)
    assert "hash@1024" in message and "hash@768" in message
    assert "nano reembed" in message, "次にやることが書かれていること"


def test_a_soul_without_vectors_can_change_model_freely(app, config):
    """まだベクトルが無いなら混ざりようがないので、止める必要はない。"""
    app.close()
    config.embed.dim = 768
    revived = App.build(config, offline=True)
    try:
        assert identity_store.recorded(revived.db) == "hash@768"
    finally:
        revived.close()


def test_reembed_backs_up_before_touching_anything(app):
    converse(app, CONVERSATION)
    app.ingest()
    assert not list(app.config.backup_dir.glob("*.db"))

    report = reembed.run(app)
    assert list(app.config.backup_dir.glob("*.db")), "バックアップを取らずに埋め直している"
    assert report.notes > 0


def test_reembed_restores_recall_after_a_model_swap(app, config):
    converse(app, CONVERSATION)
    app.ingest()
    note_count = app.db.scalar("SELECT COUNT(*) FROM notes")
    app.close()

    config.embed.dim = 768
    swapped = App.build(config, offline=True, allow_new_embedder=True)
    try:
        report = reembed.run(swapped)

        assert report.notes == note_count
        assert identity_store.recorded(swapped.db) == "hash@768"
        # 全ノートに新しい座標が付いていること
        orphans = swapped.db.scalar(
            "SELECT COUNT(*) FROM notes WHERE id NOT IN (SELECT note_id FROM note_vectors)"
        )
        assert orphans == 0
        assert len(swapped.index) == note_count

        found = recall(
            swapped.db, swapped.index, swapped.embedder, "妹の名前は？",
            swapped.config.retrieval, swapped.config.decay, touch=False,
        )
        assert found.items, "埋め直したのに想起できない"
    finally:
        swapped.close()

    # 埋め直したあとは、普通の起動が通るようになる
    revived = App.build(config, offline=True)
    revived.close()


def test_reembed_keeps_the_memories_themselves_untouched(app, config):
    """変わるのは検索用の座標だけ。本文も重要度も半減期もリンクも動かさない。"""
    converse(app, CONVERSATION)
    app.ingest()
    before = {
        note.id: (note.content, note.importance, note.half_life_days, note.state)
        for note in notes_store.iter_notes(app.db)
    }
    links_before = app.db.scalar("SELECT COUNT(*) FROM links")

    config.embed.dim = 768
    app.close()
    swapped = App.build(config, offline=True, allow_new_embedder=True)
    try:
        reembed.run(swapped)
        after = {
            note.id: (note.content, note.importance, note.half_life_days, note.state)
            for note in notes_store.iter_notes(swapped.db)
        }
        assert after == before
        assert swapped.db.scalar("SELECT COUNT(*) FROM links") == links_before
    finally:
        swapped.close()
