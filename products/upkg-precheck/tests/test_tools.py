"""D01-D03: the dictionary build script (pure part only; no network)."""

import importlib.util
import logging
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("build_known_assets", HERE.parent / "tools" / "build_known_assets.py")
bka = importlib.util.module_from_spec(_spec)
sys.modules["build_known_assets"] = bka  # dataclasses look the module up
_spec.loader.exec_module(bka)


def write_meta(root: Path, rel: str, guid: str | None) -> None:
    p = root / (rel + ".meta")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("fileFormatVersion: 2\n" + (f"guid: {guid}\n" if guid else "") + "DefaultImporter:\n")


def test_d01_union_of_tags_newer_path_wins(tmp_path):
    old, new = tmp_path / "1.0.0", tmp_path / "1.1.0"
    write_meta(old, "Assets/lilToon/a.shader", "a" * 32)
    write_meta(old, "Assets/lilToon/b.shader", "b" * 32)
    write_meta(new, "Assets/lilToon/a.shader", "c" * 32)  # GUID changed in the new version
    write_meta(new, "Assets/lilToon/moved/b.shader", "b" * 32)
    write_meta(new, "Assets/lilToon/d.shader", "d" * 32)
    write_meta(new, "UnitTests~/t.cs", "e" * 32)  # hidden from Unity
    got = bka.union_tags([("1.0.0", bka.iter_metas_in_dir(old)), ("1.1.0", bka.iter_metas_in_dir(new))],
                         bka.project_mapper)
    assert set(got) == {"a" * 32, "b" * 32, "c" * 32, "d" * 32}
    assert got["b" * 32] == "Assets/lilToon/moved/b.shader"


def test_d02_duplicate_across_sources_stops():
    with pytest.raises(bka.DuplicateGuidError):
        bka.merge_sources({"liltoon": {"a" * 32: "Assets/lilToon/x"}, "poiyomi": {"a" * 32: "Assets/_PoiyomiShaders/x"}})


def test_d03_meta_without_guid_is_skipped(tmp_path, caplog):
    write_meta(tmp_path, "Assets/lilToon/a.shader", None)
    write_meta(tmp_path, "Assets/lilToon/b.shader", "b" * 32)
    with caplog.at_level(logging.WARNING):
        got = bka.union_tags([("t", bka.iter_metas_in_dir(tmp_path))], bka.project_mapper)
    assert got == {"b" * 32: "Assets/lilToon/b.shader"}
    assert "no guid line" in caplog.text


def test_mappers_and_tag_selection():
    poi = bka.package_mapper("com.poiyomi.toon", ("_PoiyomiShaders",))
    assert poi("_PoiyomiShaders/Shaders/x.shader") == "Assets/_PoiyomiShaders/Shaders/x.shader"
    assert poi("Assets/_PoiyomiShaders/x.shader") == "Assets/_PoiyomiShaders/x.shader"
    ma = bka.package_mapper("nadena.dev.modular-avatar")
    assert ma("Editor/x.cs") == "Packages/nadena.dev.modular-avatar/Editor/x.cs"
    assert ma("Assets/FixedPrefab.prefab") is None  # old dev project, never distributed
    assert ma("Packages/nadena.dev.ndmf/x.cs") is None
    assert bka.vrcfury_mapper("com.vrcfury.vrcfury/Editor/x.cs") == "Packages/com.vrcfury.vrcfury/Editor/x.cs"
    tags = ["1.1", "1.2.0", "1.2.3", "1.3.0-beta.1", "1.3.0", "1.3.4", "V8.1.167", "v9.3.64", "v10.0.23", "v10.0.22"]
    assert bka.select_tags(tags, "minor") == ["1.2.0", "1.3.0", "v10.0.23"]
    assert bka.select_tags(tags, "majors:8,9,10") == ["V8.1.167", "v9.3.64", "v10.0.23"]
