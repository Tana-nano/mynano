"""T-* : every check code fires where it should and stays quiet where it should not."""

from up_builders import (LIL_CS, LIL_CS2, LIL_SHADER, MA_CS, NDMF_CS, PNG, VRC_PHYSBONE, VRCFURY_CS, g, make_unitypackage,
                      mat, own, prefab)
from up_helpers import codes, only, read, run
from upkg_precheck import known
from upkg_precheck.archive import InputRecord
from upkg_precheck.checks import GREEN, RED, YELLOW, analyze, exit_code

CS = b"public class A {}\n"
SHOP = "Assets/Shop/Outfit"


def base(*extra):
    return make_unitypackage([own(1, f"{SHOP}/Outfit.prefab", prefab(material_guids=[g(2)])),
                              own(2, f"{SHOP}/Outfit.mat", mat(LIL_SHADER, [g(3)])),
                              own(3, f"{SHOP}/Body.png"), *extra])


def test_clean_package_has_no_red_or_yellow():
    a = run(("A.unitypackage", base()))
    assert {f.severity for f in a.findings} == {GREEN}
    assert codes(a) == ["P19", "P21"]
    assert only(a, "P19").title == "購入者に必要なもの: lilToon"


def test_p04_mixed_liltoon():
    a = run(("A", base((LIL_SHADER, "Assets/lilToon/Shader/lts.shader", b"Shader{}", None),
                       (LIL_CS, "Assets/lilToon/Editor/GifParser/GifFile.cs", CS, None),
                       (LIL_CS2, "Assets/lilToon/Editor/GifParser/GifFrameComposer.cs", CS, None))))
    f = only(a, "P04")
    assert f.severity == RED and f.count == 3 and "lilToon" in f.title
    assert any("非推奨" in s for s in f.advice)
    assert "P09" not in codes(a)  # T-P09k: distributor files are not counted as scripts
    assert exit_code(a.findings) == 1


def test_p04n_reference_only():
    a = run(("A", base()))
    assert "P04" not in codes(a) and "lilToon" in only(a, "P19").title


def test_p22_prefix_only_is_yellow_not_red():
    a = run(("A", base(own(9, "Assets/_PoiyomiShaders/OptimizedShaders/x.shader", b"Shader{}"))))
    f = only(a, "P22")
    assert f.severity == YELLOW and "Poiyomi" in f.title
    assert "P04" not in codes(a)


def test_p09k_prefix_only_script_counts():
    a = run(("A", base(own(9, "Assets/lilToon/Editor/New.cs", CS))))
    assert only(a, "P09").count == 1


def test_p08k_exe_under_known_prefix_is_red():
    a = run(("A", base(own(9, "Assets/lilToon/tool.exe", b"MZ"))))
    assert only(a, "P08").severity == RED


def test_p05_vrcfury_only():
    a = run(("F", make_unitypackage([(VRCFURY_CS, "Packages/com.vrcfury.vrcfury/Editor/x.cs", CS, None)])))
    f = only(a, "P05")
    assert f.severity == RED and "VRCFury" in f.title and "P04" not in codes(a)


def test_p05_vrchat_sdk_only_by_prefix():
    a = run(("S", make_unitypackage([own(9, "Packages/com.vrchat.base/Runtime/x.dll", b"MZ\0")])))
    assert only(a, "P05").severity == RED


def test_p06_modular_avatar_only_includes_ndmf():
    a = run(("M", make_unitypackage([(MA_CS, "Packages/nadena.dev.modular-avatar/Editor/x.cs", CS, None),
                                     (NDMF_CS, "Packages/nadena.dev.ndmf/Editor/y.cs", CS, None)])))
    fs = [f for f in a.findings if f.code == "P06"]
    assert [f.severity for f in fs] == [YELLOW, YELLOW] and "P04" not in codes(a)


def test_p07_liltoon_only():
    a = run(("L", make_unitypackage([(LIL_SHADER, "Assets/lilToon/Shader/lts.shader", b"Shader{}", None),
                                     own(9, "Assets/lilToon/Shader/new_in_next_version.shader", b"Shader{}")])))
    assert only(a, "P07").severity == GREEN
    assert "P04" not in codes(a) and "P22" not in codes(a)


def test_p08_exe_and_allow_exe():
    pkg = base(own(9, f"{SHOP}/setup.exe", b"MZ"))
    assert only(run(("A", pkg)), "P08").severity == RED
    assert only(run(("A", pkg), allow_exe=True), "P08").severity == YELLOW


