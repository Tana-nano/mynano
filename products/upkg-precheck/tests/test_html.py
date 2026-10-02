"""H01-H06: report.html, the console verdict and colours."""

import io

from up_builders import PNG, g, make_unitypackage, make_zip, mat, own
from up_helpers import inputs, run
from upkg_precheck import known
from upkg_precheck.cli import Env, main
from upkg_precheck.html_report import render_html
from upkg_precheck.report import screen_lines, verdict_line
from test_cli import NOW, good_zip, run_dir

SHOP = "Assets/Shop"


def html_of(*pkgs):
    return render_html(inputs(*pkgs), run(*pkgs), known.load(), NOW, 5)


def test_h01_escapes_names():
    data = make_unitypackage([own(1, f"{SHOP}/<script>x.png", PNG)])
    text = html_of(("A<b>.unitypackage", data))
    assert "<script>" not in text and "&lt;script&gt;x.png" in text and "A&lt;b&gt;.unitypackage" in text


def test_h02_verdict_by_worst_severity():
    red = make_unitypackage([own(1, f"{SHOP}/run.exe", b"MZ")])
    yellow = make_unitypackage([own(1, f"{SHOP}/m.mat", mat(g(90)))])
    green = make_unitypackage([own(1, f"{SHOP}/t.png", PNG)])
    assert 'class="verdict red"' in html_of(("A", red)) and "出品前に直すものがあります" in html_of(("A", red))
    assert 'class="verdict yellow"' in html_of(("A", yellow))
    assert 'class="verdict green"' in html_of(("A", green)) and "問題は見つかりませんでした" in html_of(("A", green))


def test_h03_long_example_lists_fold():
    data = make_unitypackage([own(i, f"{SHOP}/m{i}.mat", mat(g(90 + i))) for i in range(1, 6)])
    text = html_of(("A", data))
    assert "ほか 2 件を表示" in text and all(g(90 + i) in text for i in range(1, 6))


def test_h04_self_contained_and_names_only(tmp_path):
    src = tmp_path / "secret-user-folder"
    src.mkdir()
    z = good_zip(src)
    out = io.StringIO()
    main(["--no-pause", "--out", str(tmp_path / "o"), str(z)], Env(out=out, now=lambda: NOW, environ={}))
    text = (run_dir(tmp_path / "o") / "report.html").read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>") and "Outfit_v1.0.zip" in text
    assert "secret-user-folder" not in text and str(tmp_path) not in text
    assert "<script" not in text and "src=" not in text and "<link" not in text
    assert "結果のページ:" in out.getvalue()


def cli_run(argv, tmp_path, *, tty):
    opened, out = [], io.StringIO()
    env = Env(out=out, now=lambda: NOW, input=lambda s: "", isatty=lambda: tty,
              environ={"UPKG_PRECHECK_DOCS": str(tmp_path / "docs")}, open_file=opened.append)
    main(argv, env)
    return opened, out.getvalue()


def test_h05_opens_page_only_on_drag_and_drop(tmp_path):
    z = good_zip(tmp_path)
    opened, _ = cli_run([str(z)], tmp_path, tty=True)
    assert len(opened) == 1 and opened[0].name == "report.html"
    assert cli_run(["--no-pause", str(z)], tmp_path, tty=True)[0] == []
    assert cli_run([str(z)], tmp_path, tty=False)[0] == []
    assert cli_run(["--no-report", str(z)], tmp_path, tty=True)[0] == []


def test_h05b_open_failure_is_reported_not_fatal(tmp_path):
    def fail(path):
        raise OSError(2, "no browser")
    out = io.StringIO()
    env = Env(out=out, now=lambda: NOW, input=lambda s: "", isatty=lambda: True,
              environ={"UPKG_PRECHECK_DOCS": str(tmp_path / "docs")}, open_file=fail)
    assert main([str(good_zip(tmp_path))], env) == 0
    assert "結果のページを開けませんでした" in out.getvalue()


def test_h06_colours_only_when_asked():
    data = make_unitypackage([own(1, f"{SHOP}/run.exe", b"MZ")])
    a = run(("A", data))
    plain = "\n".join(screen_lines(a.findings, False)) + verdict_line(a.findings)
    coloured = "\n".join(screen_lines(a.findings, False, color=True)) + verdict_line(a.findings, color=True)
    assert "\x1b[" not in plain and "[赤]" in plain and "【出品前に直すものがあります" in plain
    assert "\x1b[1;37;41m[赤]\x1b[0m" in coloured and coloured.count("\x1b[0m") >= 2
    out = io.StringIO()
    main(["--no-pause", "--no-report", "--no-draft", "--version"], Env(out=out, environ={}))
    assert "\x1b[" not in out.getvalue()
