"""O01-O04 (outputs) and I01-I11 (command line)."""

import hashlib
import io
import os
import stat
from datetime import datetime

import pytest
from up_builders import LIL_SHADER, MA_CS, g, make_unitypackage, make_zip, mat, own, prefab, simple_package
from up_helpers import inputs, run
from upkg_precheck import VERSION, known
from upkg_precheck.cli import Env, main
from upkg_precheck.draft import render_draft
from upkg_precheck.report import screen_lines

NOW = datetime(2026, 9, 30, 22, 15, 30)


def cli(argv, *, tty=False, environ=None):
    out = io.StringIO()
    asked = []
    env = Env(out=out, now=lambda: NOW, input=lambda s: asked.append(s) or "", isatty=lambda: tty,
              environ=environ or {})
    code = main(argv, env)
    return code, out.getvalue(), asked


def good_zip(tmp_path, name="Outfit_v1.0.zip", **files):
    content = {"Karin.unitypackage": simple_package(), "README.txt": b"x", "利用規約.txt": b"x", **files}
    p = tmp_path / name
    p.write_bytes(make_zip(content))
    return p


def run_dir(root):
    (d,) = list(root.iterdir())
    return d


# ---------------------------------------------------------------- O01-O04

def test_o01_report_has_bom_names_only_and_all_examples(tmp_path):
    src = tmp_path / "secret-user-folder"
    src.mkdir()
    entries = [own(i, f"Assets/Shop/m{i}.mat", mat(g(90 + i))) for i in range(1, 6)]
    z = good_zip(src, **{"A.unitypackage": make_unitypackage(entries)})
    code, _, _ = cli(["--no-pause", "--out", str(tmp_path / "o"), str(z)])
    raw = (run_dir(tmp_path / "o") / "report.txt").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    assert "Outfit_v1.0.zip" in text and "secret-user-folder" not in text and str(tmp_path) not in text
    assert all(g(90 + i) in text for i in range(1, 6))  # every example, not just 3
    assert "辞書 " + known.load().built in text and "SHA-256" in text


def test_o02_draft_order_none_and_urls():
    data = make_unitypackage([own(1, "Assets/S/a.prefab", prefab([(-5, MA_CS)])), own(2, "Assets/S/b.mat", mat(LIL_SHADER))])
    text = render_draft(inputs(("A.unitypackage", data)), run(("A.unitypackage", data)), known.load())
    need = text.split("## 導入に必要なもの")[1].split("##")[0]
    assert need.index("lilToon") < need.index("Modular Avatar")
    assert "https://booth.pm/ja/items/3087170" in need and "https://modular-avatar.nadena.dev/" in need
    assert "NDMF" in need  # written as part of Modular Avatar
    assert not text.startswith("\ufeff")
    plain = make_unitypackage([own(1, "Assets/S/t.png")])
    t2 = render_draft(inputs(("B.unitypackage", plain)), run(("B.unitypackage", plain)), known.load())
    assert t2.count("（検出されませんでした）") == 2


def test_o03_not_bundled_listed():
    data = make_unitypackage([own(1, "Assets/S/b.mat", mat(LIL_SHADER))])
    text = render_draft(inputs(("A.unitypackage", data)), run(("A.unitypackage", data)), known.load())
    assert "- lilToon 本体（上の入手先から導入してください）" in text.split("## 同梱していないもの")[1]


def test_o04_screen_example_limit():
    entries = [own(i, f"Assets/S/m{i}.mat", mat(g(90 + i))) for i in range(1, 6)]
    a = run(("A", make_unitypackage(entries)))
    short = "\n".join(screen_lines(a.findings, verbose=False))
    full = "\n".join(screen_lines(a.findings, verbose=True))
    assert "（ほか 2 件" in short and "（ほか" not in full


# ---------------------------------------------------------------- I01-I11

