from datetime import datetime, timedelta

import pytest
from helpers import moving, params, still
from vrc_mock import LogWriter

from vsui_log.config import (
    ConfigError,
    DetectParams,
    ensure_config_file,
    load_config,
    save_self_name,
)
from vsui_log.detector import SleepDetector
from vsui_log.logparse import LogParser, parse_location
from vsui_log.logtail import LogTailer
from vsui_log.motion import MotionAggregator, Pose, Window, angle_delta
from vsui_log.paths import default_paths

T0 = datetime(2026, 9, 29, 23, 0, 0)


# --- paths -----------------------------------------------------------------

def test_default_paths_windows_env():
    p = default_paths({"APPDATA": r"C:\U\AppData\Roaming", "LOCALAPPDATA": r"C:\U\AppData\Local", "USERPROFILE": r"C:\U"})
    assert str(p.data_dir).endswith("VsuiLog")
    assert "LocalLow" in str(p.log_dir) and str(p.log_dir).endswith("VRChat")
    assert "Documents" in str(p.output_dir)


def test_vsuilog_home_overrides_everything(tmp_path):
    p = default_paths({"VSUILOG_HOME": str(tmp_path)})
    assert p.config_path == tmp_path / "data" / "config.toml"
    assert p.log_dir == tmp_path / "vrchat"


# --- config ----------------------------------------------------------------

def test_config_defaults_and_file_created(tmp_path):
    path = tmp_path / "config.toml"
    assert ensure_config_file(path)
    cfg = load_config(path, env={})
    assert cfg["osc"]["mode"] == "auto"
    assert cfg["detect"]["sleep_minutes"] == 10
    assert not ensure_config_file(path)


