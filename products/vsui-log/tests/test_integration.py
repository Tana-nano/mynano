"""End-to-end over real UDP with shared/vrc_mock (FakeVRChat, LogWriter, OscQueryProbe)."""

import io
import socket
import time
import urllib.request
from datetime import date, datetime, timedelta

import pytest
from helpers import ManualClock, cfg, moving, still
from vrc_mock import FakeVRChat, LogWriter, OscQueryProbe, free_udp_port

from vsui_log.cli import main
from vsui_log.oscio import Handlers, OscReceiver, OscSender, PortInUse, build_dispatcher
from vsui_log.paths import default_paths
from vsui_log.runner import MSG_FORMAT, MSG_NO_POSE, Runner
from vsui_log.store import Store

T0 = datetime(2026, 9, 29, 23, 0, 0)


def wait_until(pred, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if pred():
            return True
        time.sleep(0.005)
    return pred()


class Advertised:
    def __init__(self):
        self.calls = []
        self.closed = False

    def __call__(self, name, http_port, osc_port):
        self.calls.append((name, http_port, osc_port))
        return lambda: setattr(self, "closed", True)


def noop_handlers(pose=None):
    n = lambda *_: None  # noqa: E731
    return Handlers(pose=pose or n, afk=n, vrmode=n)


# --- OSCQuery ---------------------------------------------------------------------

def test_oscquery_service_looks_right_to_vrchat():
    adv = Advertised()
    r = OscReceiver(build_dispatcher(noop_handlers(), datetime.now), "oscquery", direct_port=0, advertise=adv).start().ready()
    try:
        res = OscQueryProbe(r.http_port).probe()
        assert res.wants_avatar and res.wants_tracking
        assert res.osc_port == r.osc_port
        assert res.host_info["OSC_TRANSPORT"] == "UDP" and res.host_info["OSC_IP"] == "127.0.0.1"
        assert adv.calls == [(r.name, r.http_port, r.osc_port)]
        with pytest.raises(urllib.error.HTTPError):
            urllib.request.urlopen(f"http://127.0.0.1:{r.http_port}/nope", timeout=2)
    finally:
        r.stop()
    assert adv.closed


def test_startup_does_not_wait_for_mdns():
    import threading
    gate = threading.Event()

    def slow(*_):
        gate.wait(5)
        return lambda: None

    t = time.monotonic()
    r = OscReceiver(build_dispatcher(noop_handlers(), datetime.now), "oscquery", direct_port=0, advertise=slow).start()
    try:
        assert time.monotonic() - t < 1.0
        assert OscQueryProbe(r.http_port).probe().wants_tracking   # HTTP already serving
    finally:
        gate.set()
        r.stop()


def test_http_binds_loopback_only():
    r = OscReceiver(build_dispatcher(noop_handlers(), datetime.now), "oscquery", direct_port=0, advertise=Advertised()).start()
    try:
        assert r._servers[1].server_address[0] == "127.0.0.1"
    finally:
        r.stop()


def test_zeroconf_registration_uses_vrchat_service_types(monkeypatch):
    import zeroconf

    registered = []

    class FakeZC:
        def register_service(self, info):
            registered.append(info)

        def unregister_service(self, info):
            pass

        def close(self):
            pass

    monkeypatch.setattr(zeroconf, "Zeroconf", FakeZC)
    from vsui_log.oscio import zeroconf_advertise

    close = zeroconf_advertise("VsuiLog-1234", 8080, 9999)
    close()
    assert sorted(i.type for i in registered) == ["_osc._udp.local.", "_oscjson._tcp.local."]
    assert all(i.properties.get(b"txtvers") == b"1" for i in registered)


def test_auto_falls_back_to_fixed_when_mdns_fails():
    def broken(*_):
        raise OSError("mdns blocked")

    port = free_udp_port()
    got = []
    warned = []
    r = OscReceiver(build_dispatcher(noop_handlers(lambda ts, a: got.append(a)), datetime.now), "auto",
                    listen_port=port, direct_port=0, advertise=broken, on_warning=warned.append).start().ready()
    try:
        assert r.active_mode == "fixed" and r.osc_port == port and r.warnings == warned and warned
        with FakeVRChat(out_port=port) as vrc:
            vrc.send_head_pose(0, 1.2, 0, 0, 90, 0)
            assert wait_until(lambda: got)
    finally:
        r.stop()


def test_fixed_port_in_use_raises():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    try:
        r = OscReceiver(build_dispatcher(noop_handlers(), datetime.now), "fixed", listen_port=s.getsockname()[1], direct_port=0)
        with pytest.raises(PortInUse):
            r.start()
    finally:
        s.close()


def test_direct_port_receives_in_auto_and_is_optional():
    got = []
    direct = free_udp_port()
    h = Handlers(pose=lambda *_: None, afk=lambda *_: None, vrmode=lambda *_: None,
                 oyasumi=lambda ts, v: got.append(v), oyasumi_address="/avatar/parameters/VsuiLog/OyasumiSleep")
    r = OscReceiver(build_dispatcher(h, datetime.now), "auto", direct_port=direct, advertise=Advertised()).start()
    try:
        assert r.direct_active
        from pythonosc.udp_client import SimpleUDPClient
        SimpleUDPClient("127.0.0.1", direct).send_message("/avatar/parameters/VsuiLog/OyasumiSleep", True)
        assert wait_until(lambda: got == [True])
    finally:
        r.stop()
    # direct port busy -> warning only
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    try:
        r2 = OscReceiver(build_dispatcher(h, datetime.now), "auto", direct_port=s.getsockname()[1], advertise=Advertised()).start()
        assert not r2.direct_active and any("直送" in w for w in r2.warnings)
        r2.stop()
    finally:
        s.close()


def test_sender_parameters_and_chatbox():
    with FakeVRChat() as vrc:
        out = OscSender("127.0.0.1", vrc.in_port)
        out.sleeping(True)
        out.visitors(300)
        out.chatbox("おやすみ")
        assert wait_until(lambda: vrc.chatbox_texts() == ["おやすみ"])
        assert vrc.received_parameters() == {"VsuiLog/Sleeping": True, "VsuiLog/Visitors": 255}
        off = OscSender("127.0.0.1", vrc.in_port, send_parameters=False)
        vrc.clear()
        off.sleeping(True)
        off.chatbox("x")
        assert wait_until(lambda: vrc.chatbox_texts() == ["x"])
        assert vrc.received_parameters() == {}


# --- whole night through the runner -----------------------------------------------------

class NightHarness:
    def __init__(self, tmp_path, **overrides):
        self.clock = ManualClock(T0)
        self.paths = default_paths({"VSUILOG_HOME": str(tmp_path)})
        self.vrc = FakeVRChat().start()
        c = cfg(osc={"send_port": self.vrc.in_port, "direct_port": 0}, **overrides)
        self.notes = []
        self.runner = Runner(
            c, self.paths, clock=self.clock.now, notify=self.notes.append,
            receiver_factory=lambda d: OscReceiver(d, "oscquery", direct_port=0, advertise=Advertised()),
        )
        self.runner.start()
        self.log = LogWriter(self.paths.log_dir, start=T0)
        self.poses_sent = 0
        self.seed = 0

    @property
    def engine(self):
        return self.runner.engine

    def minutes(self, n, kind="still", per_min=6):
        port = self.runner.receiver.osc_port
        for _ in range(n):
            self.seed += 1
            samples = still(per_min, seed=self.seed) if kind == "still" else moving(per_min, seed=self.seed)
            if kind != "none":
                if self.vrc.out_port != port:
                    self.vrc.retarget(port)
                for s in samples:
                    self.vrc.send_head_pose(*s)
                self.poses_sent += len(samples)
                assert wait_until(lambda: self.engine.pose_count >= self.poses_sent)
            self.clock.advance(minutes=1)
            self.log.now = self.clock.t
            self.runner.step()

    def close(self):
        self.runner.stop()
        self.vrc.stop()


def test_one_night_end_to_end(tmp_path):
    h = NightHarness(tmp_path)
    try:
        h.log.raw("[Behaviour] User Authenticated: FixtureMe (usr_me)")
        h.log.join("wrld_a", "100", "Sample Sleep World", owner_user_id="usr_me")
        h.log.player_joined("FixtureMe", "usr_me")
        h.log.player_joined("FixtureAlice", "usr_a")
        h.minutes(10, "moving")
        h.minutes(40, "still")
        h.log.player_joined("Fixture Bob", "usr_b")
        h.minutes(5, "still")
        h.log.player_left("Fixture Bob", "usr_b")
        h.minutes(60, "still")
        h.minutes(5, "moving")
        h.minutes(31, "moving")
        assert wait_until(lambda: {"VsuiLog/Sleeping", "VsuiLog/Visitors"} <= set(h.vrc.received_parameters()))
        params = h.vrc.received_parameters()
        assert params["VsuiLog/Sleeping"] is False and params["VsuiLog/Visitors"] == 1
        assert h.vrc.chatbox_texts() == []                                  # chatbox off by default
        st = h.runner.store
        n = st.nights_on(date(2026, 9, 29))[0]
        assert n.world_name == "Sample Sleep World" and 100 <= n.sleep_minutes <= 110
        roles = {p["display_name"]: p["role"] for p in st.presence_for([n.id])}
        assert roles == {"FixtureAlice": "co_sleeper", "Fixture Bob": "visitor"}
        assert any("記録しました" in m for m in h.notes)
        assert "FixtureMe" in h.paths.config_path.read_text(encoding="utf-8")  # self name saved
        assert "OSC: OK" in h.runner.status_line()
    finally:
        h.close()


def test_chatbox_enabled_end_to_end(tmp_path):
    h = NightHarness(tmp_path, chatbox={"enabled": True})
    try:
        h.log.join("wrld_a", "1", "W")
        h.minutes(12, "still")
        h.minutes(4, "moving")
        assert wait_until(lambda: h.vrc.chatbox_texts() == ["💤 おやすみなさい", "おはようございます"])
    finally:
        h.close()


def test_no_pose_warning_and_format_warning(tmp_path):
    h = NightHarness(tmp_path)
    try:
        h.engine.on_afk(h.clock.t, False)  # OSC works, but no head pose
        h.log.raw("[Totally] New Format")
        h.minutes(61, "none")
        assert h.notes.count(MSG_NO_POSE) == 1
        assert h.notes.count(MSG_FORMAT) == 1
    finally:
        h.close()


def test_crash_recovery_through_runner(tmp_path):
    h = NightHarness(tmp_path)
    h.log.raw("[Behaviour] User Authenticated: FixtureMe (usr_me)")
    h.log.join("wrld_a", "1", "W")
    h.minutes(30, "still")
    crash_at = h.clock.t
    h.runner.receiver.stop()   # simulate a hard kill: no shutdown()
    h.vrc.stop()
    h2 = NightHarness(tmp_path)
    try:
        assert any("前回の終了時" in m for m in h2.notes)
        n = h2.runner.store.nights_on(date(2026, 9, 29))[0]
        assert n.sleep_end <= crash_at
    finally:
        h2.close()


# --- CLI ---------------------------------------------------------------------------------------

def run_cli(tmp_path, *argv, stdin=""):
    out = io.StringIO()
    code = main(list(argv), env={"VSUILOG_HOME": str(tmp_path)}, out=out, stdin=io.StringIO(stdin))
    return code, out.getvalue()


def seed_db(tmp_path):
    from test_outputs import seeded_store
    src = seeded_store()
    dst = Store(default_paths({"VSUILOG_HOME": str(tmp_path)}).db_path)
    src.conn.backup(dst.conn)
    dst.close()


def test_cli_commands(tmp_path):
    code, out = run_cli(tmp_path, "tonight")
    assert code == 0 and "まだ記録がありません" in out
    seed_db(tmp_path)
    code, out = run_cli(tmp_path, "tonight", "--date", "2026-09-29")
    assert code == 0 and "7時間50分" in out
    assert (tmp_path / "output" / "tonight_2026-09-29.html").exists()
    code, out = run_cli(tmp_path, "week", "--week", "2026-W40")
    assert code == 0 and (tmp_path / "output" / "week_2026-W40.html").exists()
    code, out = run_cli(tmp_path, "visitors", "--date", "2026-09-29")
    assert "1. 00:20 Fixture Bob" in out
    code, out = run_cli(tmp_path, "thanks", "1", "--date", "2026-09-29")
    assert code == 0
    code, out = run_cli(tmp_path, "visitors", "--date", "2026-09-29")
    assert "お礼済み" in out
    code, out = run_cli(tmp_path, "thanks", "Nobody", "--date", "2026-09-29")
    assert code == 1
    code, out = run_cli(tmp_path, "export")
    assert code == 0 and "3 夜分" in out
    code, out = run_cli(tmp_path, "chapters", "--date", "2026-09-29")
    assert (tmp_path / "output" / "chapters_2026-09-29.txt").read_text(encoding="utf-8") == "00:20:00 来客\n"
    code, out = run_cli(tmp_path, "achievements")
    assert "✓ 2026-09-29" in out and "はじめてのV睡" in out
    code, out = run_cli(tmp_path, "card", "--date", "2026-09-29")
    assert code in (0, 1)  # 1 when no Japanese font on this machine
    code, out = run_cli(tmp_path, "forget", "--all", stdin="n\n")
    assert "中止" in out
    code, out = run_cli(tmp_path, "forget", "FixtureAlice", "--yes")
    assert "1 人分" in out
    code, out = run_cli(tmp_path, "config", "--path")
    assert out.strip().endswith("config.toml")
    code, out = run_cli(tmp_path, "doctor")
    assert code == 0 and "VRChat ログ" in out


def test_cli_config_error_and_bad_date(tmp_path):
    p = default_paths({"VSUILOG_HOME": str(tmp_path)}).config_path
    p.parent.mkdir(parents=True)
    p.write_text('[osc]\nmode = "udp"\n', encoding="utf-8")
    code, out = run_cli(tmp_path, "tonight")
    assert code == 1 and "設定エラー" in out
    with pytest.raises(SystemExit):
        run_cli(tmp_path, "tonight", "--date", "yesterday")


def test_cli_doctor_log_sample(tmp_path):
    from test_outputs import FIXTURE_LOG
    log_dir = tmp_path / "vrchat"
    log_dir.mkdir()
    (log_dir / "output_log_2026-09-29_22-00-00.txt").write_text(FIXTURE_LOG, encoding="utf-8")
    code, out = run_cli(tmp_path, "doctor", "--log-sample")
    assert code == 0 and "Real Friend" not in out and "Player2" in out
    saved = (tmp_path / "output" / "doctor_log_sample.txt").read_text(encoding="utf-8")
    assert "RealMe" not in saved


def test_cli_doctor_pose_sample(tmp_path):
    port = free_udp_port()
    env = {"VSUILOG_HOME": str(tmp_path), "VSUILOG_OSC_MODE": "fixed", "VSUILOG_OSC_LISTEN_PORT": str(port)}
    import threading
    out = io.StringIO()

    def feed():
        with FakeVRChat(out_port=port) as vrc:
            for _ in range(40):
                vrc.send_head_pose(0, 1.2, 0, 0, 90, 0)
                time.sleep(0.02)

    t = threading.Thread(target=feed)
    t.start()
    code = main(["doctor", "--pose-sample", "0.05"], env=env, out=out)
    t.join()
    assert code == 0 and "サンプル" in out.getvalue()
    csvs = list((tmp_path / "output").glob("doctor_pose_*.csv"))
    assert csvs and len(csvs[0].read_text().splitlines()) > 1
