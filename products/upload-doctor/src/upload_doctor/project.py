"""Collect facts from a Unity project folder. Read-only; never touches Library/."""

from __future__ import annotations

import fnmatch
import json
import os
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from .rules import Rules

SCAN_LIMIT = 20_000
SYMBOLS = ("VRC_SDK_VRCSDK2", "VRC_SDK_VRCSDK3", "UDON")


@dataclass
class PackageInfo:
    id: str
    version: str | None
    vpm_deps: dict[str, str] = field(default_factory=dict)


@dataclass
class ProjectFacts:
    root: Path
    unity_version: str | None = None
    upm_manifest_broken: bool = False
    vpm_manifest_present: bool = False
    vpm_manifest_broken: bool = False
    vpm_expected: dict[str, str | None] = field(default_factory=dict)
    vpm_expected_from_locked: bool = False
    packages: dict[str, PackageInfo] = field(default_factory=dict)
    assets_vrcsdk: bool = False
    settings_state: str = "missing"  # missing | text | binary | unreadable
    settings_symbols: set[str] = field(default_factory=set)
    folder_hits: dict[str, list[str]] = field(default_factory=dict)
    scan_truncated: bool = False
    scan_limit: int = SCAN_LIMIT
    non_ascii: list[str] = field(default_factory=list)  # "project" / "userprofile"
    path_length: int = 0
    unity_open: bool = False
    read_files: list[str] = field(default_factory=list)

    @property
    def vrchat_packages(self) -> list[str]:
        return sorted(p for p in self.packages if p.startswith("com.vrchat."))

    @property
    def manifest_lists_vrchat(self) -> bool:
        return any(k.startswith("com.vrchat.") for k in self.vpm_expected)


def clean_path_arg(s: str) -> str:
    """Paths dropped onto a console arrive wrapped in quotes ("..." in cmd, '...' in PowerShell)."""
    s = s.strip()
    if s.startswith("& "):  # PowerShell prefixes a dropped path with the call operator
        s = s[2:].strip()
    return s.strip("\"'").strip()


def is_unity_project(p: Path) -> bool:
    return (p / "Assets").is_dir() and (p / "ProjectSettings").is_dir()


def nearby_projects(p: Path) -> list[Path]:
    try:
        children = sorted(c for c in p.iterdir() if c.is_dir())
    except OSError:
        return []
    return [c for c in children if is_unity_project(c)]


def _read_json(path: Path) -> tuple[Any, str]:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None, "missing"
    except (OSError, UnicodeDecodeError):
        return None, "broken"
    try:
        return json.loads(text), "ok"
    except json.JSONDecodeError:
        return None, "broken"


def read_unity_version(root: Path) -> str | None:
    # UNVERIFIED: the 'm_EditorVersion: <ver>' line format is the commonly known one; Unity docs unreadable here.
    try:
        text = (root / "ProjectSettings" / "ProjectVersion.txt").read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        key, sep, val = line.partition(":")
        if sep and key.strip() == "m_EditorVersion":
            return val.strip() or None
    return None


def _scan_assets(root: Path, rules: Rules, limit: int) -> tuple[dict[str, list[str]], bool]:
    hits: dict[str, list[str]] = {}
    depth_needed = max((r.max_depth for r in rules.folder_rules), default=0)
    if depth_needed == 0:
        return hits, False
    count = 0
    queue: deque[tuple[Path, int]] = deque([(root / "Assets", 1)])
    while queue:
        folder, depth = queue.popleft()
        try:
            with os.scandir(folder) as it:
                entries = sorted(it, key=lambda e: e.name)
        except OSError:
            continue
        for e in entries:
            count += 1
            if count > limit:
                return hits, True
            try:
                if not e.is_dir(follow_symlinks=False):
                    continue
            except OSError:
                continue
            rel = Path(e.path).relative_to(root).as_posix()
            for r in rules.folder_rules:
                if depth <= r.max_depth and fnmatch.fnmatchcase(e.name.casefold(), r.name_glob.casefold()):
                    hits.setdefault(r.id, []).append(rel)
            if depth < depth_needed:
                queue.append((Path(e.path), depth + 1))
    return hits, False


