from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from ud_helpers import FIXTURES, TODAY, bundled_rules, ids, make_project, touch_logged_files, write_log
from upload_doctor import checks, editorlog, project
from upload_doctor.checks import INFO, NG, OK, WARN, Finding, judge

ENV = {"USERPROFILE": "C:\\Users\\fixture"}


def run(root, log=None, today=TODAY, rules=None, **kw):
    rules = rules or bundled_rules()
    pf = project.collect(root, rules, ENV, **kw)
    lf = editorlog.parse(log, rules, pf.root) if log is not None else None
    return judge(pf, lf, rules, today)


def fixture_for(root, name, tmp_path):
    """A fixture log whose -projectpath points at `root` (the fixtures name a made-up project)."""
    body = (FIXTURES / name).read_text(encoding="utf-8")
    for fake in ('"C:/Users/FixtureUser/VRC/Fixture Avatar"', "C:/Users/FixtureUser/VRC/FixtureAvatar"):
        body = body.replace(fake, str(root))
    out = tmp_path / name
    out.write_text(body, encoding="utf-8")
    return touch_logged_files(root, out)


def lvl(findings, fid):
    f = ids(findings)[fid]
    return f.level, f.confidence


def test_healthy_project_has_no_candidates(tmp_path):
    root = make_project(tmp_path / "p")
    fs = run(root, write_log(tmp_path / "l.log", "Starting compilation", project=root))
    assert checks.candidates(fs) == []
    assert {f.id for f in fs} == {"P_UNITY_VERSION", "P_VPM_OK", "P_SDK_FOUND", "L_NO_COMPILE_ERRORS"}
    assert checks.exit_code(fs) == 0
    assert "問題は見つかりませんでした" in checks.summary(fs)


@pytest.mark.parametrize(
    "unity, expect",
    [
        ("2022.3.22f1", (OK, None)),
        ("2022.3.20f1", (WARN, "mid")),
        ("2019.4.31f1", (NG, "high")),
        ("6000.0.23f1", (NG, "high")),
    ],
)
def test_unity_version(tmp_path, unity, expect):
    assert lvl(run(make_project(tmp_path / "p", unity=unity)), "P_UNITY_VERSION") == expect


def test_unity_unreadable(tmp_path):
    fs = ids(run(make_project(tmp_path / "p", unity=None)))
    assert fs["P_UNITY_UNREADABLE"].level == INFO and "P_UNITY_VERSION" not in fs


def test_vpm_findings(tmp_path):
    assert lvl(run(make_project(tmp_path / "b", vpm_manifest="{")), "P_VPM_BROKEN") == (NG, "mid")
    assert ids(run(make_project(tmp_path / "n", vpm_manifest=None)))["P_VPM_NO_MANIFEST"].level == INFO

    missing_sdk = {"locked": {"com.vrchat.avatars": {"version": "3.10.1"}, "com.vrchat.base": {"version": "3.10.1"}}}
    fs = ids(run(make_project(tmp_path / "m", packages={"com.vrchat.base": "3.10.1"}, vpm_manifest=missing_sdk)))
    assert (fs["P_VPM_MISSING_PACKAGE"].level, fs["P_VPM_MISSING_PACKAGE"].confidence) == (NG, "mid")
    assert "P_NO_SDK" not in fs

    other = {"locked": {"com.vrchat.base": {"version": "3.10.1"}, "com.foo": {"version": "1.0.0"}}}
    fs = ids(run(make_project(tmp_path / "o", packages={"com.vrchat.base": "3.10.1"}, vpm_manifest=other)))
    assert fs["P_VPM_MISSING_PACKAGE"].level == WARN

    drift = {"locked": {"com.vrchat.base": {"version": "3.10.2"}}}
    fs = ids(run(make_project(tmp_path / "d", packages={"com.vrchat.base": "3.10.1"}, vpm_manifest=drift)))
    assert (fs["P_VPM_VERSION_DRIFT"].level, fs["P_VPM_VERSION_DRIFT"].confidence) == (WARN, "low")
    assert "P_VPM_OK" not in fs

    deps_only = {"dependencies": {"com.vrchat.base": {"version": "3.9.0"}}}
    fs = ids(run(make_project(tmp_path / "x", packages={"com.vrchat.base": "3.10.1"}, vpm_manifest=deps_only)))
    assert "P_VPM_VERSION_DRIFT" not in fs and "P_VPM_OK" in fs


