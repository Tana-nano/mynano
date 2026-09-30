"""A01-A12: zip inputs."""

import zipfile

from up_builders import PNG, g, make_unitypackage, make_zip, own, simple_package
from up_helpers import codes, only
from upkg_precheck import known
from upkg_precheck.archive import Limits, decode_member_name, read_input
from upkg_precheck.checks import GREEN, RED, YELLOW, Options, analyze


def scan(tmp_path, data, name="Outfit.zip", limits=None, **opts):
    p = tmp_path / name
    p.write_bytes(data)
    rec = read_input(p, limits or Limits())
    return rec, analyze([rec], known.load(), Options(**opts))


GOOD = {"Karin.unitypackage": simple_package(), "Manuka.unitypackage": simple_package(),
        "README.txt": b"hello", "利用規約.txt": "規約".encode()}


def test_a01_normal_zip(tmp_path):
    rec, a = scan(tmp_path, make_zip(GOOD))
    assert not {"Z01", "Z02", "Z03", "Z04", "Z05"} & set(codes(a))
    z10 = only(a, "Z10")
    assert z10.severity == GREEN and "unitypackage 2 個 / 説明書 1 / 規約 1 / その他 0" in z10.title
    assert len(rec.packages) == 2 and rec.sha256 and rec.size


def test_a02_no_unitypackage(tmp_path):
    _, a = scan(tmp_path, make_zip({"README.txt": b"x", "license.txt": b"x"}))
    assert only(a, "Z02").severity == YELLOW


def test_a03_no_readme_no_terms(tmp_path):
    _, a = scan(tmp_path, make_zip({"A.unitypackage": simple_package()}))
    assert "Z03" in codes(a) and "Z04" in codes(a)


def test_a04_mixed_case_names(tmp_path):
    _, a = scan(tmp_path, make_zip({"A.unitypackage": simple_package(), "docs/Readme_JP.pdf": b"%PDF",
                                    "VN3License.txt": b"x"}))
    assert "Z03" not in codes(a) and "Z04" not in codes(a)


def test_a05_sjis_names_are_redecoded(tmp_path):
    rec, a = scan(tmp_path, make_zip({"A.unitypackage": simple_package(), "説明書.txt": b"x", "表情/規約.txt": b"x"},
                                     sjis_names=["説明書.txt", "表情/規約.txt"]))
    names = [f.name for f in rec.zip.files]
    assert "説明書.txt" in names and "表情/規約.txt" in names  # 表 has a 0x5C trail byte
    assert "Z03" not in codes(a) and "Z04" not in codes(a)
    assert only(a, "Z05").count == 2


def test_a06_utf8_flag_names(tmp_path):
    _, a = scan(tmp_path, make_zip({"A.unitypackage": simple_package(), "説明書.txt": b"x", "規約.txt": b"x"}))
    assert "Z05" not in codes(a)


def test_decode_ascii_and_garbled():
    info = zipfile.ZipInfo("plain.txt")
    assert decode_member_name(info) == ("plain.txt", "")
    bad = zipfile.ZipInfo("x")
    bad.orig_filename = "ÿÿ"  # cp437 bytes FF FF: not valid cp932
    assert decode_member_name(bad)[1] == "garbled"


def test_a07_nested_zip_depth(tmp_path):
    inner = make_zip({"Inner.unitypackage": simple_package()})
    outer = make_zip({"README.txt": b"x", "kiyaku.txt": b"x", "set/inner.zip": inner})
    rec, a = scan(tmp_path, outer)
    assert [p.name for p in rec.packages] == ["set/inner.zip/Inner.unitypackage"]
    assert "Z02" not in codes(a)
    rec1, a1 = scan(tmp_path, outer, limits=Limits(zip_depth=1))
    assert rec1.packages == [] and "Z02" in codes(a1)


def test_a08_broken_zip(tmp_path):
    _, a = scan(tmp_path, b"PK\3\4 this is not really a zip")
    assert only(a, "Z01").severity == RED


def test_a08_broken_nested_zip(tmp_path):
    _, a = scan(tmp_path, make_zip({"a.zip": b"garbage", "A.unitypackage": simple_package()}))
    assert "a.zip" in only(a, "Z01").examples[0]


def test_a09_read_budget(tmp_path):
    big = make_unitypackage([own(i, f"Assets/S/{i}.bin", bytes(range(256)) * 400) for i in range(1, 40)])
    data = make_zip({"A.unitypackage": simple_package(), "B.unitypackage": big, "C.unitypackage": simple_package()})
    rec, a = scan(tmp_path, data, limits=Limits(max_read_bytes=len(simple_package()) + 2000))
    assert only(a, "Z07").severity == YELLOW
    assert [p.name for p in rec.packages] == ["A.unitypackage", "B.unitypackage"]  # partial result kept


def test_a10_junk_files(tmp_path):
    _, a = scan(tmp_path, make_zip({"A.unitypackage": simple_package(), "__MACOSX/._A": b"x", "img/Thumbs.db": b"x",
                                    "a.blend1": b"x", "README.txt": b"x", "terms.txt": b"x"}))
    assert only(a, "Z09").count == 3


def test_a11_exe_in_zip(tmp_path):
    data = make_zip({"A.unitypackage": simple_package(), "Tool/run.EXE": b"MZ"})
    assert only(scan(tmp_path, data)[1], "Z08").severity == RED
    assert only(scan(tmp_path, data, allow_exe=True)[1], "Z08").severity == YELLOW


def test_a12_encrypted_member(tmp_path):
    rec, a = scan(tmp_path, make_zip({"A.unitypackage": simple_package(), "secret.unitypackage": PNG},
                                     encrypted=["secret.unitypackage"]))
    assert only(a, "Z06").examples == ["secret.unitypackage"]
    assert [p.name for p in rec.packages] == ["A.unitypackage"]


def test_unitypackage_input_has_no_z(tmp_path):
    rec, a = scan(tmp_path, simple_package(), name="A.unitypackage")
    assert rec.kind == "unitypackage" and not [c for c in codes(a) if c.startswith("Z")]
    assert g(1) in rec.packages[0].entries


def test_a12b_unsupported_compression(tmp_path):
    rec, a = scan(tmp_path, make_zip({"A.unitypackage": simple_package(), "Big.unitypackage": simple_package(),
                                      "inner.zip": make_zip({"x.txt": b"x"})}, deflate64=["Big.unitypackage", "inner.zip"]))
    f = only(a, "Z06")
    assert f.examples == ["Big.unitypackage", "inner.zip"] and "Deflate64" in f.advice[0]
    assert [p.name for p in rec.packages] == ["A.unitypackage"] and "Z01" not in codes(a)
