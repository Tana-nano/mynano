"""Build products/<name>/dist/<name>-<version>.zip from product.toml.

Only files listed in [dist].include are shipped; [dist].exclude prunes
subtrees. This is the *source* distribution; the Windows exe is built by
.github/workflows/build-windows.yml and zipped there.

Usage: python scripts/package.py <name>
"""

from __future__ import annotations

import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_product(name: str) -> tuple[Path, dict]:
    pdir = ROOT / "products" / name
    meta_path = pdir / "product.toml"
    if not meta_path.exists():
        raise SystemExit(f"product.toml not found: {meta_path}")
    with meta_path.open("rb") as f:
        return pdir, tomllib.load(f)


def iter_files(pdir: Path, include: list[str], exclude: list[str]):
    ex = [e.rstrip("/") for e in exclude]
    for item in include:
        p = pdir / item
        if p.is_file():
            yield p
        elif p.is_dir():
            for f in sorted(p.rglob("*")):
                rel = f.relative_to(pdir).as_posix()
                if f.is_file() and not any(part in ex for part in rel.split("/")):
                    yield f


def build(name: str) -> Path:
    pdir, meta = load_product(name)
    version = meta["product"]["version"]
    dist = meta.get("dist", {})
    out_dir = pdir / "dist"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{name}-{version}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for f in iter_files(pdir, dist.get("include", []), dist.get("exclude", [])):
            z.write(f, f"{name}/{f.relative_to(pdir).as_posix()}")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    print(build(sys.argv[1]))