def test_i01_normal_zip_saves_both(tmp_path):
    z = good_zip(tmp_path)
    code, out, _ = cli(["--no-pause", "--out", str(tmp_path / "o"), str(z)])
    assert code == 0
    d = run_dir(tmp_path / "o")
    assert d.name == "Outfit_v1.0-20260930-221530"
    assert (d / "report.txt").is_file() and (d / "readme-draft.md").is_file()
    assert "結果: 赤 0" in out and "レポート:" in out and "説明書の下書き:" in out
    assert "unitypackage 1 個 / 説明書 1 / 規約 1 / その他 0" in out


def test_i02_red_exit_1(tmp_path):
    z = good_zip(tmp_path, **{"tool.exe": b"MZ"})
    assert cli(["--no-pause", "--no-report", "--no-draft", str(z)])[0] == 1


def test_i03_missing_path(tmp_path):
    code, out, _ = cli(["--no-pause", str(tmp_path / "nope.zip")])
    assert code == 2 and "見つかりません" in out


def test_i04_folder_input_cross_checks(tmp_path):
    folder = tmp_path / "Outfit"
    (folder / "sub").mkdir(parents=True)
    (folder / "A.unitypackage").write_bytes(make_unitypackage([own(1, "Assets/S/t.png", b"v1")]))
    (folder / "sub" / "B.zip").write_bytes(make_zip({"B.unitypackage": make_unitypackage([own(1, "Assets/S/t.png", b"v2")])}))
    (folder / "notes.txt").write_text("x")
    code, out, _ = cli(["--no-pause", "--out", str(tmp_path / "o"), str(folder)])
    assert code == 1 and "X01" in out
    assert "調べています: A.unitypackage" in out and "調べています: sub\\B.zip" in out
    assert run_dir(tmp_path / "o").name.startswith("Outfit-")
    assert str(folder) not in out.split("レポート:")[0]


def test_i04b_same_name_in_subfolders_shown_by_relative_path(tmp_path):
    folder = tmp_path / "素材"
    for sub in ("A", "B"):
        (folder / sub).mkdir(parents=True)
        (folder / sub / "lilToon.unitypackage").write_bytes(make_unitypackage([own(1, f"Assets/{sub}/t.png")]))
    code, out, _ = cli(["--no-pause", "--no-report", "--no-draft", str(folder)])
    assert "調べています: A\\lilToon.unitypackage" in out and "調べています: B\\lilToon.unitypackage" in out
    assert "(2)" not in out


def test_i04e_zip_package_and_folder_file_look_different(tmp_path):
    folder = tmp_path / "素材"
    (folder / "商品").mkdir(parents=True)
    pkg = make_unitypackage([own(1, "Assets/S/t.png")])
    (folder / "商品" / "X.unitypackage").write_bytes(pkg)
    (folder / "商品.zip").write_bytes(make_zip({"商品/X.unitypackage": pkg}))
    code, out, _ = cli(["--no-pause", "--no-report", "--no-draft", str(folder)])
    assert "商品.zip/商品/X.unitypackage だけにあるもの" in out and "商品\\X.unitypackage だけにあるもの" in out


def test_i04c_same_package_name_in_two_zips_prefixed_with_zip(tmp_path):
    for z, sub in (("A.zip", "A"), ("B.zip", "B")):
        (tmp_path / z).write_bytes(make_zip({"Outfit.unitypackage": make_unitypackage([own(1, f"Assets/{sub}/t.png")])}))
    code, out, _ = cli(["--no-pause", "--no-report", "--no-draft", str(tmp_path / "A.zip"), str(tmp_path / "B.zip")])
    assert "A.zip/Outfit.unitypackage だけにあるもの" in out and "B.zip/Outfit.unitypackage だけにあるもの" in out
    assert "(2)" not in out


def test_i04d_same_file_twice_gets_suffix(tmp_path):
    f = tmp_path / "Outfit.unitypackage"
    f.write_bytes(make_unitypackage([own(1, "Assets/S/t.png")]))
    code, out, _ = cli(["--no-pause", "--no-report", "--no-draft", str(f), str(f)])
    assert "Outfit.unitypackage (2) だけにあるもの: 0 個" in out


