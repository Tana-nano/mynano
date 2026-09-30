import socket
from datetime import datetime

import pytest

from od_fakes import NOW, make_cache
from osc_doctor import cache, checks, cli, report
from osc_doctor.checks import INFO, NG, OK, WARN, Facts, RxSummary, judge
from osc_doctor.oscquery import VrcQuery
from osc_doctor.receiver import Collector
from osc_doctor.sysinfo import LaunchOsc, PortState, PsutilSystemInfo, parse_osc_arg

VRC = PortState(True, "VRChat.exe", 100)


def ids(findings):
    return {f.id: f for f in findings}


def oq(port=9000, via="mdns", avatar=True):
    return VrcQuery("VRChat-Client-07091F", "127.0.0.1", port, avatar, via)


def healthy(**kw) -> Facts:
    base = dict(
        vrc_running=True,
        ports={9000: VRC},
        fixed_bound=True,
        discovery_vrc=oq(),
        rx=RxSummary(total=50, fixed=10, oscquery=40, addresses=5, avatar_params=3, tracking_oscquery=30, tracking_rate=3.0),
    )
    base.update(kw)
    return Facts(**base)


# --- launch args ------------------------------------------------------------

@pytest.mark.parametrize("cmd,expected", [
    (["VRChat.exe", "--osc=9000:127.0.0.1:9001"], LaunchOsc(9000, "127.0.0.1", 9001)),
    (["VRChat.exe", "--no-vr", "--osc=9100:127.0.0.1:9101", "-screen-width"], LaunchOsc(9100, "127.0.0.1", 9101)),
    (["VRChat.exe"], None),
    (["VRChat.exe", "--osc=abc"], None),
    (["VRChat.exe", "--osc=99999:127.0.0.1:9001"], None),
])
def test_parse_osc_arg(cmd, expected):
    assert parse_osc_arg(cmd) == expected


# --- port resolution ----------------------------------------------------------

def test_vrc_in_prefers_host_info_then_explicit_then_launch():
    launch = LaunchOsc(9100, "127.0.0.1", 9101)
    assert Facts(discovery_vrc=oq(9555), explicit_in=9200, launch=launch).vrc_in == 9555
    assert Facts(explicit_in=9200, launch=launch).vrc_in == 9200
    assert Facts(launch=launch).vrc_in == 9100
    assert Facts().vrc_in == 9000
    assert Facts(launch=launch).out_port == 9101
    assert Facts(launch=launch, explicit_out=9300).out_port == 9300


def test_oscquery_port_resolution():
    assert checks.resolve_oscquery_port(None, None) == 9001
    assert checks.resolve_oscquery_port(None, LaunchOsc(9100, "127.0.0.1", 9101)) == 9101
    assert checks.resolve_oscquery_port(9500, LaunchOsc(9100, "127.0.0.1", 9101)) == 9500


# --- judge --------------------------------------------------------------------

def test_healthy_has_no_problems():
    fs = judge(healthy())
    got = ids(fs)
    assert {"VRC_RUNNING", "IN_PORT_VRC", "OQ_FOUND", "RX_OK", "TRACKING_OK", "CACHE_NONE"} <= set(got)
    assert checks.summary(fs) == "問題は見つかりませんでした"
    assert checks.exit_code(fs) == 0


def test_vrchat_not_running_suppresses_dependent_checks():
    fs = judge(Facts(vrc_running=False, installer_running=True))
    got = ids(fs)
    assert got["VRC_NOT_RUNNING"].status == NG
    assert "INSTALLER_LEFT" in got
    assert not any(i.startswith(("RX_", "OQ_", "TRACKING_", "IN_PORT_")) for i in got)
    assert checks.exit_code(fs) == 1


def test_launch_args_shown():
    f = judge(healthy(launch=LaunchOsc(9000, "127.0.0.1", 9001)))
    assert "--osc=9000:127.0.0.1:9001" in ids(f)["VRC_RUNNING"].message


