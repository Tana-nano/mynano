"""Regressions for what the first hands-on Windows test turned up (docs/spec.md, 実機試験 2026-10-01)."""

import io
from datetime import datetime
from pathlib import Path

import pytest

from ud_helpers import FIXTURES, TODAY, bundled_rules, ids, make_project, write_log
from upload_doctor import checks, cli, editorlog, project, report
from upload_doctor.versions import satisfies

WIN_EXCERPT = FIXTURES / "real_editor_log_win_2022.3.22f1_excerpt.txt"
WIN_UPLOAD = FIXTURES / "real_editor_log_win_upload_lines.txt"
ENV = {"USERPROFILE": "C:\\Users\\fixture"}


def judge(root, log):
    rules = bundled_rules()
    pf = project.collect(root, rules, ENV)
    return ids(checks.judge(pf, editorlog.parse(log, rules, pf.root), rules, TODAY))


def test_import_records_are_not_errors():
    f = editorlog.parse(WIN_EXCERPT, bundled_rules(), None)
    assert f.unclassified == {}
    assert f.compile["assets"].unique == 1 and f.compile["assets"].total == 3
    assert f.compile["assets"].files == ["Assets\\UDTestBroken\\Broken.cs"]


def test_real_upload_lines_keep_real_errors():
    f = editorlog.parse(WIN_UPLOAD, bundled_rules(), None)
    assert f.rule_hits["upload.blueprint_not_owned"].count == 1
    assert f.rule_hits["upload.contentinfo_nre"].count >= 1
    assert {"IOException", "SocketException", "SetException", "TrySetException", "LogError"} <= set(f.unclassified)
    assert "VRCApiError" not in f.unclassified and "UnityWebRequestException" not in f.unclassified


@pytest.mark.parametrize(
    "line, kind",
    [
        ("System.IO.IOException: Sharing violation", "IOException"),
        ("Packages/a/Editor/IError.cs is fine", None),
        ("Assets\\X\\BarException.cs touched", None),
    ],
)
def test_unclassified_ignores_file_names(tmp_path, line, kind):
    f = editorlog.parse(write_log(tmp_path / "l.log", [line]), bundled_rules(), None)
    assert (list(f.unclassified) or [None])[0] == kind


def test_windows_gui_log_names_the_japanese_project(tmp_path):
    root = tmp_path / "UDTest" / "日本語フォルダ" / "UDテスト"
    body = WIN_EXCERPT.read_text(encoding="utf-8").replace("C:\\UDTest\\日本語フォルダ\\UDテスト", str(root))
    log = tmp_path / "Editor.log"
    log.write_text(body, encoding="utf-8")
    make_project(root)
    assert editorlog.parse(log, bundled_rules(), root).project_match == "match"


@pytest.mark.parametrize(
    "version, spec, ok",
    [
        ("3.10.4", ">=3.5.2 < 3.9.X", False),  # Gesture Manager 3.9.4 as found in a real project
        ("3.8.1", ">=3.5.2 < 3.9.X", True),
        ("3.9.0", "<=3.9.x", True),
        ("3.10.0", "<=3.9.x", False),
        ("3.10.0", ">3.9.x", True),
        ("3.9.9", ">3.9.x", False),
        ("3.9.9", "=3.9.x", True),
        ("3.10.0", "=3.9.x", False),
        ("1.2.0", "^1.0.0", None),
        ("1.2.0", ">=1.0.x-beta", None),
    ],
)
def test_wildcard_comparators(version, spec, ok):
    assert satisfies(version, spec) is ok


def test_dependency_condition_unmet_and_unknown(tmp_path):
    root = make_project(
        tmp_path / "p",
        packages={
            "com.vrchat.base": "3.10.4",
            "com.vrchat.avatars": "3.10.4",
            "vrchat.blackstartx.gesture-manager": ("3.9.4", {"com.vrchat.avatars": ">=3.5.2 < 3.9.X"}),
            "x.odd": ("1.0.0", {"com.vrchat.base": "^3.0.0"}),
        },
    )
    fs = judge(root, tmp_path / "none.log")
    f = fs["P_VPM_DEP_UNSATISFIED"]
    assert (f.level, f.confidence) == (checks.WARN, "mid") and "条件が合っていません" in f.title
    assert f.evidence == ["vrchat.blackstartx.gesture-manager は com.vrchat.avatars >=3.5.2 < 3.9.X が必要ですが、3.10.4 です"]
    u = fs["P_VPM_DEP_UNKNOWN"]
    assert u.level == checks.INFO and u.evidence == ["x.odd → com.vrchat.base ^3.0.0（入っているのは 3.10.4）"]


def test_compile_error_for_deleted_file_is_lowered(tmp_path):
    root = make_project(tmp_path / "p")
    log = write_log(tmp_path / "l.log", ["Assets\\Gone\\Broken.cs(5,28): error CS0029: x"], project=root)
    f = judge(root, log)["L_COMPILE_ASSETS"]
    assert f.confidence == "low" and checks.GONE_NOTE in f.notes and checks.LOW_NOTE not in f.notes
    assert f.evidence[0].endswith(checks.GONE_MARK)