def test_upm_broken(tmp_path):
    assert lvl(run(make_project(tmp_path / "p", upm_manifest="{")), "P_UPM_BROKEN") == (NG, "mid")


def test_dependencies(tmp_path):
    pk = {
        "com.vrchat.base": "3.2.0",
        "com.vrchat.avatars": ("3.2.0", {"com.vrchat.base": "3.1.x"}),
        "com.foo": ("1.0.0", {"com.bar": "1.0.0", "com.vrchat.base": "^3.0.0"}),
        "com.ok": ("1.0.0", {"com.vrchat.base": ">=3.1.0"}),
        "com.anatawa12.avatar-optimizer": ("1.9.19", {"com.vrchat.avatars": ">=3.7.0 <3.11.0"}),
    }
    f = ids(run(make_project(tmp_path / "p", packages=pk)))["P_VPM_DEP_UNSATISFIED"]
    assert (f.level, f.confidence) == (WARN, "mid")
    assert f.evidence == [
        "com.anatawa12.avatar-optimizer は com.vrchat.avatars >=3.7.0 <3.11.0 が必要ですが、3.2.0 です",
        "com.foo は com.bar 1.0.0 が必要ですが、入っていません",
        "com.vrchat.avatars は com.vrchat.base 3.1.x が必要ですが、3.2.0 です",
    ]


def test_sdk_presence_and_duplicate(tmp_path):
    fs = ids(run(make_project(tmp_path / "none", packages={}, vpm_manifest=None)))
    assert (fs["P_NO_SDK"].level, fs["P_NO_SDK"].confidence) == (NG, "high")
    fs = ids(run(make_project(tmp_path / "legacy", packages={}, vpm_manifest=None, assets_dirs=("VRCSDK",))))
    assert "P_NO_SDK" not in fs and "P_SDK_DUPLICATE" not in fs
    fs = ids(run(make_project(tmp_path / "dup", assets_dirs=("VRCSDK",))))
    assert lvl(list(fs.values()), "P_SDK_DUPLICATE") == (WARN, "mid")


def test_define_symbols(tmp_path):
    s2 = "scriptingDefineSymbols:\n  1: VRC_SDK_VRCSDK2\n"
    assert lvl(run(make_project(tmp_path / "a", settings=s2)), "P_DEFINE_SYMBOLS") == (WARN, "mid")
    fs = ids(run(make_project(tmp_path / "b", settings=s2, packages={"com.vrchat.base": "3.10.1"})))
    assert "P_DEFINE_SYMBOLS" not in fs
    fs = ids(run(make_project(tmp_path / "c", settings=b"\x00bin")))
    assert fs["P_SETTINGS_UNREADABLE"].level == INFO


@pytest.mark.parametrize("version, fires", [("3.8.9", True), ("3.9.0", False), ("3.10.1", False)])
def test_sdk_old(tmp_path, version, fires):
    fs = ids(run(make_project(tmp_path / "p", packages={"com.vrchat.base": version, "com.vrchat.avatars": version})))
    assert ("P_SDK_OLD" in fs) is fires
    if fires:
        assert (fs["P_SDK_OLD"].level, fs["P_SDK_OLD"].confidence) == (WARN, "low")