def test_i05_no_outputs(tmp_path):
    code, _, _ = cli(["--no-pause", "--no-report", "--no-draft", "--out", str(tmp_path / "o"), str(good_zip(tmp_path))])
    assert code == 0 and not (tmp_path / "o").exists()


@pytest.mark.parametrize("opt", [["--max-path", "0"], ["--zip-depth", "9"], ["--max-referrers", "x"]])
def test_i06_out_of_range(tmp_path, opt):
    code, out, _ = cli(["--no-pause", *opt, str(good_zip(tmp_path))])
    assert code == 2 and "指定が正しくありません" in out


def test_i07_version():
    code, out, _ = cli(["--version"])
    assert code == 0 and VERSION in out and known.load().built in out


def test_i08_pause_only_without_options_on_a_tty(tmp_path):
    z = str(good_zip(tmp_path))
    docs = {"UPKG_PRECHECK_DOCS": str(tmp_path / "docs")}
    assert cli([z], tty=True, environ=docs)[2]  # drag & drop
    assert not cli([z], tty=False, environ=docs)[2]
    assert not cli(["--no-pause", z], tty=True, environ=docs)[2]
    assert not cli(["--verbose", z], tty=True, environ=docs)[2]
    assert (tmp_path / "docs" / "UpkgPrecheck").is_dir()  # default location follows UPKG_PRECHECK_DOCS


def test_i09_no_args_shows_usage():
    code, out, asked = cli([], tty=True)
    assert code == 2 and "ドロップ" in out and asked


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="permission bits are not enforced")
def test_i10_unwritable_output(tmp_path):
    ro = tmp_path / "ro"
    ro.mkdir()
    ro.chmod(stat.S_IRUSR | stat.S_IXUSR)
    try:
        code, out, _ = cli(["--no-pause", "--out", str(ro), str(good_zip(tmp_path))])
    finally:
        ro.chmod(stat.S_IRWXU)
    assert code == 2 and "保存できませんでした" in out and "結果:" in out


def test_i10_output_path_is_a_file(tmp_path):
    blocker = tmp_path / "blocker"
    blocker.write_text("x")
    code, out, _ = cli(["--no-pause", "--out", str(blocker), str(good_zip(tmp_path))])
    assert code == 2 and "保存できませんでした" in out and "結果:" in out


def test_i11_input_is_not_modified(tmp_path):
    z = good_zip(tmp_path)
    before = (hashlib.sha256(z.read_bytes()).hexdigest(), z.stat().st_mtime_ns)
    cli(["--no-pause", "--out", str(tmp_path / "o"), str(z)])
    assert (hashlib.sha256(z.read_bytes()).hexdigest(), z.stat().st_mtime_ns) == before


def test_unsupported_file_is_skipped(tmp_path):
    (tmp_path / "a.rar").write_bytes(b"x")
    code, out, _ = cli(["--no-pause", "--no-report", "--no-draft", str(tmp_path / "a.rar"), str(good_zip(tmp_path))])
    assert code == 0 and "対応していない形式" in out


def test_unexpected_error_is_reported(tmp_path, monkeypatch):
    import upkg_precheck.cli as c

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(c, "analyze", boom)
    code, out, _ = cli(["--no-pause", str(good_zip(tmp_path))])
    assert code == 2 and "予期しないエラー" in out and "boom" in out


def test_documents_dir_prefers_known_folder(tmp_path):
    from upkg_precheck.cli import documents_dir
    real = tmp_path / "OneDrive" / "ドキュメント"
    real.mkdir(parents=True)
    assert documents_dir({}, lambda: real) == real
    assert documents_dir({"UPKG_PRECHECK_DOCS": str(tmp_path)}, lambda: real) == tmp_path
    assert documents_dir({}, lambda: tmp_path / "missing") in (__import__("pathlib").Path.home() / "Documents",
                                                             __import__("pathlib").Path.cwd())
