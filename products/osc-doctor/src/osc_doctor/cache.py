"""VRChat's per-avatar OSC config cache: OSC\\usr_*\\Avatars\\*.json."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass(frozen=True)
class CacheSummary:
    path: Path
    users: int
    files: int
    newest: datetime | None


def osc_folder(vrc_dir: Path) -> Path:
    return vrc_dir / "OSC"


def summarize(vrc_dir: Path) -> CacheSummary | None:
    root = osc_folder(vrc_dir)
    if not root.is_dir():
        return None
    users = [p for p in root.glob("usr_*") if p.is_dir()]
    files = [f for u in users for f in (u / "Avatars").glob("*.json")]
    newest = max((datetime.fromtimestamp(f.stat().st_mtime) for f in files), default=None)
    return CacheSummary(root, len(users), len(files), newest)


class CacheMoveError(Exception):
    pass


def move_cache(vrc_dir: Path, backup_root: Path, now: datetime) -> Path | None:
    """Move the whole OSC folder into ``backup_root/OSC-<stamp>``. Nothing is deleted."""
    src = osc_folder(vrc_dir)
    if not src.is_dir():
        return None
    dest = backup_root / f"OSC-{now:%Y%m%d-%H%M%S}"
    try:
        backup_root.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            raise CacheMoveError(f"{dest} already exists")
        shutil.move(str(src), str(dest))
    except (OSError, shutil.Error) as e:
        # shutil.move may copy then fail to delete; put things back if so.
        if dest.exists() and not src.exists():
            pass  # moved fully
        elif dest.exists() and src.exists():
            shutil.rmtree(dest, ignore_errors=True)
            raise CacheMoveError(str(e)) from e
        else:
            raise CacheMoveError(str(e)) from e
    return dest
