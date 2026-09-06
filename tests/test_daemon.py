"""デーモンのテスト。

見ているのは主に2つ:
  - 相手が話している最中に GPU を背景処理で埋めないこと（アイドル判定）
  - 割り込まれた仕事が失われず、あとで戻ってくること
"""

from __future__ import annotations

import pytest

from nano.gate import Preempted
from nano.store import events as events_store
from nano.store import jobs as jobs_store
from nano.unconscious import jobs as job_handlers
from nano.unconscious.daemon import Daemon

from conftest import converse

# 実際の Unix 時刻に近い値を使う。定期ジョブの「前回実行 = 0（=1970年）」との
# 差分で判定しているので、小さな合成時刻だと全ジョブが未到来になってしまう。
BASE = 1_800_000_000.0


@pytest.fixture
def daemon(app):
    return Daemon(app, log=lambda message: None)


def test_idle_only_after_silence(daemon, app):
    events_store.append(app.db, "s1", "user", "いま話している", ts=BASE)
    assert daemon.is_idle(at=BASE + 10) is False
    assert daemon.is_idle(at=BASE + 200) is True


def test_thinking_jobs_wait_for_silence(daemon, app):
    """相手が話している間は、連想も忘却も始めない。"""
    events_store.append(app.db, "s1", "user", "話しかけている", ts=BASE)
    queued = daemon.schedule(at=BASE + 5)
    assert "associate" not in queued
    assert "decay" not in queued


def test_thinking_jobs_start_once_silent(daemon, app):
    events_store.append(app.db, "s1", "user", "話しかけた", ts=BASE)
    queued = daemon.schedule(at=BASE + 500)
    assert {"associate", "reflect", "decay", "curate"} <= set(queued)


def test_conversation_is_written_up_shortly_after_it_ends(daemon, app):
    """未処理の生ログがあり、話が途切れていれば write を積む。"""
    events_store.append(app.db, "s1", "user", "覚えておいてほしい話", ts=BASE)
    assert "write" not in daemon.schedule(at=BASE + 5)
    assert "write" in daemon.schedule(at=BASE + 60)


def test_periodic_jobs_respect_their_interval(daemon, app):
    events_store.append(app.db, "s1", "user", "話しかけた", ts=BASE)
    at = BASE + 500
    assert "associate" in daemon.schedule(at=at)
    # 直後にもう一度回しても積み直さない
    assert "associate" not in daemon.schedule(at=at + 60)

    # 積んだものを消化してから、間隔を過ぎればまた積む
    while (job := jobs_store.claim(app.db, at=at)) is not None:
        jobs_store.complete(app.db, job.id)
    later = at + app.config.unconscious.associate_interval_minutes * 60 + 1
    assert "associate" in daemon.schedule(at=later)


def test_tick_runs_one_job_and_completes_it(daemon, app):
    converse(app, ["妹の名前はミオ", "クロは12歳の猫"])
    jobs_store.enqueue(app.db, "write")
    message = daemon.tick()

    assert message is not None and message.startswith("write:")
    assert jobs_store.summary(app.db)["write"] == {"done": 1}
    assert app.db.scalar("SELECT COUNT(*) FROM notes") > 0


def test_preempted_job_returns_to_the_queue(daemon, app, monkeypatch):
    """考えかけたことは、あとで考え直される。"""
    def interrupted(scoped_app, job):
        raise Preempted("chat wants the model")

    monkeypatch.setitem(job_handlers.HANDLERS, "associate", interrupted)
    job_id = jobs_store.enqueue(app.db, "associate")
    message = daemon.tick()

    assert "中断" in message
    assert app.db.scalar("SELECT status FROM jobs WHERE id=?", (job_id,)) == jobs_store.STATUS_PENDING
    assert app.db.scalar("SELECT attempts FROM jobs WHERE id=?", (job_id,)) == 0


def test_a_failing_job_does_not_kill_the_daemon(daemon, app, monkeypatch):
    def explode(scoped_app, job):
        raise RuntimeError("記憶ストアが燃えた")

    monkeypatch.setitem(job_handlers.HANDLERS, "curate", explode)
    jobs_store.enqueue(app.db, "curate")
    message = daemon.tick()

    assert "失敗" in message
    # 失敗しても消えない。あとで再試行される。
    assert app.db.scalar("SELECT status FROM jobs WHERE kind='curate'") == jobs_store.STATUS_PENDING
    daemon.tick()  # 例外を持ち越さず、次の tick が普通に回ること


def test_unknown_job_kind_is_not_retried_forever(daemon, app):
    jobs_store.enqueue(app.db, "存在しない仕事")
    daemon.tick()
    assert app.db.scalar("SELECT status FROM jobs WHERE kind='存在しない仕事'") == jobs_store.STATUS_FAILED


def test_force_ignores_silence_and_intervals(app):
    """夜間処理を手で走らせる用の抜け道が効くこと。"""
    forced = Daemon(app, force=True, log=lambda message: None)
    events_store.append(app.db, "s1", "user", "たったいま話した")
    queued = forced.schedule()
    assert {"associate", "reflect", "decay", "curate"} <= set(queued)


def test_background_llm_is_cancellable(daemon, app):
    """ジョブ実行中の LLM が、割り込みの届く形に包まれていること。"""
    from nano.gate import CancelToken
    from nano.llm import CancellableLLM

    scoped = daemon._scoped_app(CancelToken())
    assert isinstance(scoped.llm, CancellableLLM)
    assert scoped.db is app.db
