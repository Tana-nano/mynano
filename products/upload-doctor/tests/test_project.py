import os

from ud_helpers import bundled_rules, make_project
from upload_doctor import project


def collect(root, env=None, **kw):
    return project.collect(root, bundled_rules(), env or {"USERPROFILE": "C:\\Users\\fixture"}, **kw)


def test_unity_version_forms(tmp_path):
    p = make_project(tmp_path / "a", unity_text="\ufeffm_EditorVersion: 2022.3.22f1\r\nm_EditorVersionWithRevision: 2022.3.22f1 (x)\r\n")
    assert collect(p).unity_version == "2022.3.22f1"
    p = make_project(tmp_path / "b", unity_text="m_EditorVersionWithRevision: 2022.3.22f1 (x)\n")
    assert collect(p).unity_version is None
    p = make_project(tmp_path / "c", unity=None)
    assert collect(p).unity_version is None


def test_is_unity_project_and_nearby(tmp_path):
    make_project(tmp_path / "outer" / "RealProject")
    assert not project.is_unity_project(tmp_path / "outer")
    assert project.nearby_projects(tmp_path / "outer") == [tmp_path / "outer" / "RealProject"]
    assert project.clean_path_arg('  "C:\\Foo Bar\\Proj"  ') == "C:\\Foo Bar\\Proj"
    assert project.clean_path_arg("& 'C:\\Foo Bar\\Proj'") == "C:\\Foo Bar\\Proj"


def test_vpm_manifest_states(tmp_path):
    f = collect(make_project(tmp_path / "ok"))
    assert f.vpm_manifest_present and not f.vpm_manifest_broken and f.vpm_expected_from_locked
    assert f.vpm_expected == {"com.vrchat.avatars": "3.10.1", "com.vrchat.base": "3.10.1"}

    f = collect(make_project(tmp_path / "broken", vpm_manifest="{not json"))
    assert f.vpm_manifest_broken

    f = collect(make_project(tmp_path / "none", vpm_manifest=None))
    assert not f.vpm_manifest_present

    f = collect(make_project(tmp_path / "deps", vpm_manifest={"dependencies": {"com.vrchat.avatars": {"version": "3.10.1"}}}))
    assert f.vpm_expected == {"com.vrchat.avatars": "3.10.1"} and not f.vpm_expected_from_locked


def test_packages_and_deps(tmp_path):
    f = collect(make_project(tmp_path / "p", packages={"com.foo": ("1.0.0", {"com.vrchat.base": "3.1.x"}), "com.nojson": None}))
    assert f.packages["com.foo"].vpm_deps == {"com.vrchat.base": "3.1.x"}
    assert f.packages["com.nojson"].version is None


def test_upm_manifest(tmp_path):
    assert collect(make_project(tmp_path / "a", upm_manifest="{oops")).upm_manifest_broken
    assert not collect(make_project(tmp_path / "b", upm_manifest=None)).upm_manifest_broken


def test_settings_symbols(tmp_path):
    text = "PlayerSettings:\n  scriptingDefineSymbols:\n    1: VRC_SDK_VRCSDK2;UDON;UDONSHARP_X\n"
    f = collect(make_project(tmp_path / "t", settings=text))
    assert f.settings_state == "text" and f.settings_symbols == {"VRC_SDK_VRCSDK2", "UDON"}
    f = collect(make_project(tmp_path / "b", settings=b"\x00\x01binary"))
    assert f.settings_state == "binary"
    assert collect(make_project(tmp_path / "m")).settings_state == "missing"


def test_folder_scan_depth_and_library(tmp_path):
    root = make_project(tmp_path / "p", assets_dirs=("DynamicBone", "Foo/Dynamic Bone", "a/b/DynamicBone"))
    (root / "Library" / "DynamicBone").mkdir(parents=True)
    f = collect(root)
    assert f.folder_hits["dynamic_bone"] == ["Assets/DynamicBone", "Assets/Foo/Dynamic Bone"]
    assert not f.scan_truncated


def test_folder_scan_truncates(tmp_path):
    root = make_project(tmp_path / "p", assets_dirs=tuple(f"d{i:02}" for i in range(12)) + ("zz/DynamicBone",))
    f = collect(root, scan_limit=10)
    assert f.scan_truncated and "dynamic_bone" not in f.folder_hits


def test_paths(tmp_path):
    f = collect(make_project(tmp_path / "日本語"))
    assert f.non_ascii == ["project"]
    f = collect(make_project(tmp_path / "ascii"), env={"USERPROFILE": "C:\\Users\\たろう"})
    assert f.non_ascii == ["userprofile"]
    f = collect(make_project(tmp_path / "plain"))
    assert f.non_ascii == [] and f.path_length == len(os.path.abspath(tmp_path / "plain"))


def test_collect_is_read_only(tmp_path):
    root = make_project(tmp_path / "p", assets_dirs=("DynamicBone",), settings="x: VRC_SDK_VRCSDK2")

    def snapshot():
        return sorted((str(p), p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*"))

    before = snapshot()
    collect(root)
    assert snapshot() == before