def test_folder_and_path_findings(tmp_path):
    fs = ids(run(make_project(tmp_path / "p", assets_dirs=("DynamicBone",))))
    assert (fs["P_DYNAMIC_BONE"].level, fs["P_DYNAMIC_BONE"].confidence) == (INFO, "low")
    fs = ids(run(make_project(tmp_path / "日本語")))
    assert (fs["P_PATH_NON_ASCII"].level, fs["P_PATH_NON_ASCII"].confidence) == (INFO, "low")
    fs = ids(run(make_project(tmp_path / "s", assets_dirs=tuple(f"d{i}" for i in range(5))), scan_limit=2))
    assert fs["P_SCAN_TRUNCATED"].level == INFO


def test_long_path_boundary(tmp_path):
    base = str(tmp_path)
    for length, fires in ((120, False), (121, True)):
        name = "x" * (length - len(base) - 1)
        fs = ids(run(make_project(Path(base) / name)))
        assert ("P_PATH_LONG" in fs) is fires


def test_log_findings_from_compile_fixture(tmp_path):
    root = make_project(tmp_path / "p")
    fs = ids(run(root, fixture_for(root, "editor_log_compile_error.txt", tmp_path)))
    assert (fs["L_COMPILE_ASSETS"].level, fs["L_COMPILE_ASSETS"].confidence) == (NG, "high")
    assert "3 件、延べ 6 回" in fs["L_COMPILE_ASSETS"].title and fs["L_COMPILE_ASSETS"].total == 3
    assert (fs["L_COMPILE_SDK"].level, fs["L_COMPILE_SDK"].confidence) == (NG, "mid")
    assert fs["L_COMPILE_OTHER"].level == WARN and "Library" in fs["L_COMPILE_OTHER"].advice[0]
    mt = fs["L_MISSING_TYPE"]
    assert mt.evidence[0].startswith("'DynamicBone' → Dynamic Bone") and "（確からしさ:低）" in mt.evidence[0]
    assert fs["L_UNCLASSIFIED"].level == INFO
    assert "L_NO_COMPILE_ERRORS" not in fs and "L_OTHER_PROJECT" not in fs
    assert all(checks.LOG_NOTE in fs[k].notes for k in ("L_COMPILE_ASSETS", "L_MISSING_TYPE", "L_UNCLASSIFIED"))


def test_upload_messages(tmp_path):
    root = make_project(tmp_path / "p")
    fs = ids(run(root, fixture_for(root, "editor_log_upload_failed.txt", tmp_path)))
    bp = fs["L_UPLOAD_MSGS/upload.blueprint_not_owned"]
    assert (bp.level, bp.confidence) == (WARN, "mid") and "Detach" in bp.advice[0] and "Attach" in bp.advice[0]
    assert fs["L_UPLOAD_MSGS/upload.build_failed"].confidence == "low"


def test_other_project_downgrades_log_findings(tmp_path):
    root = make_project(tmp_path / "p")
    fs = ids(run(root, FIXTURES / "editor_log_compile_error.txt"))  # log names a different project
    assert (fs["L_OTHER_PROJECT"].level, fs["L_OTHER_PROJECT"].confidence) == (WARN, "high")
    for k in ("L_COMPILE_ASSETS", "L_COMPILE_SDK", "L_MISSING_TYPE"):
        assert fs[k].confidence == "low" and checks.OTHER_PROJECT_NOTE in fs[k].notes
        assert checks.LOW_NOTE not in fs[k].notes
    assert fs["P_UNITY_VERSION"].confidence is None  # OK, project findings untouched


def test_unknown_project_keeps_confidence(tmp_path):
    root = make_project(tmp_path / "p")
    fs = ids(run(root, touch_logged_files(root, write_log(tmp_path / "l.log", ["Assets/A.cs(1,1): error CS0103: x"]))))
    assert fs["L_COMPILE_ASSETS"].confidence == "high"


def test_log_missing_keeps_project_checks(tmp_path):
    fs = ids(run(make_project(tmp_path / "p", unity="2019.4.31f1"), tmp_path / "none.log"))
    assert fs["L_NOT_FOUND"].level == INFO and fs["P_UNITY_VERSION"].level == NG