def test_p09_p10_keywords():
    a = run(("A", base(own(9, f"{SHOP}/Editor/Auto.cs", b"[InitializeOnLoad] class A { UnityWebRequest r; }"))))
    assert only(a, "P09").count == 1
    f = only(a, "P10")
    assert "InitializeOnLoad" in f.examples[0] and "UnityWebRequest" in f.examples[0]


def test_p10n_plain_script():
    a = run(("A", base(own(9, f"{SHOP}/Editor/Plain.cs", CS))))
    assert "P09" in codes(a) and "P10" not in codes(a)


def test_p11_missing_script_shader_texture():
    a = run(("A", make_unitypackage([
        own(1, f"{SHOP}/a.prefab", prefab([(11500000, g(50))])),
        own(2, f"{SHOP}/b.mat", mat(g(51), [g(52)])),
    ])))
    fs = [f for f in a.findings if f.code == "P11"]
    assert len(fs) == 3
    titles = " ".join(f.title for f in fs)
    assert "スクリプト" in titles and "シェーダー" in titles and "テクスチャ 1" in titles
    assert any("Missing (Script)" in f.advice[0] for f in fs)
    assert any("ピンク" in f.advice[0] for f in fs)
    assert all("参照元:" in f.examples[0] for f in fs)


def test_p11_referrers_limited():
    entries = [own(i, f"{SHOP}/m{i}.mat", mat(g(99))) for i in range(1, 8)]
    f = only(run(("A", make_unitypackage(entries)), max_referrers=5), "P11")
    assert "ほか 2 件" in f.examples[0]


def test_p11n_and_p23_other_package():
    a = run(("A", make_unitypackage([own(1, f"{SHOP}/a.mat", mat(LIL_SHADER, [g(9)]))])),
            ("Common", make_unitypackage([own(9, "Assets/Shop/Common/t.png")])))
    assert "P11" not in codes(a)
    f = only(a, "P23")
    assert f.severity == YELLOW and "Common" in f.title
    assert a.common_packages == ["Common"]


def test_p12_p13_p14():
    a = run(("A", make_unitypackage([own(1, f"{SHOP}/bin.mat", b"\0\1\2"), own(2, "Library/x.png")])))
    assert only(a, "P12").count == 1 and only(a, "P14").severity == YELLOW
    p = read(make_unitypackage([own(1, f"{SHOP}/big.mat", mat(LIL_SHADER) + b"#" * 4096)]), "B", max_text_bytes=1024)
    recs = [InputRecord("B", "unitypackage", p.size, p.sha256, None, [p])]
    assert only(analyze(recs, known.load()), "P13").severity == YELLOW


def test_p15_path_length():
    p150 = "Assets/" + "a" * (150 - len("Assets/") - 4) + ".png"
    p151 = "Assets/" + "b" * (151 - len("Assets/") - 4) + ".png"
    assert len(p150) == 150 and len(p151) == 151
    a = run(("A", make_unitypackage([own(1, p150), own(2, p151)])))
    f = only(a, "P15")
    assert f.count == 1 and "b" * 20 in f.examples[0]
    assert "P15" not in codes(run(("A", make_unitypackage([own(2, p151)])), max_path=200))


def test_p16_windows_names():
    for paths in (["Assets/A/x.png", "Assets/a/X.png"], ["Assets/A/con.png"], ["Assets/A/x. "], ["Assets/A/a:b.png"],
                  ["Assets/LPT1/x.png"]):
        a = run(("A", make_unitypackage([own(i + 1, p) for i, p in enumerate(paths)])))
        assert "P16" in codes(a), paths
    ok = run(("A", make_unitypackage([own(1, "Assets/A/console.png"), own(2, "Assets/A/x.y.png")])))
    assert "P16" not in codes(ok)
    known_entry = run(("A", base((LIL_SHADER, "Assets/lilToon/CON.shader", b"x", None))))
    assert "P16" not in codes(known_entry)


def test_p17_scattered_top_level():
    assert "P17" in codes(run(("A", make_unitypackage([own(1, "Assets/readme.txt", b"x")]))))
    assert "P17" in codes(run(("A", make_unitypackage([own(1, "Assets/A/x.png"), own(2, "Assets/B/y.png")]))))
    quiet = run(("A", make_unitypackage([(g(9), "Assets/B", None, None), own(1, "Assets/A/x.png"),
                                         (LIL_SHADER, "Assets/lilToon/Shader/lts.shader", b"x", None)])))
    assert "P17" not in codes(quiet)