def collect(
    project: Path,
    rules: Rules,
    env: Mapping[str, str] | None = None,
    scan_limit: int = SCAN_LIMIT,
) -> ProjectFacts:
    env = os.environ if env is None else env
    root = Path(os.path.abspath(project))
    f = ProjectFacts(root=root, scan_limit=scan_limit)

    f.unity_version = read_unity_version(root)
    f.read_files.append("ProjectSettings/ProjectVersion.txt")

    packages_dir = root / "Packages"
    _, st = _read_json(packages_dir / "manifest.json")
    f.upm_manifest_broken = st == "broken"
    if st != "missing":
        f.read_files.append("Packages/manifest.json")

    data, st = _read_json(packages_dir / "vpm-manifest.json")
    f.vpm_manifest_present = st != "missing"
    if f.vpm_manifest_present:
        f.read_files.append("Packages/vpm-manifest.json")
    f.vpm_manifest_broken = st == "broken" or (st == "ok" and not isinstance(data, dict))
    if st == "ok" and isinstance(data, dict):
        # UNVERIFIED: field names come from a search summary of the VCC docs (vcc.docs.vrchat.com is blocked).
        locked, deps = data.get("locked"), data.get("dependencies")
        f.vpm_expected_from_locked = isinstance(locked, dict) and bool(locked)
        src = locked if f.vpm_expected_from_locked else deps if isinstance(deps, dict) else {}
        for pid, entry in src.items():
            ver = entry.get("version") if isinstance(entry, dict) else entry
            f.vpm_expected[str(pid)] = ver if isinstance(ver, str) else None

    if packages_dir.is_dir():
        try:
            children = sorted(c for c in packages_dir.iterdir() if c.is_dir())
        except OSError:
            children = []
        for c in children:
            pj, st = _read_json(c / "package.json")
            version, deps = None, {}
            if st == "ok" and isinstance(pj, dict):
                version = pj.get("version") if isinstance(pj.get("version"), str) else None
                raw = pj.get("vpmDependencies")
                if isinstance(raw, dict):
                    deps = {str(k): v for k, v in raw.items() if isinstance(v, str)}
                f.read_files.append(f"Packages/{c.name}/package.json")
            f.packages[c.name] = PackageInfo(c.name, version, deps)

    f.assets_vrcsdk = (root / "Assets" / "VRCSDK").is_dir()

    settings = root / "ProjectSettings" / "ProjectSettings.asset"
    try:
        raw_bytes = settings.read_bytes()
    except FileNotFoundError:
        f.settings_state = "missing"
    except OSError:
        f.settings_state = "unreadable"
    else:
        f.read_files.append("ProjectSettings/ProjectSettings.asset")
        if b"\x00" in raw_bytes[:8192]:
            f.settings_state = "binary"
        else:
            f.settings_state = "text"
            text = raw_bytes.decode("utf-8", "replace")
            f.settings_symbols = {
                s for s in SYMBOLS if re.search(rf"(?<![A-Za-z0-9_]){s}(?![A-Za-z0-9_])", text)
            }

    f.folder_hits, f.scan_truncated = _scan_assets(root, rules, scan_limit)

    if not str(root).isascii():
        f.non_ascii.append("project")
    profile = env.get("USERPROFILE", "")
    if profile and not profile.isascii():
        f.non_ascii.append("userprofile")
    f.path_length = len(str(root))
    # Seen on Windows 11 with Unity 2022.3.22f1 (2026-10-01): present while open, Temp/ removed on File > Exit.
    # After a crash the file may stay behind, so this is only a hint.
    f.unity_open = (root / "Temp" / "UnityLockfile").exists()
    return f