def test_config_toml_and_env_override(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[detect]\nsleep_minutes = 15\nsensitivity = "high"\n[osc]\nmode = "fixed"\n', encoding="utf-8")
    cfg = load_config(path, env={"VSUILOG_DETECT_SLEEP_MINUTES": "20", "VSUILOG_CHATBOX_ENABLED": "true"})
    assert cfg["detect"]["sleep_minutes"] == 20
    assert cfg["chatbox"]["enabled"] is True
    assert cfg["osc"]["mode"] == "fixed"
    p = DetectParams.from_config(cfg)
    assert p.sleep_threshold == pytest.approx(0.06)  # high = x2


@pytest.mark.parametrize(
    "toml, fragment",
    [
        ('[osc]\nmode = "udp"\n', "osc.mode"),
        ('[detect]\nsleep_minutes = "ten"\n', "detect.sleep_minutes"),
        ('[detect]\nsleep_minutes = 0\n', "detect.sleep_minutes"),
        ('[nope]\nx = 1\n', "不明な項目"),
        ('[log.patterns]\njoining = "("\n', "log.patterns.joining"),
        ("[osc\n", "書き方に誤り"),
    ],
)
def test_config_errors_are_readable(tmp_path, toml, fragment):
    path = tmp_path / "config.toml"
    path.write_text(toml, encoding="utf-8")
    with pytest.raises(ConfigError) as e:
        load_config(path, env={})
    assert fragment in str(e.value)


def test_save_self_name_keeps_comments(tmp_path):
    path = tmp_path / "config.toml"
    save_self_name(path, 'Neko "Chan"')
    text = path.read_text(encoding="utf-8")
    assert "# V睡ログ 設定ファイル" in text
    assert load_config(path, env={})["self"]["display_name"] == 'Neko "Chan"'


# --- log parsing -------------------------------------------------------------

P = LogParser()


def line(msg: str, ts: str = "2026.09.29 23:41:07") -> str:
    return f"{ts} Log        -  {msg}"


@pytest.mark.parametrize(
    "name",
    ["Alice", "Fixture Bob", "ねこ　まる", "A (B) C", "x_x!?", "名前 (カッコ)"],
)
def test_player_joined_names(name):
    ev = P.parse(line(f"[Behaviour] OnPlayerJoined {name} (usr_0000aaaa-0000-0000-0000-000000000001)"))
    assert ev.kind == "player_joined" and ev.name == name
    assert ev.user_id == "usr_0000aaaa-0000-0000-0000-000000000001"
    ev2 = P.parse(line(f"[Behaviour] OnPlayerLeft {name}"))
    assert ev2.kind == "player_left" and ev2.name == name and ev2.user_id is None


def test_other_events_and_timestamp():
    ev = P.parse(line("[Behaviour] Joining wrld_abc:123~private(usr_x)~region(jp)"))
    assert ev.kind == "joining" and ev.location.startswith("wrld_abc:123")
    assert ev.ts == datetime(2026, 9, 29, 23, 41, 7)
    assert P.parse(line("[Behaviour] Entering Room: Sleep World")).world_name == "Sleep World"
    assert P.parse(line("[Behaviour] OnLeftRoom")).kind == "left_room"
    assert P.parse(line("[Behaviour] User Authenticated: Me (usr_1)")).name == "Me"
    assert P.parse(line("[Behaviour] something else")) is None
    assert P.parse("garbage") is None
    assert P.parse("\ufeff" + line("[Behaviour] OnLeftRoom") + "\r\n").kind == "left_room"


@pytest.mark.parametrize(
    "loc, access",
    [
        ("wrld_a:1~private(usr_x)~canRequestInvite~region(jp)", "private"),
        ("wrld_a:1~friends(usr_x)~region(jp)", "friends"),
        ("wrld_a:1~hidden(usr_x)~region(jp)", "hidden"),
        ("wrld_a:1~group(grp_x)~groupAccessType(members)", "group"),
        ("wrld_a:1~region(jp)", "public"),
        ("wrld_a:1", "public"),
    ],
)
def test_parse_location(loc, access):
    l = parse_location(loc)
    assert l.world_id == "wrld_a" and l.instance_id == "1" and l.access == access


def test_pattern_override():
    p = LogParser({"player_joined": r"^\[Net\] Joined (?P<name>.+)$"})
    assert p.parse(line("[Net] Joined Alice")).name == "Alice"
    assert p.parse(line("[Behaviour] OnPlayerJoined Alice")) is None


# --- log tailing ---------------------------------------------------------------

def test_tailer_reads_appends_and_partial_lines(tmp_path):
    w = LogWriter(tmp_path, start=T0)
    t = LogTailer(tmp_path, LogParser())
    w.join("wrld_a", "1", "World")
    assert [e.kind for e in t.poll(T0)] == ["joining", "entering_room"]
    assert t.poll(T0) == []
    full = "2026.09.29 23:00:00 Log        -  [Behaviour] OnPlayerJoined Alice\n"
    with w.path.open("a", encoding="utf-8") as f:
        f.write(full[:30])
    assert t.poll(T0) == []
    with w.path.open("a", encoding="utf-8") as f:
        f.write(full[30:])
    assert [e.name for e in t.poll(T0)] == ["Alice"]


def test_tailer_handles_bom_and_bad_bytes(tmp_path):
    path = tmp_path / "output_log_2026-09-29_23-00-00.txt"
    path.write_bytes(b"\xef\xbb\xbf" + line("[Behaviour] OnLeftRoom").encode() + b"\n\xff\xfe junk\n")
    evs = LogTailer(tmp_path, LogParser()).poll(T0)
    assert [e.kind for e in evs] == ["left_room"]


def test_tailer_follows_most_recently_modified_file(tmp_path):
    import os
    old = LogWriter(tmp_path, start=T0)
    new = LogWriter(tmp_path, start=T0 + timedelta(hours=1))
    old.raw("[Behaviour] OnPlayerJoined OldFile")
    new.raw("[Behaviour] OnPlayerJoined NewFile")
    os.utime(old.path, (1, 1))
    t = LogTailer(tmp_path, LogParser())
    assert [e.name for e in t.poll(T0)] == ["NewFile"]
    # The older-named file becomes the live one (e.g. a second client): switch by mtime.
    old.raw("[Behaviour] OnPlayerJoined OldAgain")
    os.utime(old.path, None)
    os.utime(new.path, (1, 1))
    assert [e.name for e in t.poll(T0)] == ["OldFile", "OldAgain"]


def test_tailer_missing_directory(tmp_path):
    assert LogTailer(tmp_path / "nope", LogParser()).poll(T0) == []


def test_format_warning_once_after_an_hour_without_matches(tmp_path):
    w = LogWriter(tmp_path, start=T0)
    t = LogTailer(tmp_path, LogParser())
    w.raw("[Totally] New Format Alice")
    t.poll(T0)
    assert not t.format_warning_due(T0 + timedelta(minutes=59))
    assert t.format_warning_due(T0 + timedelta(minutes=60))
    assert not t.format_warning_due(T0 + timedelta(minutes=120))


# --- motion -------------------------------------------------------------------

def feed(agg: MotionAggregator, samples, start=T0, per_min=10) -> list[Window]:
    out = []
    step = 60 / per_min
    for i, s in enumerate(samples):
        out += agg.add(start + timedelta(seconds=i * step), Pose(*s))
    return out


def test_angle_delta_wraps():
    assert angle_delta(179, -179) == pytest.approx(2)
    assert angle_delta(-170, 170) == pytest.approx(20)
    assert angle_delta(10, 20) == pytest.approx(10)


def test_still_is_below_threshold_and_moving_is_above():
    p = params()
    ws = feed(MotionAggregator(p), still(60) + moving(60))
    assert all(w.motion < p.sleep_threshold for w in ws[:6])
    assert all(w.motion > p.wake_threshold for w in ws[6:11])


def test_translation_only_and_rotation_only():
    p = params(angle_weight=0.01)
    agg = MotionAggregator(p)
    trans = [(i * 0.01, 1.2, 0, 0, 90, 0) for i in range(10)]
    rot = [(0.09, 1.2, 0, 0, 90 + i, 0) for i in range(1, 11)]
    w = feed(agg, trans + rot + [(0.09, 1.2, 0.0001, 0, 100, 0)])
    assert w[0].motion == pytest.approx(0.09)          # 9 steps x 1 cm
    assert w[1].motion == pytest.approx(0.10)          # 10 steps x 1 deg x 0.01


def test_too_few_samples_is_no_data():
    p = params(min_samples=5)
    agg = MotionAggregator(p)
    feed(agg, still(4), per_min=4)
    w = agg.tick(T0 + timedelta(minutes=1))
    assert len(w) == 1 and w[0].motion is None


def test_jump_is_discarded():
    p = params(max_jump=1.0)
    s = still(10)
    s[5] = (5.0, 1.2, 0, 0, 90, 0)  # tracking snaps 5 m away and back
    w = feed(MotionAggregator(p), s + still(1, seed=9))
    assert w[0].motion < p.wake_threshold


def test_frozen_pose_is_tracking_loss_not_stillness():
    p = params(frozen_samples=20)
    frozen = [(0.1, 1.2, 0.1, 0, 90, 0)] * 30
    agg = MotionAggregator(p)
    w = feed(agg, frozen, per_min=30) + agg.tick(T0 + timedelta(minutes=2))
    assert w[0].motion is None
    assert w[0].last_good == T0  # only the first sample was trusted


def test_gap_produces_no_data_windows():
    p = params()
    agg = MotionAggregator(p)
    feed(agg, still(10))
    ws = agg.tick(T0 + timedelta(minutes=5))
    assert len(ws) == 5 and ws[0].has_data and not any(w.has_data for w in ws[1:])


# --- detector ------------------------------------------------------------------

def win(i: int, motion: float | None) -> Window:
    start = T0 + timedelta(minutes=i)
    return Window(start, motion, 10 if motion is not None else 0, start + timedelta(seconds=54) if motion is not None else None)


def run(det: SleepDetector, motions: list, start: int = 0):
    out = []
    for i, m in enumerate(motions, start=start):
        out += det.on_window(win(i, m))
    return out


def test_ten_still_minutes_fall_asleep_backdated():
    det = SleepDetector(params())
    tr = run(det, [0.5] * 3 + [0.01] * 10)
    assert [(t.kind, t.at) for t in tr] == [("sleep", T0 + timedelta(minutes=3))]


def test_single_toss_does_not_wake_three_minutes_do():
    det = SleepDetector(params())
    run(det, [0.01] * 10)
    assert run(det, [0.5, 0.01, 0.5, 0.5, 0.01], start=10) == []
    tr = run(det, [0.5, 0.5, 0.5], start=15)
    assert [(t.kind, t.at, t.reason) for t in tr] == [("wake", T0 + timedelta(minutes=15), "motion")]


def test_no_data_holds_runs_and_gap_ends_at_last_sample():
    det = SleepDetector(params())
    run(det, [0.01] * 5 + [None] * 3 + [0.01] * 5)  # holds across the gap
    assert det.asleep
    last_good = win(12, 0.01).last_good
    tr = run(det, [None] * 10, start=13)
    assert [(t.kind, t.at, t.reason) for t in tr] == [("wake", last_good, "gap")]


def test_afk_debounce():
    det = SleepDetector(params(afk_minutes=2))
    run(det, [0.01] * 10)
    t = T0 + timedelta(minutes=20)
    det.on_afk(t, True)
    assert det.check_afk(t + timedelta(minutes=1)) == []
    det.on_afk(t + timedelta(minutes=1), False)
    det.on_afk(t + timedelta(minutes=3), True)
    assert det.check_afk(t + timedelta(minutes=4)) == []
    tr = det.check_afk(t + timedelta(minutes=5))
    assert [(x.kind, x.at, x.reason) for x in tr] == [("wake", t + timedelta(minutes=3), "afk")]


def test_oyasumi_overrides_motion():
    det = SleepDetector(params())
    t = T0 + timedelta(minutes=1)
    assert [x.kind for x in det.on_oyasumi(t, True)] == ["sleep"]
    assert run(det, [0.9] * 5, start=2) == []  # moving, but OyasumiVR says asleep
    tr = det.on_oyasumi(t + timedelta(minutes=10), False)
    assert [(x.kind, x.reason) for x in tr] == [("wake", "oyasumi")]


def test_force_end_and_sensitivity():
    det = SleepDetector(params())
    assert det.force_end(T0, "left_room") == []
    run(det, [0.01] * 10)
    assert det.force_end(T0 + timedelta(minutes=30), "left_room")[0].reason == "left_room"
    # 0.05 is "awake" at normal, "still" at high sensitivity (threshold x2 = 0.06)
    assert run(SleepDetector(params()), [0.05] * 10) == []
    assert run(SleepDetector(params(sensitivity="high")), [0.05] * 10)[0].kind == "sleep"
    assert run(SleepDetector(params(sensitivity="low")), [0.02] * 10) == []
