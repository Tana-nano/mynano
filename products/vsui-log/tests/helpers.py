"""Shared test helpers: fake clock, pose series, default params."""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from vsui_log.config import DEFAULTS, DetectParams


@dataclass
class ManualClock:
    t: datetime

    def now(self) -> datetime:
        return self.t

    def advance(self, **delta: float) -> datetime:
        self.t += timedelta(**delta)
        return self.t


def cfg(**overrides: dict) -> dict:
    c = copy.deepcopy(DEFAULTS)
    for section, values in overrides.items():
        c[section].update(values)
    return c


def params(**detect) -> DetectParams:
    return DetectParams.from_config(cfg(detect=detect))


def still(n: int, seed: int = 0, noise: float = 0.0002) -> list[tuple]:
    """n nearly-still samples (tiny float noise, never bit-identical)."""
    r = random.Random(seed)
    return [
        (r.uniform(-noise, noise), 1.2 + r.uniform(-noise, noise), r.uniform(-noise, noise),
         r.uniform(-0.01, 0.01), 90 + r.uniform(-0.01, 0.01), r.uniform(-0.01, 0.01))
        for _ in range(n)
    ]


def moving(n: int, seed: int = 1, step: float = 0.05) -> list[tuple]:
    """n samples of an awake head (a few cm and degrees per sample)."""
    r = random.Random(seed)
    out, x, ry = [], 0.0, 90.0
    for _ in range(n):
        x += r.choice((-step, step))
        ry += r.choice((-5.0, 5.0))
        out.append((x, 1.6, 0.0, 0.0, ry, 0.0))
    return out