def test_in_port_other_app():
    got = ids(judge(healthy(ports={9000: PortState(True, "Other.exe", 5)})))
    assert got["IN_PORT_OTHER"].status == NG and "Other.exe" in got["IN_PORT_OTHER"].message


def test_in_port_free_without_oscquery_means_osc_off():
    got = ids(judge(healthy(ports={}, discovery_vrc=None, rx=RxSummary())))
    assert got["IN_PORT_FREE"].status == NG
    assert "IN_PORT_STALE" not in got


def test_in_port_free_but_oscquery_found_is_stale():
    got = ids(judge(healthy(ports={})))
    assert got["IN_PORT_STALE"].status == WARN
    assert "IN_PORT_FREE" not in got


def test_in_port_unknown_owner():
    got = ids(judge(healthy(ports={9000: PortState(True)})))
    assert got["IN_PORT_UNKNOWN"].status == INFO


def test_in_port_routed():
    ports = {9000: PortState(True, "VRChatOSCRouter.exe", 7), 9500: VRC}
    got = ids(judge(healthy(ports=ports, discovery_vrc=oq(9500))))
    assert got["IN_PORT_ROUTED"].status == INFO
    assert got["IN_PORT_VRC"].label == "ポート 9500"
    assert "設定・起動引数では 9000" in got["OQ_FOUND"].message


def test_out_port_other_only_when_not_bound():
    got = ids(judge(healthy(ports={9000: VRC, 9001: PortState(True, "VRCFaceTracking.exe", 9)}, fixed_bound=False)))
    assert got["OUT_PORT_OTHER"].status == INFO and "VRCFaceTracking.exe" in got["OUT_PORT_OTHER"].message
    got = ids(judge(healthy(ports={9000: VRC, 9001: PortState(True, "osc-doctor.exe", 1)}, fixed_bound=True)))
    assert "OUT_PORT_OTHER" not in got


def test_oscquery_direct_and_not_found_and_unavailable():
    assert ids(judge(healthy(discovery_vrc=oq(via="direct"))))["OQ_FOUND_DIRECT"].status == WARN
    assert ids(judge(healthy(discovery_vrc=None)))["OQ_NOT_FOUND"].status == WARN
    got = ids(judge(healthy(discovery_vrc=None, mdns_ok=False)))
    assert got["OQ_UNAVAILABLE"].status == INFO and "OQ_NOT_FOUND" not in got
    assert "mDNS が使えない" in ids(judge(healthy(discovery_vrc=oq(via="direct"), mdns_ok=False)))["OQ_FOUND_DIRECT"].message


def test_oscquery_no_avatar():
    assert ids(judge(healthy(discovery_vrc=oq(avatar=False))))["OQ_NO_AVATAR"].status == WARN


def test_rx_none_variants():
    got = ids(judge(healthy(rx=RxSummary())))
    assert got["RX_NONE_OQ"].status == NG and "RX_NONE" not in got
    got = ids(judge(healthy(rx=RxSummary(), discovery_vrc=None)))
    assert got["RX_NONE"].status == NG
    got = ids(judge(healthy(rx=RxSummary(), discovery_vrc=oq(via="direct"))))
    assert "RX_NONE_OQ" in got


def test_rx_only_fixed():
    got = ids(judge(healthy(rx=RxSummary(total=5, fixed=5, addresses=2, avatar_params=2))))
    assert got["RX_ONLY_FIXED"].status == WARN
    got = ids(judge(healthy(discovery_vrc=None, rx=RxSummary(total=5, fixed=5, addresses=2, avatar_params=2))))
    assert "RX_ONLY_FIXED" not in got


def test_tracking_not_judged_without_oscquery_reception():
    got = ids(judge(healthy(rx=RxSummary(total=5, fixed=5, addresses=2, avatar_params=2), vr_runtime=True)))
    assert not any(i.startswith("TRACKING_") for i in got)


