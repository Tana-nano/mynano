"""Pre-release checks for products/<name>.

Fails (exit 1) on anything that would embarrass us on Booth:
- product.toml missing / inconsistent (name, version, quest flag)
- README / EULA / CHANGELOG missing, README lacks required sections
- Quest 単機 non-support not stated in README
- CHANGELOG lacks the current version
- files that must never ship: .unitypackage, shaders, other people's prefabs, secrets
- AI tool names or session URLs leaking into shipped text

Usage: python scripts/release_check.py <name>
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FILES = ["README.md", "EULA.md", "CHANGELOG.md", "product.toml"]
REQUIRED_README_SECTIONS = ["できること", "対応環境", "導入手順", "既知の制限", "利用規約"]
QUEST_PATTERNS = [r"Quest\s*単機", r"Quest\s*単体", r"Quest.*非対応"]
FORBIDDEN_SUFFIXES = {".unitypackage", ".shader", ".cginc", ".hlsl", ".fbx", ".vrm", ".pem", ".key"}
FORBIDDEN_TEXT = [
    r"claude\.ai/code/session",
    r"\bClaude\b",
    r"\bChatGPT\b",
    r"\bCopilot\b",
    r"sk-[A-Za-z0-9]{20,}",
]
SHIPPED_TEXT_GLOBS = ["README.md", "EULA.md", "CHANGELOG.md", "booth.md", "src/**/*.py"]


def check(name: str) -> list[str]:
    errors: list[str] = []
    pdir = ROOT / "products" / name
    if not pdir.is_dir():
        return [f"products/{name} does not exist"]

    for f in REQUIRED_FILES:
        if not (pdir / f).exists():
            errors.append(f"missing {f}")
    if errors:
        return errors

    meta = tomllib.loads((pdir / "product.toml").read_text(encoding="utf-8"))
    prod = meta.get("product", {})
    support = meta.get("support", {})
    version = prod.get("version", "")

    if prod.get("name") != name:
        errors.append(f"product.toml name={prod.get('name')!r} != directory {name!r}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        errors.append(f"version {version!r} is not SemVer")
    if prod.get("kind") == "pc-app" and support.get("quest_standalone") is not False:
        errors.append("pc-app must set support.quest_standalone = false")

    readme = (pdir / "README.md").read_text(encoding="utf-8")
    for sec in REQUIRED_README_SECTIONS:
        if sec not in readme:
            errors.append(f"README lacks section containing {sec!r}")
    if "{{" in readme:
        errors.append("README still has {{template}} placeholders")
    if support.get("quest_standalone") is False and not any(re.search(p, readme) for p in QUEST_PATTERNS):
        errors.append("README must state Quest 単機 非対応")

    changelog = (pdir / "CHANGELOG.md").read_text(encoding="utf-8")
    if version and version not in changelog:
        errors.append(f"CHANGELOG has no entry for {version}")

    eula = (pdir / "EULA.md").read_text(encoding="utf-8")
    if "{{" in eula:
        errors.append("EULA still has {{template}} placeholders")

    for f in pdir.rglob("*"):
        if f.is_file() and f.suffix.lower() in FORBIDDEN_SUFFIXES and "tests" not in f.parts:
            errors.append(f"forbidden file in product: {f.relative_to(pdir)}")

    for pattern in SHIPPED_TEXT_GLOBS:
        for f in pdir.glob(pattern):
            text = f.read_text(encoding="utf-8", errors="replace")
            for rx in FORBIDDEN_TEXT:
                if re.search(rx, text):
                    errors.append(f"{f.relative_to(pdir)} matches forbidden text /{rx}/")
    return errors


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    errs = check(sys.argv[1])
    for e in errs:
        print("NG:", e)
    if errs:
        sys.exit(1)
    print("OK: release checks passed")
