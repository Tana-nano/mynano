from datetime import date, datetime, timedelta

import pytest
from helpers import moving, params, still

from vsui_log.achievements import current_streak
from vsui_log.engine import Engine, night_date_for
from vsui_log.logparse import LogEvent
from vsui_log.store import NightRecord, PersonRecord, Store

T0 = datetime(2026, 9, 29, 23, 0, 0)
ME = "FixtureMe"


class Recorder:
    def __init__(self):
        self.calls = []

    def sleeping(self, v):
        self.calls.append(("sleeping", v))

    def visitors(self, n):
        self.calls.append(("visitors", n))

    def chatbox(self, text):
        self.calls.append(("chatbox", text))


class Sim:
    """Drives an Engine minute by minute with synthetic poses and log events."""

    def __init__(self, store=None, start=T0, **engine_kw):
        self.t = start
        self.store = store or Store(":memory:")
        self.out = Recorder()
        engine_kw.setdefault("self_name", ME)
        self.params = engine_kw.pop("params", params())
        self.e = Engine(self.params, self.store, self.out, started_at=start - timedelta(hours=1), **engine_kw)
        self.seed = 0

    def minutes(self, n, kind="still", per_min=10):
        for _ in range(n):
            self.seed += 1
            samples = still(per_min, seed=self.seed) if kind == "still" else moving(per_min, seed=self.seed)
            for i, s in enumerate(samples):
                if kind != "none":
                    self.e.on_pose(self.t + timedelta(seconds=i * 60 / per_min), s)
            self.t += timedelta(minutes=1)
            self.e.tick(self.t)

    def log(self, kind, **kw):
        self.e.on_log_event(LogEvent(kind=kind, ts=self.t, **kw))

    def join_world(self, name="Sleep World", loc="wrld_a:100~private(usr_me)~region(jp)"):
        self.log("joining", location=loc)
        self.log("entering_room", world_name=name)
        self.log("player_joined", name=ME, user_id="usr_me")

    def player(self, name, uid=None, left=False):
        self.log("player_left" if left else "player_joined", name=name, user_id=uid)


def test_night_date_rule():
    assert night_date_for(datetime(2026, 9, 29, 23, 30)) == date(2026, 9, 29)
    assert night_date_for(datetime(2026, 9, 30, 1, 0)) == date(2026, 9, 29)
    assert night_date_for(datetime(2026, 9, 30, 12, 0)) == date(2026, 9, 30)


def test_full_night_with_co_sleeper_and_visitor():
    s = Sim()
    s.join_world()
    s.player("FixtureAlice", "usr_a")
    s.minutes(20, "moving")
    s.minutes(60, "still")                       # asleep from 23:20
    s.player("Fixture Bob", "usr_b")             # visitor at 00:20
    s.minutes(10, "still")
    s.player("Fixture Bob", "usr_b", left=True)
    s.minutes(400, "still")
    s.minutes(5, "moving")                        # wake at 07:10
    s.minutes(31, "moving")                       # merge window passes -> saved
    assert len(s.e.saved) == 1
    n = s.store.nights_on(date(2026, 9, 29))[0]
    # The first still window still carries the last movement across the boundary: +-1 min.
    assert abs(n.sleep_start - datetime(2026, 9, 29, 23, 20)) <= timedelta(minutes=1)
    assert n.sleep_end == datetime(2026, 9, 30, 7, 10)
    assert 469 <= n.sleep_minutes <= 470 and n.world_name == "Sleep World" and n.instance_access == "private"
    roles = {p["display_name"]: p["role"] for p in s.store.presence_for([n.id])}
    assert roles == {"FixtureAlice": "co_sleeper", "Fixture Bob": "visitor"}
    assert ("sleeping", True) in s.out.calls and ("visitors", 1) in s.out.calls
    assert s.out.calls[-1] == ("sleeping", False)
    assert not any(c[0] == "chatbox" for c in s.out.calls)


def test_short_wake_is_merged_and_counted():
    s = Sim()
    s.join_world()
    s.minutes(5, "moving")
    s.minutes(60, "still")
    s.minutes(5, "moving")     # wake
    s.minutes(20, "still")     # back asleep within 30 min
    s.minutes(60, "still")
    s.minutes(40, "moving")
    assert len(s.e.saved) == 1
    n = s.e.saved[0]
    assert n.awakenings == 1
    assert n.sleep_minutes < (n.sleep_end - n.sleep_start).total_seconds() / 60


