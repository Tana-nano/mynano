from __future__ import annotations

import io

from upkg_precheck import known
from upkg_precheck.archive import InputRecord
from upkg_precheck.checks import Analysis, Finding, Options, analyze
from upkg_precheck.unitypackage import Package, read_unitypackage


def read(data: bytes, name: str = "A.unitypackage", **kw) -> Package:
    return read_unitypackage(name, io.BytesIO(data), **kw)


def inputs(*pkgs: tuple[str, bytes]) -> list[InputRecord]:
    out = []
    for name, data in pkgs:
        p = read(data, name)
        out.append(InputRecord(name, "unitypackage", p.size, p.sha256, None, [p]))
    return out


def run(*pkgs: tuple[str, bytes], **opts) -> Analysis:
    return analyze(inputs(*pkgs), known.load(), Options(**opts))


def codes(a: Analysis | list[Finding]) -> list[str]:
    fs = a.findings if isinstance(a, Analysis) else a
    return [f.code for f in fs]


def only(a: Analysis, code: str) -> Finding:
    fs = [f for f in a.findings if f.code == code]
    assert len(fs) == 1, (code, codes(a))
    return fs[0]
