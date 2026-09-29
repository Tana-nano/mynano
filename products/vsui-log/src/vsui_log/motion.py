"""Turn head pose samples into one motion value per 60-second window.

motion = sum(|delta position| in m) + angle_weight * sum(|delta euler| in degrees)

UNVERIFIED: VRChat's units (m / degrees) and send rate for
/tracking/vrsystem/head/pose. Everything here is rate-independent and every
threshold is configurable.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from .config import DetectParams

WINDOW = timedelta(seconds=60)


@dataclass(frozen=True)
class Pose:
    x: float
    y: float
    z: float
    rx: float
    ry: float
    rz: float

    @classmethod
    def from_args(cls, args: tuple) -> "Pose | None":
        if len(args) < 6:
            return None
        try:
            vals = [float(a) for a in args[:6]]
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(v) for v in vals):
            return None
        return cls(*vals)


@dataclass(frozen=True)
class Window:
    start: datetime
    motion: float | None  # None = no data (too few samples or tracking lost)
    samples: int
    last_good: datetime | None  # last sample that looked like real tracking

    @property
    def has_data(self) -> bool:
        return self.motion is not None


def angle_delta(a: float, b: float) -> float:
    """Shortest absolute difference between two angles in degrees."""
    return abs((b - a + 180.0) % 360.0 - 180.0)


def floor_minute(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


class MotionAggregator:
    def __init__(self, params: DetectParams) -> None:
        self.p = params
        self.start: datetime | None = None
        self.prev: Pose | None = None
        self.frozen_run = 0
        self.last_good: datetime | None = None
        self._reset_window()

    def _reset_window(self) -> None:
        self.motion = 0.0
        self.samples = 0
        self.frozen = False
        self.window_last_good: datetime | None = None

    def _close(self) -> Window:
        assert self.start is not None
        ok = self.samples >= self.p.min_samples and not self.frozen
        w = Window(self.start, self.motion if ok else None, self.samples, self.window_last_good)
        self.start += WINDOW
        self._reset_window()
        return w

    def _advance(self, ts: datetime) -> list[Window]:
        out: list[Window] = []
        if self.start is None:
            return out
        while self.start + WINDOW <= ts:
            out.append(self._close())
        return out

    def tick(self, now: datetime) -> list[Window]:
        return self._advance(now)

    def add(self, ts: datetime, pose: Pose) -> list[Window]:
        if self.start is None:
            self.start = floor_minute(ts)
        out = self._advance(ts)
        self.samples += 1
        prev = self.prev
        self.prev = pose
        if prev is not None and pose == prev:
            self.frozen_run += 1
        else:
            self.frozen_run = 1
        if self.frozen_run >= self.p.frozen_samples:
            # Bit-identical poses for this long: tracking lost, not stillness.
            self.frozen = True
            return out
        if self.frozen_run == 1:
            self.last_good = ts
            self.window_last_good = ts
        if prev is None:
            return out
        dist = math.dist((prev.x, prev.y, prev.z), (pose.x, pose.y, pose.z))
        if dist > self.p.max_jump:
            return out  # tracking jump; re-anchor on this sample
        rot = angle_delta(prev.rx, pose.rx) + angle_delta(prev.ry, pose.ry) + angle_delta(prev.rz, pose.rz)
        self.motion += dist + self.p.angle_weight * rot
        return out
