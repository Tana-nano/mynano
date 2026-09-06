"""ジョブキューのテスト。

デーモンは状態を持たない。全部このキューにある。
だから「二重に実行されない」「落ちても戻ってくる」がここで守られていないと、
無意識は静かに壊れる（同じ記憶を二度書く、考えかけたまま二度と戻らない）。
"""

from __future__ import annotations

from nano.store import jobs
from nano.store.db import Database


def test_enqueue_and_claim(app):
    job_id = jobs.enqueue(app.db, "write")
    claimed = jobs.claim(app.db)
    assert claimed is not None
    assert claimed.id == job_id
    assert claimed.kind == "write"
    assert claimed.attempts == 1


def test_claim_returns_nothing_when_empty(app):
    assert jobs.claim(app.db) is None


def test_duplicate_pending_jobs_are_not_stacked(app):
    """デーモンが数日止まっていた後に decay が100件溜まる、を防ぐ。"""
    assert jobs.enqueue(app.db, "decay") is not None
    assert jobs.enqueue(app.db, "decay") is None
    assert app.db.scalar("SELECT COUNT(*) FROM jobs") == 1


def test_priority_and_age_decide_order(app):
    jobs.enqueue(app.db, "curate", priority=10)
    jobs.enqueue(app.db, "write", priority=5)
    assert jobs.claim(app.db).kind == "write"
    assert jobs.claim(app.db).kind == "curate"


def test_future_jobs_are_not_claimed_early(app):
    jobs.enqueue(app.db, "decay", run_after=10_000.0)
    assert jobs.claim(app.db, at=9_999.0) is None
    assert jobs.claim(app.db, at=10_001.0) is not None


def test_two_processes_never_claim_the_same_job(app, config):
    """デーモンを二重起動しても、同じ記憶を二度書かないこと。"""
    jobs.enqueue(app.db, "write")
    other = Database(config.db_path)  # 別プロセス相当の接続
    try:
        first = jobs.claim(app.db)
        second = jobs.claim(other)
        assert first is not None
        assert second is None
    finally:
        other.close()


def test_release_returns_job_without_burning_a_retry(app):
    """対話に割り込まれたのは失敗ではない。リトライ回数を消費させない。"""
    job_id = jobs.enqueue(app.db, "associate")
    jobs.claim(app.db)
    jobs.release(app.db, job_id)

    assert app.db.scalar("SELECT status FROM jobs WHERE id=?", (job_id,)) == jobs.STATUS_PENDING
    assert app.db.scalar("SELECT attempts FROM jobs WHERE id=?", (job_id,)) == 0
    assert jobs.claim(app.db) is not None


def test_failure_retries_then_gives_up(app):
    job_id = jobs.enqueue(app.db, "curate")
    for _ in range(2):
        jobs.claim(app.db, at=1e12)
        jobs.fail(app.db, job_id, "boom", retry_in=0.0, max_attempts=3)
        assert app.db.scalar("SELECT status FROM jobs WHERE id=?", (job_id,)) == jobs.STATUS_PENDING

    jobs.claim(app.db, at=1e12)
    jobs.fail(app.db, job_id, "boom", retry_in=0.0, max_attempts=3)
    assert app.db.scalar("SELECT status FROM jobs WHERE id=?", (job_id,)) == jobs.STATUS_FAILED
    assert jobs.recent_failures(app.db)[0]["kind"] == "curate"


def test_stale_running_jobs_are_reclaimed(app):
    """電源が落ちても、考えかけたことは戻ってくる。"""
    jobs.enqueue(app.db, "reflect")
    job = jobs.claim(app.db)
    app.db.execute("UPDATE jobs SET updated_at=0 WHERE id=?", (job.id,))

    assert jobs.reap_stale(app.db, timeout_s=600.0) == 1
    assert jobs.claim(app.db) is not None


def test_last_run_is_tracked_per_kind(app):
    assert jobs.last_run(app.db, "decay") == 0.0
    jobs.mark_run(app.db, "decay", at=1234.0)
    assert jobs.last_run(app.db, "decay") == 1234.0
    assert jobs.last_run(app.db, "curate") == 0.0
