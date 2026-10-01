import io
import json
from pathlib import Path

import pytest

from ud_helpers import FIXTURES, NOW, make_project, rules_data, write_log
import upload_doctor
from upload_doctor import cli, selfcheck


def run(argv, tmp_path, input_text=None, env=None):
    out = io.StringIO()
    env = env if env is not None else {"USERPROFILE": str(tmp_path / "home"), "LOCALAPPDATA": str(tmp_path / "local")}
    feed = (lambda _prompt: input_text) if input_text is not None else (lambda _p: (_ for _ in ()).throw(EOFError()))
    code = cli.main(argv, stdout=out, input_fn=feed, now=NOW, env=env)
    return code, out.getvalue()


def test_healthy_run_saves_masked_report(tmp_path):
    root = make_project(tmp_path / "MyProj")
    log = write_log(tmp_path / "Editor.log", "Starting compilation", project=root)
    code, out = run([str(root), "--editor-log", str(log), "--out", str(tmp_path / "out"), "--no-pause"], tmp_path)
    assert code == 0
    assert "結果: 問題は見つかりませんでした" in out
    report = tmp_path / "out" / "report-20260930-221530.txt"
    raw = report.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    assert "MyProj" not in raw.decode("utf-8-sig")


def test_ng_exit_code_and_default_locations(tmp_path):
    root = make_project(tmp_path / "p", unity="2019.4.31f1")
    local = tmp_path / "local" / "Unity" / "Editor"
    local.mkdir(parents=True)
    write_log(local / "Editor.log", "x", project=root)
    code, out = run([str(root)], tmp_path)
    assert code == 1
    assert "対象プロジェクト: 一致" in out
    assert list((tmp_path / "home" / "Documents" / "UploadDoctor").glob("report-*.txt"))


def test_prompt_for_folder_with_quotes(tmp_path):
    root = make_project(tmp_path / "with space")
    code, out = run(["--no-report"], tmp_path, input_text=f'"{root}"')
    assert code == 0 and "Editor.log: なし" in out


def test_no_folder_given(tmp_path):
    code, out = run(["--no-report"], tmp_path)
    assert code == 2 and "指定されていません" in out


def test_not_a_project_suggests_nearby(tmp_path):
    make_project(tmp_path / "outer" / "RealProj")
    code, out = run([str(tmp_path / "outer"), "--no-report"], tmp_path)
    assert code == 2 and "Unity プロジェクトのフォルダではありません" in out and "RealProj" in out
    code, out = run([str(tmp_path / "missing"), "--no-report"], tmp_path)
    assert code == 2 and "見つかりません" in out


def test_bad_rules(tmp_path):
    bad = tmp_path / "r.json"
    d = rules_data()
    d["log_rules"][0]["level"] = "fatal"
    bad.write_text(json.dumps(d), encoding="utf-8")
    code, out = run([str(make_project(tmp_path / "p")), "--rules", str(bad), "--no-report"], tmp_path)
    assert code == 2 and "規則表が不正です" in out and "log_rules[0].level" in out


def test_bad_argument_and_version(tmp_path, capsys):
    assert run(["--nope"], tmp_path)[0] == 2
    assert run(["--version"], tmp_path)[0] == 0
    assert upload_doctor.VERSION in capsys.readouterr().out


def test_report_save_failure_keeps_exit_code(tmp_path):
    root = make_project(tmp_path / "p")
    blocker = tmp_path / "blocker"
    blocker.write_text("file, not a folder", encoding="utf-8")
    code, out = run([str(root), "--out", str(blocker / "sub")], tmp_path)
    assert code == 0 and "レポートを保存できませんでした" in out


def test_verbose_lists_files(tmp_path):
    code, out = run([str(make_project(tmp_path / "p")), "--verbose", "--no-report"], tmp_path)
    assert "読んだファイル:" in out and "Packages/vpm-manifest.json" in out


def test_keyboard_interrupt(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli.project, "collect", boom)
    code, out = run([str(make_project(tmp_path / "p")), "--no-report"], tmp_path)
    assert code == 2 and "中断しました" in out


@pytest.mark.parametrize(
    "argv, pause",
    [([], True), (["C:\\Proj"], True), (["C:\\Proj", "--no-pause"], False), (["C:\\Proj", "--verbose"], False), (["--self-check"], False)],
)
def test_should_pause(argv, pause):
    assert cli.should_pause(argv) is pause


def test_self_check_runs_and_cleans_up(tmp_path, monkeypatch):
    import tempfile

    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    code, out = run(["--self-check", "--no-pause"], tmp_path)
    assert code == 0 and "自己診断: OK" in out
    assert not list(tmp_path.glob("upload-doctor-*"))


def test_diagnosis_is_read_only(tmp_path):
    root = make_project(tmp_path / "p", assets_dirs=("DynamicBone", "VRCSDK"), settings="x: VRC_SDK_VRCSDK2")
    log = write_log(tmp_path / "Editor.log", (FIXTURES / "editor_log_compile_error.txt").read_text(encoding="utf-8"), project=root)

    def snapshot(base):
        return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in base.rglob("*"))

    before, log_before = snapshot(root), log.stat().st_mtime_ns
    code, _ = run([str(root), "--editor-log", str(log), "--out", str(tmp_path / "out")], tmp_path)
    assert code == 1
    assert snapshot(root) == before and log.stat().st_mtime_ns == log_before
    assert [p.name for p in (tmp_path / "out").iterdir()] == ["report-20260930-221530.txt"]
