from pathlib import Path

from ud_helpers import FIXTURES, NOW, TODAY, bundled_rules, make_project, touch_logged_files
from upload_doctor import checks, editorlog, project, report
from upload_doctor.checks import Finding
from upload_doctor.mask import Masker

UUID = "0123abcd-0000-4000-8000-00000000abcd"


def test_ids_email_and_users():
    m = Masker()
    s = m(f"usr_{UUID} avtr_{UUID} wrld_{UUID} a.b+c@example.co.jp C:\\Users\\たろう\\x D:/Users/Bob/y")
    assert s == "usr_xxxx avtr_xxxx wrld_xxxx <email> %USERPROFILE%\\x %USERPROFILE%/y"
    assert m("c:\\users\\alice\\AppData") == "%USERPROFILE%\\AppData"
    assert m("/home/alice/x") == "~/x"


def test_packagecache_paths_are_not_emails():
    line = "Library/PackageCache/com.unity.ugui@1.0.0/Runtime/UI/Core/Graphic.cs(5,1)"
    assert Masker()(line) == line


def test_project_path_variants_and_order():
    m = Masker(["C:\\Users\\foo\\MyAvatarProj"])
    assert m("C:/Users/foo/MyAvatarProj/Assets/X.cs") == "<PROJECT>/Assets/X.cs"
    assert m("c:\\users\\foo\\myavatarproj\\Assets") == "<PROJECT>\\Assets"
    assert m("C:\\Users\\foo\\MyAvatarProj") == "<PROJECT>"
    assert m("C:\\Users\\foo\\MyAvatarProj2\\x") == "%USERPROFILE%\\MyAvatarProj2\\x"  # not a prefix match
    assert m('"C:/Users/foo/MyAvatarProj"') == '"<PROJECT>"'


def test_mask_leaves_nothing_behind_on_fixtures():
    m = Masker(["C:/Users/FixtureUser/VRC/FixtureAvatar", "C:/Users/FixtureUser/VRC/Fixture Avatar"])
    for p in FIXTURES.glob("*.txt"):
        out = m(p.read_text(encoding="utf-8"))
        for secret in ("FixtureUser", "FixtureAvatar", "Fixture Avatar", "fixture@example.com", "00000000-0000-0000-0000-000000000000"):
            assert secret not in out, (p.name, secret)


def _diagnose(tmp_path, log_name="editor_log_compile_error.txt"):
    rules = bundled_rules()
    root = make_project(tmp_path / "SecretAvatarName", unity="2019.4.31f1", assets_dirs=("DynamicBone",))
    body = (FIXTURES / log_name).read_text(encoding="utf-8").replace("C:/Users/FixtureUser/VRC/FixtureAvatar", str(root))
    log = tmp_path / "Editor.log"
    log.write_text(body, encoding="utf-8")
    touch_logged_files(root, log)
    pf = project.collect(root, rules, {"USERPROFILE": "C:\\Users\\fixture"})
    lf = editorlog.parse(log, rules, pf.root)
    fs = checks.judge(pf, lf, rules, TODAY)
    return fs, pf, lf, rules, Masker([str(root)])


def test_screen_layout(tmp_path):
    fs, pf, lf, rules, m = _diagnose(tmp_path)
    out = report.screen(fs, pf, lf, rules, m, verbose=False)
    lines = out.splitlines()
    assert lines[1] == "プロジェクト: <PROJECT>"
    assert "対象プロジェクト: 一致" in lines[2]
    assert "原因の候補（上ほど可能性が高い順）" in out
    assert " 1. [NG]   確からしさ:高  Assets 内のスクリプト" in out
    assert " 2. [NG]   確からしさ:高  Unity のバージョン" in out
    assert "※ " + checks.LOW_NOTE in out
    assert out.count("根拠: ") == len(checks.candidates(fs)) - sum(1 for f in checks.candidates(fs) if not f.total)
    assert "ほか " in out  # screen shows at most 3 evidence lines
    assert "問題なしの項目: " in out
    assert lines[-1].startswith("結果: NG")
    assert "SecretAvatarName" not in out
    assert "読んだファイル:" not in out
    verbose = report.screen(fs, pf, lf, rules, m, verbose=True)
    assert "読んだファイル:" in verbose and "Editor.log の内訳:" in verbose


def test_report_contents_and_limits(tmp_path):
    fs, pf, lf, rules, m = _diagnose(tmp_path)
    text = report.render_report(fs, pf, lf, rules, m, NOW)
    for section in ("診断レポート", "実行日時: 2026-09-30 22:15:30", "Windows: ", "規則表: 2026-09-30", "Unity: 2019.4.31f1",
                    "== 原因の候補", "== 問題なしの項目 ==", "== パッケージ（Packages/） ==", "com.vrchat.avatars 3.10.1",
                    "== Editor.log の内訳 ==", "== 読んだファイル =="):
        assert section in text, section
    assert text.rstrip("\n").splitlines()[-1] == report.PROMO
    assert "SecretAvatarName" not in text


def test_report_evidence_budget_and_clip():
    long = "x" * 500
    fs = [Finding(f"F{i:02}", "warn", "t", "mid", [long] * 20) for i in range(5)]
    lines = report.candidate_lines(fs, 20, report._Budget(60), clip_lines=True)
    ev = [l for l in lines if l.startswith(report.INDENT + "根拠: x") or l.startswith(report.INDENT + "      x")]
    assert len(ev) == 60
    assert all(len(l.strip().removeprefix("根拠: ")) <= 200 for l in ev)
    assert sum("ほか 20 件" in l for l in lines) == 2  # the last two findings had no budget left


def test_no_candidates_message():
    assert report.candidate_lines([Finding("A", "ok", "fine")], 3) == ["原因の候補は見つかりませんでした"]


def test_output_is_encodable_on_japanese_windows_console(tmp_path):
    """cp932 is the Japanese Windows console code page; everything we print must survive it."""
    fs, pf, lf, rules, m = _diagnose(tmp_path)
    fs += _diagnose(tmp_path / "upload", "editor_log_upload_failed.txt")[0]
    report.screen(fs, pf, lf, rules, m, verbose=True).encode("cp932")
    report.render_report(fs, pf, lf, rules, m, NOW).encode("cp932")
