"""Checks against output captured from a real Unity 2022.3.22f1 (see shared/fixtures/README.md).

The real header stops before project loading (no license in the container), and the compiler
output comes from Unity's bundled Roslyn run directly, so these prove the text shapes, not the
full Editor.log layout on Windows.
"""

from pathlib import Path

from ud_helpers import FIXTURES, TODAY, bundled_rules, ids, make_project
from upload_doctor import checks, editorlog, project

HEAD = FIXTURES / "real_unity_2022.3.22f1_batchmode_unlicensed_head.txt"
CSC = FIXTURES / "real_csc_2022.3.22f1_errors.txt"


def test_real_unity_header_has_no_false_positives():
    f = editorlog.parse(HEAD, bundled_rules(), Path("/work/FixtureAvatar"))
    assert f.lines == 32
    assert f.compile_unique == 0 and not f.rule_hits and not f.unclassified and not f.missing_types
    # Batch mode on Linux does not print the command line before the license check.
    assert f.project_match == "unknown"


def test_real_compiler_output_is_parsed():
    r = bundled_rules()
    f = editorlog.parse(CSC, r, None)
    assert (f.compile["assets"].unique, f.compile["sdk"].unique, f.compile["other"].unique) == (3, 1, 0)
    assert f.compile["assets"].samples[0].startswith("Assets/Fixture Folder (1)/Menu.cs(1,7) error CS0246:")
    assert f.missing_types == ["nadena", "VRC", "Cinemachine", "DynamicBone"]
    # A missing root namespace is reported by its first segment only ('nadena', not 'nadena.dev...').
    assert "Modular Avatar" in r.hint_for("nadena").hint
    assert all(r.hint_for(n) for n in f.missing_types)


def test_real_compiler_output_drives_findings(tmp_path):
    rules = bundled_rules()
    pf = project.collect(make_project(tmp_path / "p"), rules, {"USERPROFILE": "C:\\Users\\fixture"})
    fs = ids(checks.judge(pf, editorlog.parse(CSC, rules, pf.root), rules, TODAY))
    assert (fs["L_COMPILE_ASSETS"].level, fs["L_COMPILE_ASSETS"].confidence) == ("ng", "high")
    assert fs["L_COMPILE_SDK"].level == "ng"
    assert fs["L_MISSING_TYPE"].total == 4