def test_merge_applies_across_rejoin_after_crash():
    s = Sim()
    s.join_world()
    s.minutes(60, "still")
    s.log("left_room")                            # VRChat dropped
    s.minutes(5, "none")
    s.join_world(loc="wrld_a:200~private(usr_me)~region(jp)")
    s.minutes(60, "still")
    s.minutes(40, "moving")
    assert len(s.e.saved) == 1 and s.e.saved[0].awakenings == 1


def test_chatbox_once_each_when_enabled():
    s = Sim(chatbox_enabled=True, sleep_text="おやすみ", wake_text="おはよう")
    s.join_world()
    s.minutes(15, "still")
    s.minutes(5, "moving")
    s.minutes(15, "still")
    s.minutes(40, "moving")
    texts = [c[1] for c in s.out.calls if c[0] == "chatbox"]
    assert texts == ["おやすみ", "おはよう"]


def test_afk_ends_night_at_afk_time():
    s = Sim()
    s.join_world()
    s.minutes(60, "still")
    t_off = s.t
    s.e.on_afk(t_off, True)
    s.minutes(40, "none")
    assert s.e.saved[0].sleep_end == t_off


def test_oyasumi_forces_sleep_through_motion():
    s = Sim()
    s.join_world()
    s.e.on_oyasumi(s.t, True)
    s.minutes(30, "moving")
    s.e.on_oyasumi(s.t, False)
    s.minutes(31, "moving")
    n = s.e.saved[0]
    assert n.source == "oyasumi" and n.sleep_minutes == 30


def test_people_not_saved_until_self_known_and_only_for_nights():
    s = Sim(self_name="")
    s.log("joining", location="wrld_a:1~region(jp)")
    s.player("SomeoneFirst")                       # heuristic candidate, not confirmed
    s.player("DaytimeFriend")
    s.minutes(20, "moving")
    s.player("DaytimeFriend", left=True)
    s.minutes(60, "still")
    s.minutes(40, "moving")
    assert len(s.e.saved) == 1
    assert s.store.count_people() == 0


def test_self_confirmed_by_authenticated_line():
    confirmed = []
    s = Sim(self_name="", on_self_confirmed=confirmed.append)
    s.log("authenticated", name=ME)
    assert confirmed == [ME] and s.e.me.name == ME


def test_self_confirmed_by_three_first_joins():
    confirmed = []
    s = Sim(self_name="", on_self_confirmed=confirmed.append)
    for i in range(3):
        s.log("joining", location=f"wrld_a:{i}")
        s.player(ME)
        if i == 0:
            s.log("joining", location="wrld_b:9")
            s.player("Other")                     # resets the run
            s.log("joining", location="wrld_a:10")
            s.player(ME)
    assert confirmed == [ME]


def test_daytime_people_are_never_stored():
    s = Sim()
    s.join_world()
    s.player("DaytimeOnly")
    s.minutes(30, "moving")
    s.player("DaytimeOnly", left=True)
    s.minutes(60, "still")
    s.minutes(40, "moving")
    names = [p["display_name"] for p in s.store.presence_for([s.e.saved[0].id])]
    assert "DaytimeOnly" not in names


def test_log_only_night_for_desktop():
    s = Sim(start=datetime(2026, 9, 29, 22, 0))
    s.e.on_vrmode(s.t, 0)
    s.join_world()
    s.player("FixtureAlice")
    s.t = datetime(2026, 9, 30, 7, 0)
    s.log("left_room")
    n = s.e.saved[0]
    assert (n.mode, n.source, n.sleep_minutes) == ("log_only", "log", None)
    assert n.night_date == date(2026, 9, 29)
    assert [p["role"] for p in s.store.presence_for([n.id])] == ["co_sleeper"]


def test_vr_night_without_detected_sleep_is_kept_as_log_night():
    s = Sim(start=datetime(2026, 9, 29, 23, 30))
    s.join_world()
    s.minutes(150, "moving")   # thresholds too strict for this user: never "asleep"
    s.log("left_room")
    n = s.e.saved[0]
    assert (n.mode, n.source) == ("vr", "log")


