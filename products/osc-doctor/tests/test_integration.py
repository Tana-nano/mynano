import socket

import pytest
from pythonosc.udp_client import SimpleUDPClient

from od_fakes import FakeBrowser, FakeSys, make_cache, make_env, run_cli, vrchat
from osc_doctor import oscquery, receiver
from osc_doctor.sysinfo import PortState
from vrc_mock import FakeVRChat, FakeVRChatQuery, OscQueryProbe, free_udp_port

POSE = (0.0, 1.6, 0.0, 5.0, 90.0, 0.0)


def base_args(tmp_path, out_port, *extra):
    return ["--no-pause", "--seconds", "1", "--browse-seconds", "1", "--out-port", str(out_port),
            "--oscquery-port", str(free_udp_port()), "--out", str(tmp_path / "out"), *extra]


def vrc_sys(in_port):
    return FakeSys([vrchat()], {in_port: PortState(True, "VRChat.exe", 100)})


def test_fixed_port_reception(tmp_path):
    out_port = free_udp_port()
    with FakeVRChat(out_port=out_port) as vrc:
        def emit(_rcv):
            vrc.set_parameter("GestureLeft", 3)
            vrc.set_parameter("VRMode", 1)
            vrc.send_head_pose(*POSE)

        env = make_env(tmp_path, sysinfo=vrc_sys(9000), on_listening=emit)
        code, out = run_cli(base_args(tmp_path, out_port, "--in-port", "9000", "--verbose"), env)
    assert "[OK]" in out and "固定ポート" in out
    assert "/avatar/parameters/GestureLeft" in out
    assert "トラッキング" not in out  # tracking only judged for OSCQuery reception
    reports = list((tmp_path / "out").glob("report-*.txt"))
    assert len(reports) == 1


def test_oscquery_reception_with_tracking(tmp_path):
    out_port = free_udp_port()
    with FakeVRChat() as vrc:
        def emit(rcv: receiver.Receiver):
            probe = OscQueryProbe(rcv.http_port).probe()
            assert probe.wants_avatar and probe.wants_tracking
            vrc.retarget(probe.osc_port)
            vrc.set_parameter("VRMode", 1)
            for _ in range(5):
                vrc.send_head_pose(*POSE)

        env = make_env(tmp_path, sysinfo=vrc_sys(9000), on_listening=emit)
        code, out = run_cli(base_args(tmp_path, out_port, "--in-port", "9000"), env)
    assert "OSCQuery 経由" in out
    assert "頭・手首の位置が届いています（5 件" in out
    text = next((tmp_path / "out").glob("report-*.txt")).read_text(encoding="utf-8-sig")
    assert "/tracking/vrsystem/head/pose" in text and "範囲 [0.000, 0.000], [1.600, 1.600]" in text


def test_fixed_port_used_by_other_app_is_not_stolen(tmp_path):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as other:
        other.bind(("127.0.0.1", 0))
        other.settimeout(2)
        out_port = other.getsockname()[1]
        sysinfo = FakeSys([vrchat()], {9000: PortState(True, "VRChat.exe", 100),
                                       out_port: PortState(True, "VRCFaceTracking.exe", 9)})
        seen = {}

        def emit(rcv: receiver.Receiver):
            seen["bound"] = rcv.fixed_bound
            SimpleUDPClient("127.0.0.1", out_port).send_message("/avatar/parameters/X", 1)

        env = make_env(tmp_path, sysinfo=sysinfo, on_listening=emit)
        code, out = run_cli(base_args(tmp_path, out_port, "--in-port", "9000"), env)
        data, _ = other.recvfrom(1024)
    assert seen["bound"] is False
    assert b"/avatar/parameters/X" in data
    assert "VRCFaceTracking.exe が使っています" in out


def test_vrchat_oscquery_found_via_direct_http(tmp_path):
    with FakeVRChatQuery(osc_port=9555) as q:
        env = make_env(tmp_path, sysinfo=vrc_sys(9555), browser=FakeBrowser())
        args = base_args(tmp_path, free_udp_port())
        args[args.index("--oscquery-port") + 1] = str(q.http_port)
        code, out = run_cli(args, env)
    assert "直接確認で受信ポート 9555" in out
    assert "ポート 9555" in out and "VRChat.exe が受信に使っています" in out


def test_vrchat_oscquery_found_via_mdns(tmp_path):
    with FakeVRChatQuery(osc_port=9000) as q:
        try:
            q.advertise()
        except Exception as e:  # pragma: no cover - environment without multicast
            pytest.skip(f"mDNS unavailable here: {e}")
        env = make_env(tmp_path, sysinfo=vrc_sys(9000), browser=oscquery.ZeroconfBrowser(interfaces=["127.0.0.1"]))
        args = base_args(tmp_path, free_udp_port())
        args[args.index("--browse-seconds") + 1] = "3"
        code, out = run_cli(args, env)
    assert "VRChat を見つけました（VRChat-Client-07091F、受信ポート 9000）" in out