@pytest.mark.parametrize("vrmode,runtime,expected", [
    (0, True, "TRACKING_DESKTOP"),
    (1, False, "TRACKING_MISSING"),
    (None, True, "TRACKING_MISSING"),
    (None, False, "TRACKING_UNKNOWN"),
])
def test_tracking_missing_variants(vrmode, runtime, expected):
    rx = RxSummary(total=5, oscquery=5, addresses=2, avatar_params=2, vrmode=vrmode)
    got = ids(judge(healthy(rx=rx, vr_runtime=runtime)))
    assert expected in got
    if expected == "TRACKING_MISSING":
        assert checks.TRACKING_SETTING in got[expected].actions[0]


def test_cache_info_and_fix_hint(tmp_path):
    make_cache(tmp_path, users=2, files=3)
    summ = cache.summarize(tmp_path)
    got = ids(judge(healthy(cache=summ)))
    assert "6 件" in got["CACHE_INFO"].message and not got["CACHE_INFO"].actions
    rx = RxSummary(total=5, oscquery=5, addresses=1, avatar_params=0, tracking_oscquery=5)
    got = ids(judge(healthy(cache=summ, rx=rx)))
    assert "--fix-cache" in got["CACHE_INFO"].actions[0]


def test_summary_counts():
    fs = judge(healthy(rx=RxSummary(), ports={9000: PortState(True, "X.exe")}, installer_running=True))
    assert checks.summary(fs) == "NG 2 件、注意 1 件"


# --- collector ----------------------------------------------------------------

def test_collector_tally_and_tracking_ranges():
    c = Collector()
    c.record("oscquery", "/tracking/vrsystem/head/pose", (0.0, 1.5, 0.0, 10.0, -170.0, 0.0))
    c.record("oscquery", "/tracking/vrsystem/head/pose", (0.1, 1.4, -0.2, 12.0, 175.0, 1.0))
    c.record("fixed", "/avatar/parameters/VRMode", (1,))
    c.record("oscquery", "/avatar/parameters/VRMode", (1,))
    c.record("oscquery", "/avatar/change", ("avtr_1234",))
    c.record("fixed", "/avatar/parameters/IsLocal", (True,))
    c.record("fixed", "/avatar/parameters/IsLocal", (False,))
    snap = {s.address: s for s in c.snapshot()}
    head = snap["/tracking/vrsystem/head/pose"]
    assert head.count == 2 and head.types == {"ffffff"}
    assert head.mins[:3] == [0.0, 1.4, -0.2] and head.maxs[4] == 175.0
    assert snap["/avatar/parameters/VRMode"].routes == {"fixed", "oscquery"}
    assert snap["/avatar/parameters/IsLocal"].type_label == "bool"
    assert c.vrmode == 1
    assert not snap["/avatar/change"].mins  # value of avatar change is not kept
    assert "avtr_1234" not in repr(snap["/avatar/change"])
    summ = cli.rx_summary(c.snapshot(), 2.0, c.vrmode)
    assert summ.total == 7 and summ.tracking_oscquery == 2 and summ.tracking_rate == 1.0 and summ.avatar_params == 2


# --- masking & report -----------------------------------------------------------

@pytest.mark.parametrize("raw,leak", [
    ("usr_c1644b5b-3ca4-45b4-97c6-a2a0de70d469", "c1644b5b"),
    ("avtr_12345678-aaaa-bbbb-cccc-000000000000", "12345678-aaaa"),
    ("wrld_abcdef00-1111-2222-3333-444444444444", "abcdef00"),
    (r"C:\Users\たなか\Documents\OscDoctor", "たなか"),
    (r"c:/users/Tana/AppData/LocalLow", "Tana"),
    (r"D:\\USERS\\Bob\\x", "Bob"),
])
def test_mask(raw, leak):
    assert leak not in report.mask(raw)


