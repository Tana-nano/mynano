"""U01-U13 (unitypackage reader) and R01-R07 (reference extraction)."""

import gzip
import io
import os
import tarfile

from up_builders import LIL_SHADER, PNG, g, make_unitypackage, mat, meta, prefab, simple_package
from up_helpers import read
from upkg_precheck import refs
from upkg_precheck.unitypackage import SCRIPT_KEYWORDS, is_unsafe_path


def anomalies(p, code):
    return [a.detail for a in p.anomalies if a.code == code]


def test_u01_normal_package():
    p = read(simple_package())
    assert len(p.entries) == 4 and not p.anomalies
    folder = p.entries[g(1)]
    assert folder.is_folder and folder.pathname == "Assets/Shop"
    png = p.entries[g(4)]
    assert not png.is_folder and png.ext == ".png" and png.size == len(PNG) and len(png.sha256) == 64
    assert not png.textual and not png.starts_yaml
    m = p.entries[g(3)]
    assert m.starts_yaml and m.ext == ".mat"
    assert {r.guid for r in m.refs} == {LIL_SHADER, g(4)}
    assert [r.guid for r in p.entries[g(2)].refs] == [g(3)]


def test_u02_member_order_does_not_matter():
    a = read(simple_package())
    b = read(make_unitypackage([
        (g(1), "Assets/Shop", None, None),
        (g(2), "Assets/Shop/Outfit.prefab", prefab(material_guids=[g(3)]), None),
        (g(3), "Assets/Shop/Outfit.mat", mat(LIL_SHADER, [g(4)]), None),
        (g(4), "Assets/Shop/Body.png", PNG, None),
    ], asset_first=True))
    assert {k: (e.pathname, e.sha256, e.refs) for k, e in a.entries.items()} == \
           {k: (e.pathname, e.sha256, e.refs) for k, e in b.entries.items()}


def test_u03_u12_pathname_first_line_only():
    p = read(make_unitypackage([(g(1), "Assets/A/x.png\n00", PNG, None), (g(2), "Assets/A/y.png\r\n", PNG, None)]))
    assert p.entries[g(1)].pathname == "Assets/A/x.png"
    assert p.entries[g(2)].pathname == "Assets/A/y.png"
    assert not p.anomalies


def test_u04_uppercase_guid_normalized():
    up = "ABCDEF0123456789ABCDEF0123456789"
    p = read(make_unitypackage([(up, "Assets/A/x.png", PNG, meta(up.lower()))]))
    assert list(p.entries) == [up.lower()] and not p.anomalies


