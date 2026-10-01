"""Version parsing for Unity and VPM (semver-like) strings."""

from __future__ import annotations

import re

_NUMERIC = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")
_WILDCARD = re.compile(r"(\d+(?:\.\d+)*)(?:\.[xX*])+")


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


_COMPARATOR = re.compile(
    r"(>=|<=|>|<|=)?\s*(\d+(?:\.\d+)*)((?:\.[xX*])+)?(-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?"
)
_PRERELEASE = re.compile(r"^\s*v?\d+(?:\.\d+)*-")


def _check(v: tuple[int, ...], v_pre: bool, op: str, bound: tuple[int, ...], b_pre: bool) -> bool | None:
    c = compare(v, bound)
    if c == 0 and (v_pre or b_pre):
        return None  # pre-release ordering at the same numbers: do not guess
    return {">=": c >= 0, "<=": c <= 0, ">": c > 0, "<": c < 0, "=": c == 0}[op]


def satisfies(version: str | None, spec: str) -> bool | None:
    """Judge a VPM dependency range.

    Understood: 'X.Y.x' wildcards, and one or more space-separated comparators
    ('>=1.14.7 <2.0.0-a', '>=3.7.0 <3.11.0', '3.1.4', '>=3.5.2 < 3.9.X'), as seen in real VPM package.json files.
    Returns None when either side cannot be interpreted ('||', '^', '~', ...); the caller then stays silent.
    UNVERIFIED: the full VPM range grammar is not documented in sources we could read.
    """
    v = parse_version(version)
    if v is None or not isinstance(spec, str) or not spec.strip():
        return None
    v_pre = bool(_PRERELEASE.match(version or ""))
    spec = spec.strip()
    if m := _WILDCARD.fullmatch(spec):
        prefix = parse_version(m.group(1)) or ()
        return _pad(v, len(prefix))[: len(prefix)] == prefix
    result = True
    for token in re.findall(r"(?:>=|<=|>|<|=)?\s*[^\s<>=]+", spec):
        m = _COMPARATOR.fullmatch(token.strip())
        if not m:
            return None
        op, bound, wild, pre = m.group(1) or "=", parse_version(m.group(2)) or (), bool(m.group(3)), bool(m.group(4))
        if wild and pre:
            return None
        for op2, bound2 in _expand_wildcard(op, bound) if wild else [(op, bound)]:
            ok = _check(v, v_pre, op2, bound2, pre)
            if ok is None:
                return None
            result = result and ok
    return result


def _next(bound: tuple[int, ...]) -> tuple[int, ...]:
    return bound[:-1] + (bound[-1] + 1,)


def _expand_wildcard(op: str, bound: tuple[int, ...]) -> list[tuple[str, tuple[int, ...]]]:
    """'<3.9.x' -> '<3.9.0'; '<=3.9.x' -> '<3.10.0'; '>3.9.x' -> '>=3.10.0'; '=3.9.x' -> '>=3.9.0 <3.10.0'.

    Same reading as npm semver; seen in a real package as '>=3.5.2 < 3.9.X'.
    """
    if op == "<":
        return [("<", bound)]
    if op == ">=":
        return [(">=", bound)]
    if op == "<=":
        return [("<", _next(bound))]
    if op == ">":
        return [(">=", _next(bound))]
    return [(">=", bound), ("<", _next(bound))]


def unity_major_minor(v: str) -> str:
    """'2022.3.22f1' -> '2022.3'."""
    return ".".join(v.strip().split(".")[:2])
