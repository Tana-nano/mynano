"""デーモンのログ。

常駐プロセスなので、ローテーションを自分で持てているかどうかが本題。
起動用バッチ側のリダイレクトに任せると、日付が「起動した日」で固定される。
"""

from __future__ import annotations

import logging

import pytest

from nano import logs
from nano.unconscious.daemon import Daemon


@pytest.fixture(autouse=True)
def clean_logger():
    logs.reset()
    yield
    logs.reset()


def test_writes_into_the_soul_directory(config):
    logger = logs.setup(config, to_stream=False)
    logger.info("無意識を起動しました")

    target = config.log_dir / "unconscious.log"
    assert target.exists()
    assert "無意識を起動しました" in target.read_text(encoding="utf-8")
    # 魂の中に閉じていること（引っ越しはディレクトリごとコピーで済む）
    assert target.is_relative_to(config.soul_dir)


def test_rotates_daily_and_keeps_the_configured_days(config):
    config.unconscious.log_retain_days = 7
    logs.setup(config, to_stream=False)
    handler = next(h for h in logs.own_handlers() if hasattr(h, "backupCount"))
    assert handler.backupCount == 7
    assert handler.when == "MIDNIGHT"
    # Windows の既定は cp932。明示しないと日本語1行で落ちる
    assert handler.encoding == "utf-8"


def test_setup_is_idempotent(config):
    first = logs.setup(config, to_stream=False)
    second = logs.setup(config, to_stream=False)
    assert first is second
    assert len(logs.own_handlers()) == 1  # 呼ぶたびにハンドラが増えない


def test_verbose_lowers_the_level(config):
    assert logs.setup(config, to_stream=False).level == logging.INFO
    logs.reset()
    assert logs.setup(config, verbose=True, to_stream=False).level == logging.DEBUG


def test_failures_are_louder_than_ordinary_ticks(app, monkeypatch):
    """後から「何かあったか」を探せること。失敗だけ WARNING で出る。"""
    from nano.store import jobs as jobs_store
    from nano.unconscious import jobs as job_handlers

    def explode(scoped_app, job):
        raise RuntimeError("記憶ストアが燃えた")

    monkeypatch.setitem(job_handlers.HANDLERS, "curate", explode)
    jobs_store.enqueue(app.db, "curate")

    daemon = Daemon(app, force=True)
    seen: list[tuple[str, str]] = []

    def record(level):
        def emit(message: str) -> None:
            seen.append((level, message))
            if len(seen) >= 2:  # 起動メッセージの次まで見たら止める
                daemon.stop()

        return emit

    daemon.log = record("info")
    daemon.warn = record("warn")
    daemon.run()

    levels = dict((message, level) for level, message in seen)
    failure = next(m for m in levels if "失敗" in m)
    assert levels[failure] == "warn"
    assert "記憶ストアが燃えた" in failure
    assert daemon._failed is True


def test_a_normal_tick_is_not_a_failure(app):
    from nano.store import jobs as jobs_store

    daemon = Daemon(app, force=True, log=lambda message: None)
    app.say("何か話した", "s1")
    jobs_store.enqueue(app.db, "write")
    daemon.tick()
    assert daemon._failed is False
