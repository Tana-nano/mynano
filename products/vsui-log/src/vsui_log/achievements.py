"""Text-only badges (spec: 実績)."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from .store import NightRecord, Store

ACHIEVEMENTS: dict[str, str] = {
    "first_night": "はじめてのV睡",
    "streak_3": "3日連続",
    "streak_7": "7日連続",
    "streak_30": "30日連続",
    "total_100h": "累計100時間",
    "long_sleep": "ぐっすり",
    "early_bird": "早起き",
    "popular": "人気者",
    "together_10": "いつものメンバー",
}


def current_streak(dates: list[date], upto: date) -> int:
    """Consecutive night dates ending at ``upto``."""
    have = set(dates)
    n, d = 0, upto
    while d in have:
        n += 1
        d -= timedelta(days=1)
    return n


def evaluate(store: Store, night: NightRecord, now: datetime) -> list[str]:
    """Unlock whatever this newly saved night earns. Returns newly unlocked keys."""
    earned: list[str] = ["first_night"]
    streak = current_streak(store.all_night_dates(), night.night_date)
    earned += [k for k, n in (("streak_3", 3), ("streak_7", 7), ("streak_30", 30)) if streak >= n]
    if store.total_sleep_minutes() >= 100 * 60:
        earned.append("total_100h")
    if (night.sleep_minutes or 0) >= 7 * 60:
        earned.append("long_sleep")
    if night.sleep_end is not None and night.sleep_end.hour < 6:
        earned.append("early_bird")
    if sum(1 for p in night.people if p.role == "visitor") >= 5:
        earned.append("popular")
    if any(c >= 10 for _, c in store.co_sleeper_counts()):
        earned.append("together_10")
    return [k for k in earned if store.unlock(k, now, night.night_date)]