def test_u05_not_gzip_empty_truncated():
    assert anomalies(read(b"not a gzip at all"), "P01")
    assert anomalies(read(b""), "P01")
    data = simple_package()
    raw = gzip.decompress(data)
    cut = read(gzip.compress(raw[: len(raw) // 2 + 700]))
    p01 = anomalies(cut, "P01")
    assert p01 and "途中で" in p01[0]
    assert cut.entries  # partial result kept


def test_u06_unsafe_paths():
    for bad in ("/etc/x", "C:\\x", "\\\\srv\\x", "Assets/../x", "Assets\\..\\x"):
        assert is_unsafe_path(bad), bad
        p = read(make_unitypackage([(g(1), bad, PNG, None)]))
        assert anomalies(p, "P02") == [bad]
        assert not anomalies(p, "P14")
    assert not is_unsafe_path("Assets/a..b/x.png")


def test_u07_symlink_member():
    link = tarfile.TarInfo(f"{g(9)}/asset")
    link.type = tarfile.SYMTYPE
    link.linkname = "/etc/passwd"
    p = read(make_unitypackage([(g(1), "Assets/A/x.png", PNG, None)], extra_members=[link]))
    assert anomalies(p, "P03") == [f"{g(9)}/asset"]


def test_u08_structure_anomalies():
    p = read(make_unitypackage(
        [(g(1), "Assets/A/x.png", PNG, meta(g(2))), (g(3), "Library/x.png", PNG, None)],
        extra_members=[("notaguid/pathname", b"Assets/x"), (f"{g(4)}/asset", PNG), (f"{g(5)}/weird", b"x")]))
    p14 = " ".join(anomalies(p, "P14"))
    assert "notaguid" in p14
    assert f"pathname がありません: {g(4)}" in p14
    assert ".meta の guid" in p14
    assert "Library/x.png" in p14
    assert f"{g(5)}/weird" in p14


def test_u09_text_over_limit():
    big = mat(LIL_SHADER) + b"#" * 2048
    p = read(make_unitypackage([(g(1), "Assets/A/big.mat", big, None)]), max_text_bytes=1024)
    e = p.entries[g(1)]
    assert e.too_large and e.starts_yaml and e.refs == [] and e.size == len(big) and len(e.sha256) == 64


def test_u10_nothing_written_to_disk(tmp_path, monkeypatch):
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    read(simple_package())
    assert os.listdir(tmp_path) == []


def test_u11_dot_slash_prefix_dirs_and_icon():
    icon = tarfile.TarInfo("./.icon.png")
    icon.size = 0
    d = tarfile.TarInfo(f"./{g(1)}")
    d.type = tarfile.DIRTYPE
    base = read(simple_package())
    p = read(make_unitypackage([
        (g(1), "Assets/Shop", None, None),
        (g(2), "Assets/Shop/Outfit.prefab", prefab(material_guids=[g(3)]), None),
        (g(3), "Assets/Shop/Outfit.mat", mat(LIL_SHADER, [g(4)]), None),
        (g(4), "Assets/Shop/Body.png", PNG, None),
    ], prefix="./", extra_members=[icon, d]))
    assert not p.anomalies and p.root_files == 1
    assert {k: e.pathname for k, e in p.entries.items()} == {k: e.pathname for k, e in base.entries.items()}


def test_u13_folder_entry():
    p = read(make_unitypackage([(g(1), "Assets/Shop", None, meta(g(1), folder=True))]))
    e = p.entries[g(1)]
    assert e.is_folder and e.size == 0 and p.files() == []


def test_script_keywords_kept_for_cs_only():
    cs = b"using UnityEditor;\n[InitializeOnLoad]\nclass A { void F(){ System.Diagnostics.Process.Start(\"x\"); } }\n"
    p = read(make_unitypackage([(g(1), "Assets/A/A.cs", cs, None), (g(2), "Assets/A/a.txt", cs, None)]))
    assert p.entries[g(1)].keywords == {"InitializeOnLoad", "Process.Start"}
    assert p.entries[g(2)].keywords == frozenset()
    assert set(SCRIPT_KEYWORDS) >= p.entries[g(1)].keywords


# ---------------------------------------------------------------- R01-R07

def test_r01_keyed_ref():
    (r,) = refs.extract_yaml(f"  m_Shader: {{fileID: 4800000, guid: {LIL_SHADER}, type: 3}}")
    assert (r.key, r.file_id, r.guid, r.type) == ("m_Shader", 4800000, LIL_SHADER, 3)


def test_r02_list_item_without_key():
    (r,) = refs.extract_yaml(f"  - {{fileID: 2100000, guid: {g(7)}, type: 2}}")
    assert r.key is None and r.file_id == 2100000


def test_r03_own_guid_line_ignored():
    assert refs.extract_yaml(meta(g(1))) == []


def test_r04_zero_guid_dropped():
    assert refs.extract_yaml("m_Texture: {fileID: 0, guid: 00000000000000000000000000000000, type: 0}") == []


def test_r05_serialized_but_binary():
    p = read(make_unitypackage([(g(1), "Assets/A/a.mat", b"\x00\x01binary mat", None)]))
    e = p.entries[g(1)]
    assert not e.starts_yaml and e.refs == [] and e.ext in refs.SERIALIZED_EXTS


def test_r06_asmdef_guid_refs():
    js = f'{{"name": "A", "references": ["GUID:{g(8)}", "Other.Name"]}}'.encode()
    p = read(make_unitypackage([(g(1), "Assets/A/A.asmdef", js, None), (g(2), "Assets/A/n.json", js, None)]))
    assert [(r.key, r.guid) for r in p.entries[g(1)].refs] == [("asmdef", g(8))]
    assert p.entries[g(2)].refs == []


def test_r07_negative_file_id():
    (r,) = refs.extract_yaml(f"  m_CorrespondingSourceObject: {{fileID: -8679921383154817045, guid: {g(5)}, type: 3}}")
    assert r.file_id == -8679921383154817045


def test_refs_inside_meta_are_extracted():
    m = meta(g(1), [f"  - _MainTex: {{fileID: 2800000, guid: {g(2)}, type: 3}}"])
    p = read(make_unitypackage([(g(1), "Assets/A/s.shader", b"Shader \"x\" {}", m)]))
    assert [r.guid for r in p.entries[g(1)].refs] == [g(2)]