def test_compile_error_partly_deleted_keeps_confidence(tmp_path):
    root = make_project(tmp_path / "p")
    (root / "Assets" / "Here.cs").touch()
    log = write_log(tmp_path / "l.log", ["Assets/Here.cs(1,1): error CS0103: x", "Assets/Gone.cs(1,1): error CS0103: y"], project=root)
    f = judge(root, log)["L_COMPILE_ASSETS"]
    assert f.confidence == "high" and checks.GONE_NOTE not in f.notes
    assert [e.endswith(checks.GONE_MARK) for e in f.evidence] == [False, True]


def test_unity_open_notice(tmp_path):
    root = make_project(tmp_path / "p")
    assert "P_UNITY_OPEN" not in judge(root, tmp_path / "none.log")
    (root / "Temp").mkdir()
    (root / "Temp" / "UnityLockfile").touch()
    f = judge(root, tmp_path / "none.log")["P_UNITY_OPEN"]
    assert f.level == checks.INFO and "途中" in f.advice[0]


def test_non_ascii_path_is_information_only(tmp_path):
    f = judge(make_project(tmp_path / "日本語フォルダ"), tmp_path / "none.log")["P_PATH_NON_ASCII"]
    assert (f.level, f.confidence) == (checks.INFO, "low")


@pytest.mark.parametrize(
    "release, version, label",
    [
        ("10", "10.0.26200", "Windows 11 (10.0.26200)"),
        ("10", "10.0.22000", "Windows 11 (10.0.22000)"),
        ("10", "10.0.19045", "Windows 10 (10.0.19045)"),
        ("11", "10.0.26100", "Windows 11 (10.0.26100)"),
    ],
)
def test_os_label(release, version, label):
    assert report.os_label("Windows", release, version) == label


def test_report_time_is_taken_after_the_prompt(tmp_path, monkeypatch):
    root = make_project(tmp_path / "p")
    clock = {"t": datetime(2026, 10, 1, 9, 42, 11)}

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return clock["t"]

    def answer(_prompt):
        clock["t"] = datetime(2026, 10, 1, 9, 57, 3)  # the folder is dropped 15 minutes after launch
        return str(root)

    monkeypatch.setattr(cli, "datetime", FakeDatetime)
    env = {"USERPROFILE": str(tmp_path / "home"), "LOCALAPPDATA": str(tmp_path / "local")}
    cli.main(["--out", str(tmp_path / "out")], stdout=io.StringIO(), input_fn=answer, env=env)
    (rep,) = (tmp_path / "out").glob("report-*.txt")
    assert rep.name == "report-20261001-095703.txt"
    assert "実行日時: 2026-10-01 09:57:03" in rep.read_text(encoding="utf-8-sig")


# --- 0.1.1 retest (2026-10-01) ---------------------------------------------------------

CS2001 = FIXTURES / "real_editor_log_win_cs2001.txt"
OTHER = "C:\\UDTest\\日本語フォルダ\\UDテスト"


def test_cs2001_is_a_missing_source_not_unclassified():
    f = editorlog.parse(CS2001, bundled_rules(), None)
    assert f.unclassified == {} and f.compile_unique == 0
    assert f.missing_sources == [OTHER + "\\Assets/UDTestBroken/Broken.cs"]


def test_missing_source_finding(tmp_path):
    root = make_project(tmp_path / "p")
    log = write_log(tmp_path / "l.log", CS2001.read_text(encoding="utf-8"), project=root)
    f = judge(root, log)["L_SOURCE_GONE"]
    assert f.level == checks.INFO and f.log_derived and "Library" in f.advice[1]
    assert "L_UNCLASSIFIED" not in judge(root, log)


def test_other_project_lowers_every_log_derived_candidate(tmp_path):
    root = make_project(tmp_path / "p")
    log = write_log(tmp_path / "l.log", CS2001.read_text(encoding="utf-8") + "NullReferenceException: x\n", project=Path(OTHER))
    fs = judge(root, log)
    for k in ("L_SOURCE_GONE", "L_UNCLASSIFIED"):
        assert fs[k].confidence == "low" and checks.OTHER_PROJECT_NOTE in fs[k].notes
    assert fs["L_OTHER_PROJECT"].confidence == "high"


def test_other_project_path_is_masked_on_screen(tmp_path):
    root = make_project(tmp_path / "kip")
    log = write_log(tmp_path / "Editor.log", CS2001.read_text(encoding="utf-8"), project=Path(OTHER))
    out = io.StringIO()
    cli.main([str(root), "--editor-log", str(log), "--no-report", "--verbose"], stdout=out, input_fn=lambda _p: "", env={})
    text = out.getvalue()
    assert "対象プロジェクト: 不一致" in text
    assert "UDテスト" not in text and "<OTHER_PROJECT>\\Assets/UDTestBroken/Broken.cs" in text


def test_masker_keeps_target_token_on_identical_paths():
    from upload_doctor.mask import Masker

    m = Masker(["C:/A/Proj"], ["c:\\a\\proj", "C:/A/Other"])
    assert m("C:\\A\\Proj\\x C:/A/Other/y") == "<PROJECT>\\x <OTHER_PROJECT>/y"
