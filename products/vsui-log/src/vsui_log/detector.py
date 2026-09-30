"""Sleep/wake state machine over motion windows (spec: 状態遷移・主要ロジック)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import DetectParams
from .motion import Window


@dataclass(frozen=True)
class Transition:
    kind: str  # "sleep" | "wake"
    at: datetime
    reason: str  # sleep: motion|oyasumi ; wake: motion|oyasumi|afk|gap|left_room|exit


class SleepDetector:
    def __init__(self, params: DetectParams) -> None:
        self.p = params
        self.asleep = False
        self.sleep_at: datetime | None = None
        self.forced: bool | None = None  # OyasumiVR state when known
        self.afk_since: datetime | None = None
        self.last_good: datetime | None = None
        self._reset_runs()
        self.nodata_run = 0

    def _reset_runs(self) -> None:
        self.still_run = 0
        self.still_start: datetime | None = None
        self.move_run = 0
        self.move_start: datetime | None = None

    def _sleep(self, at: datetime, reason: str) -> list[Transition]:
        self.asleep = True
        self.sleep_at = at
        self._reset_runs()
        return [Transition("sleep", at, reason)]

    def _wake(self, at: datetime, reason: str) -> list[Transition]:
        if self.sleep_at is not None and at < self.sleep_at:
            at = self.sleep_at
        self.asleep = False
        self.sleep_at = None
        self._reset_runs()
        return [Transition("wake", at, reason)]

    def on_window(self, w: Window) -> list[Transition]:
        if not w.has_data:
            # Hold both runs: no-data neither proves stillness nor movement.
            self.nodata_run += 1
            if self.asleep and self.nodata_run >= self.p.gap_minutes:
                end = self.last_good or w.start
                return self._wake(end, "gap")
            return []
        self.nodata_run = 0
        if w.last_good is not None:
            self.last_good = w.last_good
        assert w.motion is not None
        if self.forced is True:
            return []
        if not self.asleep:
            if w.motion < self.p.sleep_threshold:
                if self.still_run == 0:
                    self.still_start = w.start
                self.still_run += 1
                if self.still_run >= self.p.sleep_minutes:
                    assert self.still_start is not None
                    return self._sleep(self.still_start, "motion")
            else:
                self.still_run = 0
            return []
        if w.motion > self.p.wake_threshold:
            if self.move_run == 0:
                self.move_start = w.start
            self.move_run += 1
            if self.move_run >= self.p.wake_minutes:
                assert self.move_start is not None
                return self._wake(self.move_start, "motion")
        else:
            self.move_run = 0
        return []

    def on_afk(self, ts: datetime, afk: bool) -> None:
        if afk:
            if self.afk_since is None:
                self.afk_since = ts
        else:
            self.afk_since = None

    def check_afk(self, now: datetime) -> list[Transition]:
        if not self.asleep or self.afk_since is None:
            return []
        if now - self.afk_since >= timedelta(minutes=self.p.afk_minutes):
            return self._wake(self.afk_since, "afk")
        return []

    def on_oyasumi(self, ts: datetime, sleeping: bool) -> list[Transition]:
        self.forced = sleeping
        if sleeping and not self.asleep:
            return self._sleep(ts, "oyasumi")
        if not sleeping and self.asleep:
            return self._wake(ts, "oyasumi")
        return []

    def force_end(self, ts: datetime, reason: str) -> list[Transition]:
        return self._wake(ts, reason) if self.asleep else []
