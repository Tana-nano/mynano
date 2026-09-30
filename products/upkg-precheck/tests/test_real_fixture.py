"""Optional: a real Unity export. Runs only when UPKG_REAL_FIXTURE_DIR points to a folder with
lilToon_1.7.0.unitypackage (https://github.com/lilxyzw/lilToon/releases/download/1.7.0/lilToon_1.7.0.unitypackage, MIT).
The file is not kept in the repository."""

import os
from pathlib import Path

import pytest
from up_helpers import codes
from upkg_precheck import known
from upkg_precheck.archive import Limits, read_input
from upkg_precheck.checks import analyze

FIXTURE = Path(os.environ.get("UPKG_REAL_FIXTURE_DIR", "/nonexistent")) / "lilToon_1.7.0.unitypackage"


@pytest.mark.skipif(not FIXTURE.is_file(), reason="UPKG_REAL_FIXTURE_DIR not set")
def test_real_liltoon_1_7_0():
    rec = read_input(FIXTURE, Limits())
    (pkg,) = rec.packages
    assert len(pkg.entries) == 370 and len(pkg.entries) - len(pkg.files()) == 18
    a = analyze([rec], known.load())
    assert not {"P01", "P02", "P03", "P14", "P04", "P22"} & set(codes(a))
    assert "P07" in codes(a)
    assert all(m is not None and m.exact for m in a.matches[pkg.name].values())
