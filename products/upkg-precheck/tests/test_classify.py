"""C01-C09 (reference classification) and K01-K05 (known-asset identification)."""

import json
from importlib import resources

from up_builders import LIL_SHADER, PNG, VRC_CORE_EDITOR, g, make_unitypackage, mat, prefab
from up_helpers import read
from upkg_precheck import classify as cl
from upkg_precheck import known
from upkg_precheck.known import ORDER


def ext(pkgs, name="A"):
    res = cl.classify(pkgs, known.load())
    return {pr.package: pr for pr in res}[name]


def pkg(name, entries):
    return read(make_unitypackage(entries), name)


def test_c01_internal_across_the_same_package_only():
    a = pkg("A", [(g(1), "Assets/A/a.mat", mat(LIL_SHADER, [g(2)]), None), (g(2), "Assets/A/t.png", PNG, None)])
    pr = ext([a])
    assert pr.internal == 1 and g(2) not in pr.external


def test_c02_builtin():
    a = pkg("A", [(g(1), "Assets/A/a.mat", mat("0000000000000000e000000000000000", ["0000000000000000f000000000000000"]), None)])
    pr = ext([a])
    assert pr.builtin == 2 and not pr.external


def test_c03_known_liltoon():
    a = pkg("A", [(g(1), "Assets/A/a.mat", mat(LIL_SHADER), None)])
    x = ext([a]).external[LIL_SHADER]
    assert x.category == cl.KNOWN and x.known_id == "liltoon"


def test_c03b_vrchat_sdk_dll_beats_dll_rule():
    a = pkg("A", [(g(1), "Assets/A/a.prefab", prefab([(-1427037861, VRC_CORE_EDITOR)]), None)])
    x = ext([a]).external[VRC_CORE_EDITOR]
    assert x.category == cl.KNOWN and x.known_id == "vrchat-sdk"


def test_c09_other_package():
    a = pkg("A", [(g(1), "Assets/A/a.mat", mat(LIL_SHADER, [g(2)]), None)])
    b = pkg("B", [(g(2), "Assets/Common/t.png", PNG, None)])
    x = ext([a, b]).external[g(2)]
    assert x.category == cl.OTHER_PACKAGE and x.packages == ["B"] and x.kind == "テクスチャ"


def test_c04_dll_part():
    a = pkg("A", [(g(1), "Assets/A/a.prefab", prefab([(-1234567, g(9))]), None)])
    assert ext([a]).external[g(9)].category == cl.DLL


def test_c05_missing_script():
    a = pkg("A", [(g(1), "Assets/A/a.prefab", prefab([(11500000, g(9))]), None)])
    assert ext([a]).external[g(9)].category == cl.MISSING_SCRIPT


def test_c06_missing_shader():
    a = pkg("A", [(g(1), "Assets/A/a.mat", mat(g(9)), None)])
    assert ext([a]).external[g(9)].category == cl.MISSING_SHADER


def test_c07_missing_other_kind_from_file_id():
    a = pkg("A", [(g(1), "Assets/A/a.prefab", prefab(material_guids=[g(8)]), None),
                  (g(2), "Assets/A/b.mat", mat(LIL_SHADER, [g(9)]), None)])
    pr = ext([a])
    assert (pr.external[g(8)].category, pr.external[g(8)].kind) == (cl.MISSING_OTHER, "マテリアル")
    assert (pr.external[g(9)].category, pr.external[g(9)].kind) == (cl.MISSING_OTHER, "テクスチャ")
    assert cl.kind_of(None, -8679921383154817045) == "プレハブかモデル（FBX）の中身"
    assert cl.kind_of(None, 123) == "アセット"


def test_c08_referrers_are_counted_and_listed():
    entries = [(g(i), f"Assets/A/m{i}.mat", mat(g(99)), None) for i in range(1, 8)]
    x = ext([pkg("A", entries)]).external[g(99)]
    assert x.count == 7 and len(x.referrers) == 7


# ---------------------------------------------------------------- K01-K05

def test_k01_guid_hit():
    m = known.load().identify(LIL_SHADER, "Assets/Shop/whatever.shader")
    assert (m.id, m.exact) == ("liltoon", True)


def test_k02_vrchat_path_prefix():
    m = known.load().identify(g(1), "Packages/com.vrchat.base/x.cs")
    assert (m.id, m.exact) == ("vrchat-sdk", False)


def test_k03_liltoon_path_prefix():
    m = known.load().identify(g(1), "Assets/lilToon/New.shader")
    assert (m.id, m.exact) == ("liltoon", False)
    assert known.load().identify(g(1), "Assets/Shop/New.shader") is None


def test_k04_files_counted_not_folders(tmp_path):
    from up_helpers import run
    a = run(("A", make_unitypackage([
        (g(1), "Assets/Shop", None, None),
        (g(2), "Assets/Shop/Outfit.prefab", prefab(), None),
        (LIL_SHADER, "Assets/Shop/lts.shader", b"Shader \"x\" {}", None),
    ])))
    assert a.matches["A"] == {g(2): None, LIL_SHADER: known.Match("liltoon", True)}


def test_k05_dictionary_contents():
    k = known.load()
    assert set(ORDER) <= set(k.ids)
    for i in ORDER:
        info = k.ids[i]
        assert info.guidance and info.source_url.startswith("https://") and info.get_url.startswith("https://")
        assert info.prefixes and info.draft
    counts = {i: sum(1 for v in k.guids.values() if v == i) for i in ORDER}
    assert counts["vrchat-sdk"] == 6
    assert counts["liltoon"] >= 400 and counts["poiyomi"] >= 1500 and counts["modular-avatar"] >= 400
    assert counts["ndmf"] >= 280 and counts["vrcfury"] >= 700
    # no GUID key appears twice in the raw JSON
    text = resources.files("upkg_precheck").joinpath("data/known_assets.json").read_text(encoding="utf-8")
    known.parse(text)
    assert len(json.loads(text)["guids"]) == len(k.guids)


def test_k05_duplicate_key_is_rejected():
    import pytest
    with pytest.raises(known.DictionaryError):
        known.parse('{"built": "x", "ids": {}, "guids": {"a": ["x", "p"], "a": ["y", "q"]}}')
