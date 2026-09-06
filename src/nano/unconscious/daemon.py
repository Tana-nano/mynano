"""無意識デーモン。

  tick():
    1. 取り残されたジョブを回収する
    2. 期限の来た定期ジョブを積む
    3. ジョブを1件だけ実行する（1 tick 1 ジョブ。対話に道を空けておくため）

状態は全て soul.db にある。このプロセス自身は何も覚えていないので、
いつ落ちても、電源が切れても、続きから再開できる。

アイドル判定を挟んでいるのは、ユーザーが話している最中に
GPU を背景処理で埋めないため。連想も忘却も、相手が黙ってからやる。
"""

from __future__ import annotations

import os
import signal
import time
from dataclasses import dataclass, field
from typing import Callable

from .. import logs
from ..gate import PRIORITY_BACKGROUND, Preempted
from ..llm import CancellableLLM
from ..store import jobs as jobs_store
from ..store.db import now
from .jobs import HANDLERS

MINUTE = 60.0
HOUR = 3600.0


@dataclass
class Daemon:
    app: object
    verbose: bool = False
    # 待ち時間を全て無視して動かす。夜間処理を手で走らせたいときと、テスト用。
    force: bool = False
    # 既定は None。run() で soul/log/ に日次ローテーションする logger を用意する。
    # 差し替えられるようにしてあるのは、テストが黙らせたいときのため。
    log: Callable[[str], None] | None = None
    warn: Callable[[str], None] | None = None
    _stopping: bool = field(default=False, init=False)
    _current_job_id: int | None = field(default=None, init=False)
    # 直前の tick がジョブの失敗だったか。run() がログの重さを決めるのに使う。
    _failed: bool = field(default=False, init=False)

    # --- 観測 ---
    def last_event_at(self) -> float:
        return self.app.db.scalar("SELECT COALESCE(MAX(ts), 0) FROM events") or 0.0

    def is_idle(self, at: float | None = None) -> bool:
        if self.force:
            return True
        at = now() if at is None else at
        return (at - self.last_event_at()) >= self.app.config.unconscious.idle_seconds

    def pending_events(self) -> int:
        return self.app.db.scalar("SELECT COUNT(*) FROM events WHERE episode_id IS NULL") or 0

    # --- スケジュール ---
    def schedule(self, at: float | None = None) -> list[str]:
        """期限の来た定期ジョブを積む。積んだ種類を返す。"""
        at = now() if at is None else at
        config = self.app.config.unconscious
        db = self.app.db
        idle = self.is_idle(at)
        queued: list[str] = []

        def due(kind: str, interval_s: float) -> bool:
            return self.force or (at - jobs_store.last_run(db, kind)) >= interval_s

        # 会話を記憶に変える仕事は、話が途切れたらすぐやる（アイドル判定より短い間隔）
        if self.pending_events() and (at - self.last_event_at()) >= config.write_delay_seconds:
            if jobs_store.enqueue(db, "write", priority=5, run_after=at) is not None:
                queued.append("write")

        # 外界の取り込みは相手が話していても構わない（LLM を使わないので）。
        # ただし優先度は他の背景ジョブと同じにしておく。ここだけ高くすると、
        # 毎tick積まれる ingest が他の仕事を永久に押しのける（実際に起きた）。
        if due("ingest", config.ingest_interval_minutes * MINUTE):
            if jobs_store.enqueue(db, "ingest", run_after=at) is not None:
                jobs_store.mark_run(db, "ingest", at)
                queued.append("ingest")

        # ここから下は GPU を使う仕事。相手が黙っている間にだけやる。
        if not idle:
            return queued

        periodic = (
            ("associate", config.associate_interval_minutes * MINUTE),
            ("reflect", config.reflect_interval_minutes * MINUTE),
            ("decay", config.decay_interval_hours * HOUR),
            ("curate", config.curate_interval_hours * HOUR),
        )
        for kind, interval_s in periodic:
            if due(kind, interval_s):
                if jobs_store.enqueue(db, kind, run_after=at) is not None:
                    jobs_store.mark_run(db, kind, at)
                    queued.append(kind)
        return queued

    # --- 実行 ---
    def tick(self, at: float | None = None) -> str | None:
        at = now() if at is None else at
        self._failed = False
        config = self.app.config.unconscious
        db = self.app.db

        reaped = jobs_store.reap_stale(db, config.stale_job_seconds, at)
        if reaped and self.verbose:
            self._say(f"取り残されたジョブ {reaped} 件を戻した")

        queued = self.schedule(at)
        if queued and self.verbose:
            self._say("積んだ: " + ", ".join(queued))

        job = jobs_store.claim(db, at)
        if job is None:
            return None

        self._current_job_id = job.id
        handler = HANDLERS.get(job.kind)
        if handler is None:
            jobs_store.fail(db, job.id, f"unknown job kind: {job.kind}", max_attempts=1)
            self._current_job_id = None
            return f"{job.kind}: 未知のジョブ種"

        try:
            # 背景の推論は最低優先度で取り、対話が来たら中断される
            with self.app.gate.acquire(PRIORITY_BACKGROUND) as cancel:
                scoped = self._scoped_app(cancel)
                message = handler(scoped, job)
            jobs_store.complete(db, job.id)
            return f"{job.kind}: {message}"
        except Preempted:
            # 割り込まれただけなので失敗ではない。考えかけたことは、あとで考え直す。
            jobs_store.release(db, job.id)
            return f"{job.kind}: 対話に譲って中断"
        except KeyboardInterrupt:
            jobs_store.release(db, job.id)
            raise
        except Exception as error:  # noqa: BLE001 - デーモンは何があっても死なない
            jobs_store.fail(
                db,
                job.id,
                f"{type(error).__name__}: {error}",
                retry_in=config.job_retry_seconds,
                max_attempts=config.max_job_attempts,
            )
            self._failed = True
            return f"{job.kind}: 失敗 — {type(error).__name__}: {error}"
        finally:
            self._current_job_id = None

    def _scoped_app(self, cancel):
        """ジョブ実行中だけ LLM を中断可能なものに差し替えた App を作る。"""
        import dataclasses

        return dataclasses.replace(self.app, llm=CancellableLLM(self.app.llm, cancel))

    def _say(self, message: str) -> None:
        if self.log is not None:
            self.log(message)

    def _warn(self, message: str) -> None:
        """後から探したくなるもの（ジョブの失敗など）だけ重く出す。"""
        if self.warn is not None:
            self.warn(message)
        else:
            self._say(message)

    # --- 常駐 ---
    def stop(self, *_args) -> None:
        self._stopping = True

    def run(self) -> int:
        for received in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(received, self.stop)
            except (ValueError, AttributeError):  # メインスレッド以外／Windows の一部
                pass

        if self.log is None:
            logger = logs.setup(self.app.config, verbose=self.verbose)
            self.log = logger.info
            self.warn = logger.warning

        config = self.app.config.unconscious
        self._say(f"無意識を起動しました（tick {config.tick_seconds}秒 / pid {os.getpid()}）")
        try:
            while not self._stopping:
                try:
                    message = self.tick()
                except KeyboardInterrupt:
                    break
                if message and self._failed:
                    self._warn(message)
                elif message:
                    self._say(message)
                elif self.verbose:
                    self._say("することなし")

                deadline = time.monotonic() + config.tick_seconds
                while not self._stopping and time.monotonic() < deadline:
                    time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        finally:
            if self._current_job_id is not None:
                jobs_store.release(self.app.db, self._current_job_id)
            self._say("無意識を停止しました")
        return 0
