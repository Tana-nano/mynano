"""Version parsing for Unity and VPM (semver-like) strings."""

from __future__ import annotations

import re

_NUMERIC = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")
_GE = re.compile(r">=\s*(\d+(?:\.\d+)*)")
_WILDCARD = re.compile(r"(\d+(?:\.\d+)*)\.[xX]")
_EXACT = re.compile(r"\d+(?:\.\d+)*(?:[-+][0-9A-Za-z.-]+)?")


def parse_version(s: str | None) -> tuple[int, ...] | None:
    """'3.1.4-beta.1' -> (3, 1, 4). None when there is no leading number."""
    if not isinstance(s, str):
        return None
    m = _NUMERIC.match(s)
    if not m:
        return None
    return tuple(int(x) for x in m.group(1).split("."))


def _pad(t: tuple[int, ...], n: int = 3) -> tuple[int, ...]:
    return t + (0,) * max(0, n - len(t))


def compare(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    n = max(len(a), len(b), 3)
    pa, pb = _pad(a, n), _pad(b, n)
    return (pa > pb) - (pa < pb)


def satisfies(version: str | None, spec: str) -> bool | None:
    """Judge a VPM dependency range. Only '>=X', 'X.x' and exact 'X.Y.Z' are understood.

    Returns None when either side cannot be interpreted (the caller then stays silent).
    UNVERIFIED: the full VPM range grammar is not documented in sources we could read.
    """
    v = parse_version(version)
    if v is None or not isinstance(spec, str):
        return None
    spec = spec.strip()
    if m := _GE.fullmatch(spec):
        return compare(v, parse_version(m.group(1)) or ()) >= 0
    if m := _WILDCARD.fullmatch(spec):
        prefix = parse_version(m.group(1)) or ()
        return _pad(v, len(prefix))[: len(prefix)] == prefix
    if _EXACT.fullmatch(spec):
        return compare(v, parse_version(spec) or ()) == 0
    return None


def unity_major_minor(v: str) -> str:
    """'2022.3.22f1' -> '2022.3'."""
    return ".".join(v.strip().split(".")[:2])