@pytest.mark.parametrize(
    "start, end, saved",
    [
        (datetime(2026, 9, 29, 22, 0), datetime(2026, 9, 29, 23, 30), False),  # no 0-6
        (datetime(2026, 9, 30, 5, 30), datetime(2026, 9, 30, 6, 10), False),  # < 60 min
        (datetime(2026, 9, 30, 3, 0), datetime(2026, 9, 30, 9, 0), True),
    ],
)
def test_log_night_rules(start, end, saved):
    s = Sim(start=start)
    s.e.on_vrmode(s.t, 0)
    s.join_world()
    s.t = end
    s.log("left_room")
    assert bool(s.e.saved) is saved


def test_history_before_startup_is_not_turned_into_nights():
    s = Sim(start=datetime(2026, 9, 30, 12, 0))
    s.e.started_at = datetime(2026, 9, 30, 12, 0)
    s.t = datetime(2026, 9, 29, 23, 0)
    s.join_world()
    s.t = datetime(2026, 9, 30, 7, 0)
    s.log("left_room")
    assert s.e.saved == []


def test_checkpoint_and_recover(tmp_path):
    store = Store(tmp_path / "vsui.db")
    s = Sim(store=store)
    s.join_world()
    s.player("FixtureAlice", "usr_a")
    s.minutes(90, "still")
    s.e.checkpoint(s.t)
    crash_t = s.t
    # process dies; new engine on the same db
    s2 = Sim(store=Store(tmp_path / "vsui.db"), self_name="")
    rec = s2.e.recover(crash_t + timedelta(hours=2))
    assert rec is not None and rec.sleep_end == crash_t
    assert [p.display_name for p in rec.people] == ["FixtureAlice"]
    assert s2.store.load_checkpoint() is None


def test_shutdown_saves_open_night():
    s = Sim()
    s.join_world()
    s.minutes(60, "still")
    s.e.shutdown(s.t)
    assert len(s.e.saved) == 1


def test_duplicate_night_is_ignored():
    st = Store(":memory:")
    n = NightRecord(night_date=date(2026, 9, 29), mode="vr", source="motion", sleep_start=T0, sleep_end=T0 + timedelta(hours=1), sleep_minutes=60)
    assert st.save_night(n) is not None
    n2 = NightRecord(night_date=date(2026, 9, 29), mode="vr", source="motion", sleep_start=T0, sleep_end=T0 + timedelta(hours=1), sleep_minutes=60)
    assert st.save_night(n2) is None


def test_store_forget_and_broken_db(tmp_path):
    st = Store(tmp_path / "vsui.db")
    n = NightRecord(
        night_date=date(2026, 9, 29), mode="vr", source="motion", sleep_start=T0, sleep_end=T0 + timedelta(hours=1),
        sleep_minutes=60,
        people=[PersonRecord("A", "usr_a", T0, None, "co_sleeper"), PersonRecord("B", None, T0, None, "visitor")],
    )
    st.save_night(n)
    assert st.forget("A") == 1 and st.count_people() == 1
    assert [p["display_name"] for p in st.presence_for([n.id])] == ["B"]
    assert st.forget() == 1 and st.count_people() == 0
    st.close()
    (tmp_path / "bad.db").write_bytes(b"this is not sqlite" * 100)
    bad = Store(tmp_path / "bad.db")
    assert bad.recovered_from is not None and bad.recovered_from.exists()
    assert bad.latest_night_date() is None


def test_achievements():
    s = Sim()
    for day in range(3):
        s.t = datetime(2026, 9, 29, 23, 0) + timedelta(days=day)
        s.join_world(loc=f"wrld_a:{day}~region(jp)")
        s.minutes(5, "moving")
        s.minutes(430, "still")
        s.minutes(40, "moving")
    unlocked = s.store.unlocked()
    assert {"first_night", "streak_3", "long_sleep"} <= set(unlocked)
    assert "streak_7" not in unlocked
    assert current_streak([date(2026, 9, 29), date(2026, 9, 30), date(2026, 10, 2)], date(2026, 10, 2)) == 1
