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

    def __init__(self, project_paths: Iterable[str] = (), other_paths: Iterable[str] = ()):
        """other_paths: another project the Editor.log belongs to; its name can be as personal as ours."""
        pats: dict[str, tuple[re.Pattern[str], str]] = {}
        for token, paths in (("<OTHER_PROJECT>", other_paths), ("<PROJECT>", project_paths)):
            for path in paths:
                if path and (pat := _path_pattern(path)):
                    pats[pat.pattern.casefold()] = (pat, token)  # the target project wins on the same path
        # Longer paths first so the most specific spelling wins.
        self._projects = sorted(pats.values(), key=lambda pt: -len(pt[0].pattern))

    def __call__(self, text: str) -> str:
        for p, token in self._projects:
            text = p.sub(token, text)
        text = _IDS.sub(lambda m: f"{m.group(1)}_xxxx", text)
        text = _USERS.sub("%USERPROFILE%", text)
        text = _HOME_POSIX.sub("~", text)
        return _EMAIL.sub("<email>", text)
