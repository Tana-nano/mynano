"""Core engine: pose/OSC/log events in, nights out.

Every method takes explicit timestamps, so tests can fast-forward a whole night
without waiting. All public methods are thread-safe (OSC handlers run on
server threads).
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Any, Callable, Protocol

from . import achievements
from .config import DetectParams
from .detector import SleepDetector, Transition
from .logparse import LogEvent, parse_location
from .motion import MotionAggregator, Pose, Window
from .store import NightRecord, PersonRecord, Store

log = logging.getLogger(__name__)

SELF_CONFIRM_INSTANCES = 3
LOG_NIGHT_MIN = timedelta(minutes=60)
LOG_NIGHT_HOURS = (0, 6)  # stays overlapping 0:00-6:00
PRUNE_AFTER = timedelta(hours=36)


class Outputs(Protocol):
    def sleeping(self, value: bool) -> None: ...
    def visitors(self, count: int) -> None: ...
    def chatbox(self, text: str) -> None: ...


class NullOutputs:
    def sleeping(self, value: bool) -> None: ...
    def visitors(self, count: int) -> None: ...
    def chatbox(self, text: str) -> None: ...


def night_date_for(sleep_start: datetime) -> date:
    return sleep_start.date() if sleep_start.hour >= 12 else sleep_start.date() - timedelta(days=1)


def person_key(name: str, user_id: str | None) -> str:
    return user_id or f"name:{name}"


def overlap(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> timedelta:
    return max(timedelta(0), min(a1, b1) - max(a0, b0))


@dataclass
class Player:
    name: str
    user_id: str | None
    intervals: list[list[datetime | None]] = field(default_factory=list)  # [joined, left|None]

    @property
    def present(self) -> bool:
        return bool(self.intervals) and self.intervals[-1][1] is None


@dataclass
class Stay:
    key: str
    start: datetime
    world_id: str | None = None
    world_name: str | None = None
    access: str | None = None
    end: datetime | None = None
    pose_seen: bool = False
    desktop: bool = False
    first_joiner: str | None = None
    players: dict[str, Player] = field(default_factory=dict)

    def close(self, ts: datetime) -> None:
        self.end = ts
        for p in self.players.values():
            if p.present:
                p.intervals[-1][1] = ts

    def to_json(self) -> dict[str, Any]:
        iso = lambda v: v.isoformat() if v else None  # noqa: E731
        return {
            "key": self.key, "start": iso(self.start), "end": iso(self.end), "world_id": self.world_id,
            "world_name": self.world_name, "access": self.access, "pose_seen": self.pose_seen,
            "desktop": self.desktop,
            "players": {k: {"name": p.name, "user_id": p.user_id, "intervals": [[iso(a), iso(b)] for a, b in p.intervals]}
                        for k, p in self.players.items()},
        }

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Stay":
        dt = lambda v: datetime.fromisoformat(v) if v else None  # noqa: E731
        s = cls(key=d["key"], start=dt(d["start"]), world_id=d["world_id"], world_name=d["world_name"],
                access=d["access"], end=dt(d["end"]), pose_seen=d["pose_seen"], desktop=d["desktop"])
        for k, p in d["players"].items():
            s.players[k] = Player(p["name"], p["user_id"], [[dt(a), dt(b)] for a, b in p["intervals"]])
        return s


@dataclass
class Segment:
    start: datetime
    end: datetime | None
    stay_key: str | None
    source: str


@dataclass
class ActiveNight:
    segments: list[Segment] = field(default_factory=list)
    awakenings: int = 0
    visitor_keys: set[str] = field(default_factory=set)
    sleep_text_sent: bool = False
    wake_text_sent: bool = False

    @property
    def last_end(self) -> datetime | None:
        return self.segments[-1].end if self.segments else None

    @property
    def open(self) -> bool:
        return bool(self.segments) and self.segments[-1].end is None


class SelfResolver:
    """Who am I? config > 'User Authenticated' log line > first joiner x3."""

    def __init__(self, configured: str, on_confirm: Callable[[str], None] | None = None) -> None:
        self.name: str | None = configured or None
        self.on_confirm = on_confirm
        self._candidate: str | None = None
        self._count = 0

    def _confirm(self, name: str) -> None:
        if self.name is None:
            self.name = name
            if self.on_confirm:
                self.on_confirm(name)

    def authenticated(self, name: str) -> None:
        self._confirm(name)

    def first_joiner(self, name: str) -> None:
        # UNVERIFIED: VRChat logs the local player as the first OnPlayerJoined of an instance.
        if self.name is not None:
            return
        if name == self._candidate:
            self._count += 1
        else:
            self._candidate, self._count = name, 1
        if self._count >= SELF_CONFIRM_INSTANCES:
            self._confirm(name)


class Engine:
    def __init__(
        self,
        params: DetectParams,
        store: Store,
        outputs: Outputs | None = None,
        *,
        self_name: str = "",
        on_self_confirmed: Callable[[str], None] | None = None,
        chatbox_enabled: bool = False,
        sleep_text: str = "",
        wake_text: str = "",
        oyasumi_address: str | None = None,
        started_at: datetime | None = None,
        on_night_saved: Callable[[NightRecord, list[str]], None] | None = None,
        keep_samples_days: int = 30,
    ) -> None:
        self.p = params
        self.store = store
        self.out: Outputs = outputs or NullOutputs()
        self.lock = threading.RLock()
        self.agg = MotionAggregator(params)
        self.det = SleepDetector(params)
        self.me = SelfResolver(self_name, on_self_confirmed)
        self.chatbox_enabled = chatbox_enabled
        self.sleep_text = sleep_text
        self.wake_text = wake_text
        self.oyasumi_address = oyasumi_address
        self.started_at = started_at or datetime.min
        self.on_night_saved = on_night_saved
        self.keep_samples_days = keep_samples_days

        self.stays: dict[str, Stay] = {}
        self.current: Stay | None = None
        self.night: ActiveNight | None = None
        self.recent_segments: list[tuple[datetime, datetime]] = []
        self.last_pose_at: datetime | None = None
        self.pose_count = 0
        self.last_osc_at: datetime | None = None
        self.vrmode: int | None = None
        self.last_motion: float | None = None
        self.saved: list[NightRecord] = []

    # ------------------------------------------------------------------ inputs

    def on_pose(self, ts: datetime, args: tuple) -> None:
        pose = Pose.from_args(tuple(args))
        if pose is None:
            return
        with self.lock:
            self.pose_count += 1
            self.last_pose_at = self.last_osc_at = ts
            if self.current is not None:
                self.current.pose_seen = True
            if self.vrmode == 0:
                return
            self._windows(self.agg.add(ts, pose))

    def on_afk(self, ts: datetime, value: Any) -> None:
        with self.lock:
            self.last_osc_at = ts
            self.det.on_afk(ts, bool(value))

    def on_vrmode(self, ts: datetime, value: Any) -> None:
        with self.lock:
            self.last_osc_at = ts
            try:
                self.vrmode = int(value)
            except (TypeError, ValueError):
                return
            if self.vrmode == 0 and self.current is not None:
                self.current.desktop = True

    def on_oyasumi(self, ts: datetime, value: Any) -> None:
        with self.lock:
            self._apply(self.det.on_oyasumi(ts, bool(value)), ts)

    def on_log_event(self, ev: LogEvent) -> None:
        with self.lock:
            handler = getattr(self, f"_log_{ev.kind}", None)
            if handler:
                handler(ev)

    def tick(self, now: datetime) -> None:
        with self.lock:
            self._windows(self.agg.tick(now))
            self._apply(self.det.check_afk(now), now)
            self._maybe_finalize(now)
            self._prune(now)

    def shutdown(self, now: datetime) -> None:
        with self.lock:
            end = self.last_pose_at if self.last_pose_at and self.det.asleep else now
            self._apply(self.det.force_end(end, "exit"), now)
            self._finalize(now)
            self.store.clear_checkpoint()

    # ------------------------------------------------------------------ status

    @property
    def asleep(self) -> bool:
        return self.det.asleep

    def status(self) -> dict[str, Any]:
        with self.lock:
            people = 0
            if self.current:
                people = sum(1 for k, p in self.current.players.items() if p.present and p.name != self.me.name)
            return {
                "mode": "desktop" if self.vrmode == 0 else "vr",
                "asleep": self.det.asleep,
                "motion": self.last_motion,
                "world": self.current.world_name if self.current else None,
                "people": people,
                "visitors": len(self.night.visitor_keys) if self.night else 0,
            }

    # ------------------------------------------------------------------ log

    def _log_joining(self, ev: LogEvent) -> None:
        if self.current is not None and self.current.end is None:
            self._close_stay(ev.ts)
        loc = parse_location(ev.location or "")
        key = f"{ev.location}@{ev.ts.isoformat()}"
        stay = Stay(key=key, start=ev.ts, world_id=loc.world_id, access=loc.access, desktop=self.vrmode == 0)
        self.stays[key] = stay
        self.current = stay

    def _log_entering_room(self, ev: LogEvent) -> None:
        if self.current is not None:
            self.current.world_name = ev.world_name

    def _log_authenticated(self, ev: LogEvent) -> None:
        if ev.name:
            self.me.authenticated(ev.name)

    def _log_player_joined(self, ev: LogEvent) -> None:
        if self.current is None or not ev.name:
            return
        stay = self.current
        if stay.first_joiner is None:
            stay.first_joiner = ev.name
            self.me.first_joiner(ev.name)
        k = person_key(ev.name, ev.user_id)
        player = stay.players.setdefault(k, Player(ev.name, ev.user_id))
        if not player.present:
            player.intervals.append([ev.ts, None])
        if self.det.asleep and self.night is not None and ev.name != self.me.name:
            seg = self.night.segments[-1]
            if seg.stay_key == stay.key and ev.ts >= seg.start and k not in self.night.visitor_keys:
                self.night.visitor_keys.add(k)
                self.out.visitors(min(255, len(self.night.visitor_keys)))

    def _log_player_left(self, ev: LogEvent) -> None:
        if self.current is None or not ev.name:
            return
        player = self.current.players.get(person_key(ev.name, ev.user_id))
        if player and player.present:
            player.intervals[-1][1] = ev.ts

    def _log_left_room(self, ev: LogEvent) -> None:
        if self.current is not None and self.current.end is None:
            self._close_stay(ev.ts)

    def _close_stay(self, ts: datetime) -> None:
        stay = self.current
        assert stay is not None
        self._apply(self.det.force_end(ts, "left_room"), ts)
        stay.close(ts)
        self.current = None
        self._maybe_log_night(stay)

    # ------------------------------------------------------------------ detection

    def _windows(self, windows: list[Window]) -> None:
        for w in windows:
            if w.has_data:
                self.last_motion = w.motion
            if w.samples:
                self.store.add_sample(w.start, w.motion)
            self._apply(self.det.on_window(w), w.start)

    def _apply(self, transitions: list[Transition], now: datetime) -> None:
        for t in transitions:
            if t.kind == "sleep":
                self._on_sleep(t)
            else:
                self._on_wake(t)

    def _on_sleep(self, t: Transition) -> None:
        stay_key = self.current.key if self.current else None
        n = self.night
        if n is not None and n.last_end is not None and t.at - n.last_end <= timedelta(minutes=self.p.merge_minutes):
            n.awakenings += 1
        else:
            if n is not None:
                self._finalize(t.at)
            n = self.night = ActiveNight()
        n.segments.append(Segment(t.at, None, stay_key, t.reason))
        self.out.sleeping(True)
        if self.chatbox_enabled and not n.sleep_text_sent and self.sleep_text:
            n.sleep_text_sent = True
            self.out.chatbox(self.sleep_text)

    def _on_wake(self, t: Transition) -> None:
        n = self.night
        if n is None or not n.open:
            return
        n.segments[-1].end = t.at
        self.out.sleeping(False)
        if self.chatbox_enabled and not n.wake_text_sent and self.wake_text:
            n.wake_text_sent = True
            self.out.chatbox(self.wake_text)

    def _maybe_finalize(self, now: datetime) -> None:
        n = self.night
        if n is None or n.open or n.last_end is None:
            return
        if now - n.last_end > timedelta(minutes=self.p.merge_minutes):
            self._finalize(now)

    # ------------------------------------------------------------------ nights

    def _people_for(self, intervals: list[tuple[datetime, datetime, str | None]]) -> list[PersonRecord] | None:
        """Classify people against (start, end, stay_key) sleep intervals. None if self is unknown."""
        if self.me.name is None:
            log.warning("self display name unknown; skipping people for this night")
            return None
        min_overlap = timedelta(minutes=self.p.co_sleeper_minutes)
        found: dict[str, PersonRecord] = {}
        for s0, s1, stay_key in intervals:
            stay = self.stays.get(stay_key) if stay_key else None
            if stay is None:
                continue
            for k, pl in stay.players.items():
                if pl.name == self.me.name:
                    continue
                total = timedelta(0)
                joined_during = False
                touched: list[tuple[datetime, datetime]] = []
                for a, b in pl.intervals:
                    b = b or s1
                    ov = overlap(a, b, s0, s1)
                    if ov > timedelta(0) or s0 <= a <= s1:
                        touched.append((a, b))
                    total += ov
                    if s0 < a <= s1:
                        joined_during = True
                if not touched:
                    continue
                role = "co_sleeper" if total >= min_overlap else ("visitor" if joined_during else None)
                if role is None:
                    continue
                prev = found.get(k)
                rec = PersonRecord(pl.name, pl.user_id, min(a for a, _ in touched), max(b for _, b in touched), role)
                if prev is None:
                    found[k] = rec
                else:
                    prev.joined_at = min(prev.joined_at, rec.joined_at)
                    prev.left_at = max(prev.left_at or rec.left_at, rec.left_at or prev.left_at)
                    if "co_sleeper" in (prev.role, rec.role):
                        prev.role = "co_sleeper"
        return list(found.values())

    def _finalize(self, now: datetime) -> None:
        n = self.night
        self.night = None
        if n is None or not n.segments:
            return
        if n.open:
            n.segments[-1].end = now
        segs = [s for s in n.segments if s.end is not None and s.end > s.start]
        if not segs:
            return
        first = segs[0]
        stay = self.stays.get(first.stay_key) if first.stay_key else None
        minutes = int(sum(((s.end - s.start) for s in segs), timedelta(0)).total_seconds() // 60)
        people = self._people_for([(s.start, s.end, s.stay_key) for s in segs])
        rec = NightRecord(
            night_date=night_date_for(first.start),
            mode="vr",
            source=first.source,
            world_id=stay.world_id if stay else None,
            world_name=stay.world_name if stay else None,
            instance_access=stay.access if stay else None,
            instance_key=first.stay_key,
            stay_start=stay.start if stay else None,
            stay_end=stay.end if stay else None,
            sleep_start=first.start,
            sleep_end=segs[-1].end,
            sleep_minutes=minutes,
            awakenings=n.awakenings,
            people=people or [],
        )
        for s in segs:
            self.recent_segments.append((s.start, s.end))
        self._save(rec, now)

    def _maybe_log_night(self, stay: Stay) -> None:
        if stay.end is None or stay.end < self.started_at:
            return  # history replayed at startup, not observed live
        if stay.end - stay.start < LOG_NIGHT_MIN:
            return
        night_d = self._log_night_date(stay.start, stay.end)
        if night_d is None:
            return
        for a, b in self.recent_segments:
            if overlap(a, b, stay.start, stay.end) > timedelta(0):
                return
        if self.night is not None:
            for s in self.night.segments:
                if overlap(s.start, s.end or stay.end, stay.start, stay.end) > timedelta(0):
                    return
        people = self._people_for([(stay.start, stay.end, stay.key)])
        mode = "vr" if stay.pose_seen and not stay.desktop else "log_only"
        rec = NightRecord(
            night_date=night_d, mode=mode, source="log", world_id=stay.world_id, world_name=stay.world_name,
            instance_access=stay.access, instance_key=stay.key, stay_start=stay.start, stay_end=stay.end,
            people=people or [],
        )
        self._save(rec, stay.end)

    @staticmethod
    def _log_night_date(start: datetime, end: datetime) -> date | None:
        d = start.date()
        while datetime.combine(d, time()) < end:
            w0 = datetime.combine(d, time(LOG_NIGHT_HOURS[0]))
            w1 = datetime.combine(d, time(LOG_NIGHT_HOURS[1]))
            if overlap(start, end, w0, w1) > timedelta(0):
                return d - timedelta(days=1)
            d += timedelta(days=1)
        return None

    def _save(self, rec: NightRecord, now: datetime) -> None:
        if self.store.save_night(rec) is None:
            return
        unlocked = achievements.evaluate(self.store, rec, now)
        self.saved.append(rec)
        if self.on_night_saved:
            self.on_night_saved(rec, unlocked)

    def _prune(self, now: datetime) -> None:
        keep: set[str] = set()
        if self.current:
            keep.add(self.current.key)
        if self.night:
            keep.update(s.stay_key for s in self.night.segments if s.stay_key)
        for k in [k for k, s in self.stays.items() if k not in keep and s.end and now - s.end > PRUNE_AFTER]:
            del self.stays[k]
        self.recent_segments = [(a, b) for a, b in self.recent_segments if now - b <= PRUNE_AFTER]
        if now.minute == 0 and now.second < 2:
            self.store.prune_samples(now, self.keep_samples_days)

    # ------------------------------------------------------------------ checkpoint

    def checkpoint(self, now: datetime) -> None:
        with self.lock:
            if self.night is None:
                self.store.clear_checkpoint()
                return
            iso = lambda v: v.isoformat() if v else None  # noqa: E731
            keys = {s.stay_key for s in self.night.segments if s.stay_key}
            self.store.save_checkpoint({
                "saved_at": now.isoformat(),
                "self_name": self.me.name,
                "awakenings": self.night.awakenings,
                "segments": [[iso(s.start), iso(s.end), s.stay_key, s.source] for s in self.night.segments],
                "stays": [self.stays[k].to_json() for k in keys if k in self.stays],
            })

    def recover(self, now: datetime) -> NightRecord | None:
        """Finalize a night left behind by a crash. Wake time = last checkpoint."""
        with self.lock:
            data = self.store.load_checkpoint()
            if not data:
                return None
            saved_at = datetime.fromisoformat(data["saved_at"])
            if self.me.name is None and data.get("self_name"):
                self.me.name = data["self_name"]
            for sj in data["stays"]:
                stay = Stay.from_json(sj)
                if stay.end is None:
                    stay.close(saved_at)
                self.stays.setdefault(stay.key, stay)
            night = ActiveNight(awakenings=data["awakenings"])
            for a, b, k, src in data["segments"]:
                night.segments.append(
                    Segment(datetime.fromisoformat(a), datetime.fromisoformat(b) if b else saved_at, k, src)
                )
            self.night = night
            before = len(self.saved)
            self._finalize(saved_at)
            self.store.clear_checkpoint()
            return self.saved[-1] if len(self.saved) > before else None