def test_report_contents_and_masking(tmp_path):
    vrc_dir = tmp_path / "Users" / "たなか"
    make_cache(vrc_dir)
    c = Collector()
    c.record("oscquery", "/tracking/vrsystem/head/pose", (0.0, 1.5, 0.0, 10.0, -170.0, 0.0))
    c.record("fixed", "/avatar/parameters/GestureLeft", (3,))
    facts = healthy(cache=cache.summarize(vrc_dir))
    fs = judge(facts)
    text = report.render_report(fs, facts, c.snapshot(), 10.0, NOW)
    for section in ("■ 結果", "■ 受信したアドレス", "■ トラッキング", "■ ポート", "■ VRChat の OSCQuery", "■ キャッシュ"):
        assert section in text
    assert "/avatar/parameters/GestureLeft" in text and "約 0.1 件/秒" in text
    assert "usr_0000000" not in text and "たなか" not in text
    assert text.rstrip().endswith(report.PROMO)
    path = report.write_report(text, tmp_path / "out", NOW)
    assert path.name == "report-20260930-221530.txt"
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw


def test_finding_lines_align_wide_chars():
    fs = [checks.Finding("A", OK, "VRChat", "x"), checks.Finding("B", INFO, "キャッシュ", "y", ("do it",))]
    lines = report.finding_lines(fs)
    assert report.width(lines[0].split("x")[0]) == report.width(lines[1].split("y")[0])
    assert lines[2].strip() == "→ do it"


# --- cache ------------------------------------------------------------------------

def test_cache_summary_none_and_counts(tmp_path):
    assert cache.summarize(tmp_path) is None
    make_cache(tmp_path, users=2, files=2)
    s = cache.summarize(tmp_path)
    assert (s.users, s.files) == (2, 4) and isinstance(s.newest, datetime)


def test_move_cache_moves_everything(tmp_path):
    make_cache(tmp_path / "vrc", files=3)
    dest = cache.move_cache(tmp_path / "vrc", tmp_path / "backup", NOW)
    assert dest == tmp_path / "backup" / "OSC-20260930-221530"
    assert len(list(dest.glob("usr_*/Avatars/*.json"))) == 3
    assert not (tmp_path / "vrc" / "OSC").exists()
    assert cache.move_cache(tmp_path / "vrc", tmp_path / "backup", NOW) is None


def test_move_cache_failure_leaves_source(tmp_path, monkeypatch):
    make_cache(tmp_path / "vrc")

    def boom(*_a, **_k):
        raise OSError("in use")

    monkeypatch.setattr(cache.shutil, "move", boom)
    with pytest.raises(cache.CacheMoveError):
        cache.move_cache(tmp_path / "vrc", tmp_path / "backup", NOW)
    assert len(list((tmp_path / "vrc" / "OSC").glob("usr_*/Avatars/*.json"))) == 2


# --- psutil implementation (real, on this OS) ----------------------------------------

def test_psutil_reports_owner_of_bound_port():
    import os

    import psutil

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        st = PsutilSystemInfo().udp_port(port)
        assert st.in_use
        if st.owner is not None:  # may be unknown without privileges on some OSes
            assert st.owner == psutil.Process(os.getpid()).name()
    assert not PsutilSystemInfo().udp_port(port).in_use


def test_psutil_process_list_contains_self():
    import os

    assert any(p.pid == os.getpid() for p in PsutilSystemInfo().processes())


# --- CLI arguments ------------------------------------------------------------------------

def test_cli_rejects_out_of_range(capsys):
    assert cli.main(["--seconds", "0"]) == 2
    assert cli.main(["--seconds", "abc"]) == 2
    assert cli.main(["--browse-seconds", "31"]) == 2


def test_cli_version(capsys):
    assert cli.main(["--version"]) == 0
    assert "0.1.0" in capsys.readouterr().out