def test_old_log_and_stale_rules(tmp_path):
    root = make_project(tmp_path / "p")
    log = write_log(tmp_path / "l.log", "x", project=root)
    mtime = datetime(2026, 9, 30, 12).timestamp()
    import os

    os.utime(log, (mtime, mtime))
    assert "L_OLD_LOG" in ids(run(root, log, today=date(2026, 10, 8)))
    assert "L_OLD_LOG" not in ids(run(root, log, today=date(2026, 10, 6)))
    rules = bundled_rules()
    assert "R_STALE" not in ids(run(root, today=rules.checked_on + timedelta(days=89)))
    assert "R_STALE" not in ids(run(root, today=rules.checked_on + timedelta(days=90)))
    assert ids(run(root, today=rules.checked_on + timedelta(days=91)))["R_STALE"].level == INFO


def test_low_note_always_on_low_candidates(tmp_path):
    fs = run(make_project(tmp_path / "日本語", assets_dirs=("DynamicBone",), packages={"com.vrchat.base": "3.8.0", "com.vrchat.avatars": "3.8.0"}))
    lows = [f for f in checks.candidates(fs) if f.confidence == "low"]
    assert lows and all(checks.LOW_NOTE in f.notes for f in lows)
    assert all(checks.LOW_NOTE not in f.notes for f in checks.candidates(fs) if f.confidence in ("high", "mid"))


def test_overrides(tmp_path):
    from dataclasses import replace

    rules = replace(bundled_rules(), overrides={"P_DYNAMIC_BONE": {"level": "warn"}, "L_UPLOAD_MSGS": {"confidence": "high"}})
    root = make_project(tmp_path / "p", assets_dirs=("DynamicBone",))
    fs = ids(run(root, fixture_for(root, "editor_log_upload_failed.txt", tmp_path), rules=rules))
    assert fs["P_DYNAMIC_BONE"].level == WARN
    assert fs["L_UPLOAD_MSGS/upload.build_failed"].confidence == "high"


def test_sort_order_is_total_and_stable():
    fs = [
        Finding("B", INFO, "b"),
        Finding("Z", NG, "z", "low", ["1"]),
        Finding("Y", NG, "y", "high", ["1"]),
        Finding("X", NG, "x", "high", ["1", "2"]),
        Finding("W", NG, "w", "high", ["1", "2"]),
        Finding("V", WARN, "v", "high"),
        Finding("U", NG, "u", "mid"),
    ]
    order = [f.id for f in sorted(fs, key=checks.sort_key)]
    assert order == ["W", "X", "Y", "U", "Z", "V", "B"]
    assert [f.id for f in sorted(reversed(fs), key=checks.sort_key)] == order


def test_summary_and_exit_code():
    assert checks.summary([Finding("A", NG, "a"), Finding("B", WARN, "b"), Finding("C", WARN, "c")]) == "結果: NG 1 件、注意 2 件"
    assert checks.summary([Finding("B", WARN, "b")]) == "結果: 注意 1 件"
    assert checks.exit_code([Finding("B", WARN, "b")]) == 0
    assert checks.exit_code([Finding("A", NG, "a")]) == 1


def test_real_range_sdk_too_new(tmp_path):
    pk = {
        "com.vrchat.base": "3.11.0",
        "com.vrchat.avatars": "3.11.0",
        "com.anatawa12.avatar-optimizer": ("1.9.19", {"com.vrchat.avatars": ">=3.7.0 <3.11.0"}),
    }
    f = ids(run(make_project(tmp_path / "p", packages=pk)))["P_VPM_DEP_UNSATISFIED"]
    assert f.evidence == ["com.anatawa12.avatar-optimizer は com.vrchat.avatars >=3.7.0 <3.11.0 が必要ですが、3.11.0 です"]
