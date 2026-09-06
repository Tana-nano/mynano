"""記憶ストアの性質。可搬性と監査可能性を守る。"""

from __future__ import annotations

from nano.app import App
from nano.store import archive, notes as notes_store, state as state_store

from conftest import converse

CONVERSATION = ["妹の名前はミオ", "クロは12歳の猫で最近元気がない", "来週の金曜に歯医者の予約"]


def test_short_japanese_queries_are_searchable(app):
    """trigram FTS は3文字未満を索引できない。日本語では2文字語が普通なので落とさない。"""
    notes_store.insert(app.db, "ユーザーの妹の名前はミオ", keywords=["妹", "ミオ"], tags=["家族"])
    assert [n.content for n in notes_store.text_search(app.db, "ミオ")]
    assert [n.content for n in notes_store.text_search(app.db, "家族")]
    assert notes_store.text_search(app.db, "まったく出てこない語") == []


def test_soul_survives_a_restart(app, config):
    """魂は1ファイル。プロセスを落としても、そこから完全に再開できること。"""
    converse(app, CONVERSATION)
    app.ingest()
    before = app.stats()
    app.close()

    revived = App.build(config, offline=True)
    try:
        assert revived.stats()["notes_active"] == before["notes_active"]
        assert len(revived.index) == before["vectors"]
        found = notes_store.text_search(revived.db, "ミオ")
        assert found
    finally:
        revived.close()


def test_export_is_readable_without_this_code(app):
    converse(app, CONVERSATION)
    app.ingest()
    count = archive.export_notes(app.db, app.config.export_dir)

    assert count > 0
    files = sorted((app.config.export_dir / "notes").glob("*.md"))
    assert files
    text = files[0].read_text(encoding="utf-8")
    assert text.startswith("---"), "YAML フロントマター付きの Markdown であること"
    assert "id:" in text and "importance:" in text
    assert (app.config.export_dir / "index.md").exists()


def test_working_state_changes_are_audited(app):
    """人格の周辺を無意識が書き換えた履歴が必ず残ること。"""
    state_store.set_value(app.db, state_store.KEY_CURRENT_FOCUS, "妹の話", updated_by="unconscious")
    state_store.set_value(app.db, state_store.KEY_CURRENT_FOCUS, "猫の話", updated_by="unconscious")

    log = state_store.history(app.db, state_store.KEY_CURRENT_FOCUS)
    assert len(log) == 2
    assert log[0]["new_value"] == "猫の話"
    assert log[0]["old_value"] == "妹の話"
    assert log[0]["updated_by"] == "unconscious"


def test_backup_snapshot_is_a_usable_database(app, tmp_path):
    converse(app, CONVERSATION)
    app.ingest()
    target = app.db.backup(app.config.backup_dir)

    import sqlite3

    conn = sqlite3.connect(target)
    try:
        assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] > 0
        assert conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0] > 0
    finally:
        conn.close()
