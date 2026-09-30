"""Helpers shared by upload-doctor tests: a fake Unity project builder and fixture paths."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any

from upload_doctor import rules as rules_mod

REPO = Path(__file__).resolve().parents[3]
FIXTURES = REPO / "shared" / "fixtures" / "unity"
TODAY = date(2026, 9, 30)
NOW = datetime(2026, 9, 30, 22, 15, 30)
RECOMMENDED = "2022.3.22f1"


def bundled_rules() -> rules_mod.Rules:
    return rules_mod.load()


def rules_data() -> dict[str, Any]:
    return json.loads((REPO / "products/upload-doctor/src/upload_doctor/rules.json").read_text(encoding="utf-8"))


def make_project(
    root: Path,
    *,
    unity: str | None = RECOMMENDED,
    unity_text: str | None = None,
    packages: dict[str, Any] | None = None,
    vpm_manifest: Any = "auto",
    upm_manifest: str | None = "{}",
    assets_dirs: tuple[str, ...] = (),
    settings: bytes | str | None = None,
) -> Path:
    """packages: {id: version} or {id: (version, {dep: range})}; version None = no package.json.

    vpm_manifest: "auto" = locked from `packages`, None = no file, str = raw text, dict = JSON.
    """
    (root / "Assets").mkdir(parents=True)
    (root / "ProjectSettings").mkdir()
    if unity_text is not None:
        (root / "ProjectSettings" / "ProjectVersion.txt").write_text(unity_text, encoding="utf-8")
    elif unity is not None:
        (root / "ProjectSettings" / "ProjectVersion.txt").write_text(
            f"m_EditorVersion: {unity}\nm_EditorVersionWithRevision: {unity} (0000)\n", encoding="utf-8"
        )
    packages = {"com.vrchat.base": "3.10.1", "com.vrchat.avatars": "3.10.1"} if packages is None else packages
    pdir = root / "Packages"
    pdir.mkdir()
    locked = {}
    for pid, spec in packages.items():
        version, deps = spec if isinstance(spec, tuple) else (spec, None)
        d = pdir / pid
        d.mkdir()
        if version is not None:
            pj: dict[str, Any] = {"name": pid, "version": version}
            if deps is not None:
                pj["vpmDependencies"] = deps
            (d / "package.json").write_text(json.dumps(pj), encoding="utf-8")
            locked[pid] = {"version": version}
    if vpm_manifest == "auto":
        vpm_manifest = {"dependencies": {}, "locked": locked}
    if isinstance(vpm_manifest, dict):
        (pdir / "vpm-manifest.json").write_text(json.dumps(vpm_manifest), encoding="utf-8")
    elif isinstance(vpm_manifest, str):
        (pdir / "vpm-manifest.json").write_text(vpm_manifest, encoding="utf-8")
    if upm_manifest is not None:
        (pdir / "manifest.json").write_text(upm_manifest, encoding="utf-8")
    for d in assets_dirs:
        (root / "Assets" / d).mkdir(parents=True, exist_ok=True)
    if settings is not None:
        p = root / "ProjectSettings" / "ProjectSettings.asset"
        if isinstance(settings, bytes):
            p.write_bytes(settings)
        else:
            p.write_text(settings, encoding="utf-8")
    return root


def write_log(path: Path, lines: list[str] | str, project: Path | None = None) -> Path:
    body = lines if isinstance(lines, str) else "\n".join(lines) + "\n"
    head = f"COMMAND LINE ARGUMENTS:\nUnity.exe\n-projectpath\n{project}\n" if project is not None else ""
    path.write_text(head + body, encoding="utf-8")
    return path


def ids(findings) -> dict:
    return {f.id: f for f in findings}
