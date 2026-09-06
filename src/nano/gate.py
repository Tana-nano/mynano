"""InferenceGate — 1枚のGPUを「意識」と「無意識」で譲り合うための優先度ゲート。

VRAM 8〜16GB では対話用モデルと背景ジョブ用モデルを同時に常駐できない。
そこで推論は必ずこのゲートを通し、対話（高優先度）が来た瞬間に
背景ジョブ（低優先度）へ中断を通知する。これが実装上の
「無意識は意識に譲る」の定義である。
"""

from __future__ import annotations

import threading
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
