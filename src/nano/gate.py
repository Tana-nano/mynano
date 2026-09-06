"""InferenceGate — 1枚のGPUを「意識」と「無意識」で譲り合うための優先度ゲート。

VRAM 8〜16GB では対話用モデルと背景ジョブ用モデルを同時に常駐できない。
そこで推論は必ずこのゲートを通し、対話（高優先度）が来た瞬間に
背景ジョブ（低優先度）へ中断を通知する。これが実装上の
「無意識は意識に譲る」の定義である。
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import Iterator

PRIORITY_CHAT = 0
PRIORITY_REFLEX = 5
PRIORITY_BACKGROUND = 10


class Preempted(Exception):
    """優先度の高い仕事に割り込まれて中断した。ジョブはキューへ戻される。"""


class CancelToken:
    """生成ループが定期的に見張る中断フラグ。"""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def reset(self) -> None:
        self._event.clear()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise Preempted("higher-priority work requested the model")


class InferenceGate:
    def __init__(self) -> None:
        self._cv = threading.Condition(threading.Lock())
        self._holder_priority: int | None = None
        self._holder_cancel: CancelToken | None = None
        self._waiting: list[int] = []

    @contextmanager
    def acquire(
        self, priority: int = PRIORITY_BACKGROUND, cancel: CancelToken | None = None
    ) -> Iterator[CancelToken]:
        """モデルの占有権を取る。数値が小さいほど高優先度。"""
        token = cancel or CancelToken()
        token.reset()
        with self._cv:
            self._waiting.append(priority)
            try:
                while self._holder_priority is not None:
                    # 自分の方が優先度が高いなら、いま占有している側に退去を通知する。
                    if priority < self._holder_priority and self._holder_cancel is not None:
                        self._holder_cancel.cancel()
                    self._cv.wait()
            finally:
                self._waiting.remove(priority)
            self._holder_priority = priority
            self._holder_cancel = token
        try:
            yield token
        finally:
            with self._cv:
                self._holder_priority = None
                self._holder_cancel = None
                self._cv.notify_all()

    def should_yield(self, priority: int) -> bool:
        """自分より高い優先度が待っているか。長い処理の合間に自発的に譲るために使う。"""
        with self._cv:
            return any(waiting < priority for waiting in self._waiting)


class SharedInferenceGate:
    """プロセスをまたぐ推論ゲート。

    `InferenceGate` は threading ベースなので、同じプロセスの中でしか効かない。
    M2 でデーモンが `nano chat` とは別プロセスになった時点で、
    「対話が来たら背景の思考を中断させる」という性質がプロセス境界で失われる。

    そこで soul.db の `model_lease`（1行だけの表）をリースとして使い、
    プロセス内の排他（InferenceGate）の外側にプロセス間の排他を重ねる。

      - 高優先度が来ると、保持中の低優先度リースに preempt_requested を立てる
      - 保持側のウォッチドッグがそれを見て CancelToken を立てる
        → 生成ループが Preempted で抜ける → ジョブは待ち行列へ戻る
      - リースには期限があり、保持者のプロセスが死んでも自動で回収される

    ファイルロックにしないのは fcntl が Windows で使えないから。
    常駐先が Windows である以上、SQLite で完結させるほうが移植性が高い。

    なお llama-server 自体はリクエストを直列化するので、これは
    正しさのためではなく**待ち時間**のための仕組みである。
    """

    def __init__(
        self,
        db_path,
        holder: str = "",
        ttl_s: float = 10.0,
        poll_s: float = 0.05,
        heartbeat_s: float = 0.2,
    ) -> None:
        import os
        import sqlite3

        self.ttl_s = ttl_s
        self.poll_s = poll_s
        self.heartbeat_s = heartbeat_s
        self.holder = holder or f"pid{os.getpid()}"
        self._local = InferenceGate()
        # ゲート専用の接続。アプリ側の接続とスレッドを共有しないので、
        # ウォッチドッグスレッドから安全に触れる。
        self._conn = sqlite3.connect(
            str(db_path), check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn_lock = threading.Lock()

    def close(self) -> None:
        with self._conn_lock:
            self._conn.close()

    # --- リース操作 ---
    def _try_take(self, priority: int, at: float) -> bool:
        with self._conn_lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute("SELECT * FROM model_lease WHERE id=1").fetchone()
                if row is None:  # 古い魂を開いた場合の保険
                    self._conn.execute("INSERT OR IGNORE INTO model_lease(id) VALUES(1)")
                    row = self._conn.execute("SELECT * FROM model_lease WHERE id=1").fetchone()

                free = not row["holder"] or row["expires_at"] <= at
                if free:
                    self._conn.execute(
                        """UPDATE model_lease
                           SET holder=?, priority=?, acquired_at=?, expires_at=?, preempt_requested=0
                           WHERE id=1""",
                        (self.holder, priority, at, at + self.ttl_s),
                    )
                    self._conn.execute("COMMIT")
                    return True

                # 自分の方が優先度が高いなら、退去を要求してから待つ。
                # 横取りはしない。相手が生成中のトークンを捨てて抜けるのを待つ。
                if priority < row["priority"] and not row["preempt_requested"]:
                    self._conn.execute("UPDATE model_lease SET preempt_requested=1 WHERE id=1")
                self._conn.execute("COMMIT")
                return False
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise

    def _release_lease(self) -> None:
        with self._conn_lock:
            self._conn.execute(
                """UPDATE model_lease SET holder='', priority=99, expires_at=0, preempt_requested=0
                   WHERE id=1 AND holder=?""",
                (self.holder,),
            )

    def _heartbeat(self, token: CancelToken, stop: threading.Event) -> None:
        """期限を延ばしつつ、退去要求を監視する。"""
        while not stop.wait(self.heartbeat_s):
            with self._conn_lock:
                # UPDATE ... RETURNING は SQLite 3.35+ 限定。10年動かす前提なので使わない。
                self._conn.execute(
                    "UPDATE model_lease SET expires_at=? WHERE id=1 AND holder=?",
                    (time.time() + self.ttl_s, self.holder),
                )
                row = self._conn.execute(
                    "SELECT preempt_requested FROM model_lease WHERE id=1 AND holder=?",
                    (self.holder,),
                ).fetchone()
            if row is not None and row["preempt_requested"]:
                token.cancel()
                return

    @contextmanager
    def acquire(
        self, priority: int = PRIORITY_BACKGROUND, cancel: CancelToken | None = None
    ) -> Iterator[CancelToken]:
        """`InferenceGate.acquire` と同じ使い方ができる。呼び出し側は差し替えを意識しない。"""
        with self._local.acquire(priority, cancel) as token:
            while not self._try_take(priority, time.time()):
                if token.cancelled:  # 待っている間に自分が割り込まれることもある
                    raise Preempted("preempted while waiting for the model")
                time.sleep(self.poll_s)

            stop = threading.Event()
            watchdog = threading.Thread(
                target=self._heartbeat, args=(token, stop), daemon=True, name="nano-gate"
            )
            watchdog.start()
            try:
                yield token
            finally:
                stop.set()
                watchdog.join(timeout=1.0)
                self._release_lease()

    def should_yield(self, priority: int) -> bool:
        if self._local.should_yield(priority):
            return True
        with self._conn_lock:
            row = self._conn.execute(
                "SELECT preempt_requested FROM model_lease WHERE id=1 AND holder=?", (self.holder,)
            ).fetchone()
        return bool(row and row["preempt_requested"])
