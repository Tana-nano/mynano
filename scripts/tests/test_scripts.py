import shutil
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import package  # noqa: E402
import release_check  # noqa: E402


@pytest.fixture
def product(tmp_path, monkeypatch):
    """A minimal valid product tree under a temporary ROOT."""
    root = tmp_path
    pdir = root / "products" / "demo-tool"
    (pdir / "src" / "demo_tool").mkdir(parents=True)
    (pdir / "tests").mkdir()
    (pdir / "src" / "demo_tool" / "__init__.py").write_text("VERSION = '0.1.0'\n", encoding="utf-8")
    (pdir / "tests" / "test_x.py").write_text("def test_x(): pass\n", encoding="utf-8")
    (pdir / "requirements.txt").write_text("python-osc\n", encoding="utf-8")
    (pdir / "product.toml").write_text(
        """
[product]
name = "demo-tool"
display_name = "デモ"
version = "0.1.0"
kind = "pc-app"
price_jpy = 500
entry = "src/demo_tool/__main__.py"
package = "demo_tool"

[support]
pc_vr = true
desktop = true
quest_standalone = false

[dist]
include = ["README.md", "EULA.md", "CHANGELOG.md", "src/", "requirements.txt"]
exclude = ["tests/", "__pycache__/"]
""",
        encoding="utf-8",
    )
    (pdir / "README.md").write_text(
        "# デモ\n## できること\n- x\n## 対応環境\nQuest 単機 非対応\n## 導入手順\n1.\n## 既知の制限\n-\n## 利用規約\nEULA.md\n",
        encoding="utf-8",
    )
    (pdir / "EULA.md").write_text("# 利用規約\n", encoding="utf-8")
    (pdir / "CHANGELOG.md").write_text("## 0.1.0 - 2026-09-29\n- 初版\n", encoding="utf-8")
    monkeypatch.setattr(package, "ROOT", root)
    monkeypatch.setattr(release_check, "ROOT", root)
    return pdir


def test_release_check_passes_on_valid_product(product):
    assert release_check.check("demo-tool") == []


def test_release_check_flags_missing_quest_note_and_placeholders(product):
    (product / "README.md").write_text(
        "# {{x}}\n## できること\n## 対応環境\n## 導入手順\n## 既知の制限\n## 利用規約\n", encoding="utf-8"
    )
    errs = release_check.check("demo-tool")
    assert any("Quest" in e for e in errs)
    assert any("placeholders" in e for e in errs)


def test_release_check_flags_forbidden_files_and_text(product):
    (product / "src" / "demo_tool" / "cool.shader").write_text("x", encoding="utf-8")
    (product / "README.md").write_text(
        (product / "README.md").read_text(encoding="utf-8") + "\nMade with Claude\n", encoding="utf-8"
    )
    errs = release_check.check("demo-tool")
    assert any("forbidden file" in e for e in errs)
    assert any("forbidden text" in e for e in errs)


def test_release_check_requires_changelog_entry(product):
    (product / "CHANGELOG.md").write_text("## 0.0.9\n", encoding="utf-8")
    assert any("CHANGELOG" in e for e in release_check.check("demo-tool"))


def test_package_ships_only_included_files(product):
    out = package.build("demo-tool")
    assert out.name == "demo-tool-0.1.0.zip"
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
    assert "demo-tool/README.md" in names
    assert "demo-tool/src/demo_tool/__init__.py" in names
    assert not any("tests/" in n for n in names)
    shutil.rmtree(product / "dist")