def test_p18_nested_archive():
    assert only(run(("A", base(own(9, f"{SHOP}/extra.zip", b"PK\5\6" + b"\0" * 18)))), "P18").count == 1


def test_p19_fixed_order():
    a = run(("A", make_unitypackage([own(1, f"{SHOP}/a.prefab", prefab([(-5, MA_CS)])),
                                     own(2, f"{SHOP}/b.mat", mat(LIL_SHADER))])))
    assert only(a, "P19").title == "購入者に必要なもの: lilToon, Modular Avatar"
    assert a.required == ["liltoon", "modular-avatar"]


def test_p20_dll_parts_and_vrchat_sdk():
    a = run(("A", make_unitypackage([own(1, f"{SHOP}/a.prefab", prefab([(-1427037861, g(70))]))])))
    assert only(a, "P20").severity == GREEN
    b = run(("A", make_unitypackage([own(1, f"{SHOP}/a.prefab", prefab([(1661092475, VRC_PHYSBONE)]))])))
    assert "P20" not in codes(b) and "VRChat SDK" in only(b, "P19").title


def test_p21_kind_counts():
    a = run(("A", make_unitypackage([
        (g(9), "Assets/Shop", None, None),
        own(1, f"{SHOP}/a.prefab", prefab()), own(2, f"{SHOP}/b.mat", mat(LIL_SHADER)), own(3, f"{SHOP}/c.png"),
        own(4, f"{SHOP}/d.fbx", b"\0fbx"), own(5, f"{SHOP}/e.anim", b"%YAML"), own(6, f"{SHOP}/f.cs", CS),
        own(7, f"{SHOP}/g.txt", b"x"),
    ])))
    s = a.summaries["A"]
    assert s.kinds == {"プレハブ": 1, "マテリアル": 1, "テクスチャ": 1, "メッシュ": 1, "アニメーション": 1, "スクリプト": 1, "その他": 1}
    assert s.files == 7 and s.folders == 1 and s.top_folders == ["Shop"]


# ---------------------------------------------------------------- cross-package

def two(a_entries, b_entries):
    return run(("A", make_unitypackage(a_entries)), ("B", make_unitypackage(b_entries)))


def test_x01_same_guid_different_content():
    a = two([own(1, f"{SHOP}/t.png", PNG)], [own(1, f"{SHOP}/t.png", PNG + b"v2")])
    assert only(a, "X01").severity == RED


def test_x01n_same_content_counts_as_common():
    a = two([own(1, f"{SHOP}/t.png"), own(2, f"{SHOP}/a.png")], [own(1, f"{SHOP}/t.png"), own(3, f"{SHOP}/b.png")])
    assert "X01" not in codes(a)
    f = only(a, "X04")
    assert f.count == 1 and f.examples == ["A だけにあるもの: 1 個", "B だけにあるもの: 1 個"]


def test_x02_x03():
    a = two([own(1, f"{SHOP}/t.png"), own(2, f"{SHOP}/u.png")], [own(1, f"{SHOP}/moved.png"), own(3, f"{SHOP}/u.png")])
    assert only(a, "X02").severity == YELLOW and only(a, "X03").severity == YELLOW


def test_x_known_excluded():
    lil_a = (LIL_SHADER, "Assets/lilToon/Shader/lts.shader", b"v1", None)
    lil_b = (LIL_SHADER, "Assets/lilToon/Shader/lts.shader", b"v2", None)
    a = two([own(1, f"{SHOP}/a.png"), lil_a], [own(2, f"{SHOP}/b.png"), lil_b])
    assert not {"X01", "X02", "X03"} & set(codes(a))


def test_x_folders_excluded():
    a = two([(g(1), "Assets/Shop", None, None), own(2, f"{SHOP}/a.png")],
            [(g(3), "Assets/Shop", None, None), own(4, f"{SHOP}/b.png")])
    assert "X03" not in codes(a)


def test_single_package_has_no_x():
    assert not [c for c in codes(run(("A", base()))) if c.startswith("X")]


def test_order_red_yellow_green_then_code():
    a = two([own(1, f"{SHOP}/t.png"), own(5, f"{SHOP}/run.exe", b"MZ"), own(6, "Assets/x.txt", b"x")],
            [own(1, f"{SHOP}/t.png", b"other")])
    sev = [f.severity for f in a.findings]
    assert sev == sorted(sev, key=[RED, YELLOW, GREEN].index)
    reds = [f.code for f in a.findings if f.severity == RED]
    assert reds == sorted(reds) == ["P08", "X01"]
