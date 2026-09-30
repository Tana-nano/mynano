"""Masking for everything shown or saved: IDs, user names, the project path, e-mail addresses."""

from __future__ import annotations

import re
from typing import Iterable

_IDS = re.compile(r"\b(usr|avtr|wrld)_[0-9A-Za-z-]{8,}")
_USERS = re.compile(r"([A-Za-z]:[\\/]+Users[\\/]+)[^\\/\r\n\"'<>|]+", re.IGNORECASE)
_HOME_POSIX = re.compile(r"/(?:home|Users)/[^/\s\"']+")
# The TLD must be letters so that 'com.unity.ugui@1.0.0' (PackageCache paths) is not taken for an address.
_EMAIL = re.compile(r"[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
_SEP = r"[\\/]+"
# A path match must end at a boundary so that '.../Proj' does not mask the front of '.../Proj2'.
_END = r"(?![^\\/\s\"'():,;])"


def _path_pattern(path: str) -> re.Pattern[str] | None:
    parts = [p for p in re.split(r"[\\/]+", path) if p]
    if not parts:
        return None
    lead = _SEP if path[:1] in "\\/" else ""
    return re.compile(lead + _SEP.join(re.escape(p) for p in parts) + _END, re.IGNORECASE)


class Masker:
    """Order matters: the project path first, then the user folder, so a project under
    C:\\Users\\<name>\\ becomes '<PROJECT>' and not '%USERPROFILE%\\...'."""

    def __init__(self, project_paths: Iterable[str] = ()):
        pats = {_path_pattern(p) for p in project_paths if p}
        # Longer paths first so the most specific spelling wins.
        self._projects = sorted((p for p in pats if p), key=lambda p: -len(p.pattern))

    def __call__(self, text: str) -> str:
        for p in self._projects:
            text = p.sub("<PROJECT>", text)
        text = _IDS.sub(lambda m: f"{m.group(1)}_xxxx", text)
        text = _USERS.sub("%USERPROFILE%", text)
        text = _HOME_POSIX.sub("~", text)
        return _EMAIL.sub("<email>", text)