def test_mdns_failure_is_reported_not_fatal(tmp_path):
    env = make_env(tmp_path, sysinfo=vrc_sys(9000), browser=FakeBrowser(error=OSError("no multicast")))
    code, out = run_cli(base_args(tmp_path, free_udp_port()), env)
    assert "確認できませんでした（mDNS が使えません）" in out


def test_no_reception_extends_once_then_ng(tmp_path):
    sleeps = []
    env = make_env(tmp_path, sysinfo=vrc_sys(9000), sleep=lambda s: sleeps.append(s))
    code, out = run_cli(base_args(tmp_path, free_udp_port(), "--seconds", "2"), env)
    assert code == 1
    assert out.count("もう一度計測します") == 1
    assert len(sleeps) == 4  # 2 s + one 2 s extension, no third round
    assert "VRChat から何も届きませんでした" in out


def test_extension_catches_late_messages(tmp_path):
    out_port = free_udp_port()
    with FakeVRChat(out_port=out_port) as vrc:
        calls = []

        def sleep(_s):
            calls.append(1)
            if len(calls) == 2:  # during the extension
                vrc.set_parameter("Voice", 0.5)
                import time
                time.sleep(0.1)

        env = make_env(tmp_path, sysinfo=vrc_sys(9000), sleep=sleep)
        code, out = run_cli(base_args(tmp_path, out_port), env)
    assert "もう一度計測します" in out
    assert "届きました" in out
    text = next((tmp_path / "out").glob("report-*.txt")).read_text(encoding="utf-8-sig")
    assert "0 件のため 1 回延長" in text


def test_send_test_reaches_vrchat(tmp_path):
    with FakeVRChat() as vrc:
        env = make_env(tmp_path, sysinfo=vrc_sys(vrc.in_port))
        code, out = run_cli(base_args(tmp_path, free_udp_port(), "--in-port", str(vrc.in_port), "--send-test"), env)
        assert vrc.wait_for("/chatbox/input") is not None
    assert vrc.chatbox_texts() == ["OSCドクター: 送信テスト"]
    assert "送信テスト" in out


def test_send_test_skipped_without_vrchat(tmp_path):
    env = make_env(tmp_path)
    code, out = run_cli(base_args(tmp_path, free_udp_port(), "--send-test"), env)
    assert "送りませんでした" in out and code == 1


def test_fix_cache_confirm_and_move(tmp_path):
    env = make_env(tmp_path, input=lambda _p: "y")
    make_cache(env.vrc_dir, files=2)
    code, out = run_cli(base_args(tmp_path, free_udp_port(), "--fix-cache", "--no-report"), env)
    assert "退避しました" in out
    assert not (env.vrc_dir / "OSC").exists()
    assert len(list((tmp_path / "out" / "backup").glob("OSC-*/usr_*/Avatars/*.json"))) == 2


def test_fix_cache_declined_changes_nothing(tmp_path):
    env = make_env(tmp_path, input=lambda _p: "n")
    make_cache(env.vrc_dir)
    code, out = run_cli(base_args(tmp_path, free_udp_port(), "--fix-cache", "--no-report"), env)
    assert "中止しました" in out and (env.vrc_dir / "OSC").exists()


def test_fix_cache_yes_skips_prompt(tmp_path):
    def no_input(_p):
        raise AssertionError("should not ask")

    env = make_env(tmp_path, input=no_input)
    make_cache(env.vrc_dir)
    code, out = run_cli(base_args(tmp_path, free_udp_port(), "--fix-cache", "--yes", "--no-report"), env)
    assert "退避しました" in out


def test_fix_cache_failure_exit_2(tmp_path, monkeypatch):
    from osc_doctor import cache

    def boom(*_a, **_k):
        raise OSError("in use")

    monkeypatch.setattr(cache.shutil, "move", boom)
    env = make_env(tmp_path, sysinfo=vrc_sys(9000), input=lambda _p: "y")
    make_cache(env.vrc_dir)
    code, out = run_cli(base_args(tmp_path, free_udp_port(), "--fix-cache", "--no-report"), env)
    assert code == 2 and "退避できませんでした" in out and (env.vrc_dir / "OSC").exists()


def test_ctrl_c_during_measurement_still_reports(tmp_path):
    def interrupt(_s):
        raise KeyboardInterrupt

    env = make_env(tmp_path, sysinfo=vrc_sys(9000), sleep=interrupt)
    code, out = run_cli(base_args(tmp_path, free_udp_port()), env)
    assert "結果:" in out and "もう一度計測します" not in out
    assert list((tmp_path / "out").glob("report-*.txt"))


def test_report_save_failure_does_not_crash(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    env = make_env(tmp_path)
    args = base_args(tmp_path, free_udp_port())
    args[args.index("--out") + 1] = str(blocker / "sub")
    code, out = run_cli(args, env)
    assert "レポートを保存できませんでした" in out and code == 1


def test_no_vrchat_end_to_end_exit_code(tmp_path):
    env = make_env(tmp_path)
    code, out = run_cli(base_args(tmp_path, free_udp_port()), env)
    assert code == 1 and "起動していません" in out
