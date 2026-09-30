"""Expand command-line inputs and read zips / unitypackages into records (no disk writes)."""

from __future__ import annotations

import hashlib
import io
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .unitypackage import Budget, BudgetExceeded, Package, read_unitypackage

SUPPORTED = (".zip", ".unitypackage")
UTF8_FLAG = 0x800
ENCRYPTED_FLAG = 0x1
CHUNK = 1 << 20


@dataclass
class ZipMember:
    name: str  # decoded path inside the zip (nested: "inner.zip/x")
    size: int


@dataclass
class ZipRecord:
    name: str
    broken: list[str] = field(default_factory=list)  # Z01: the zip itself or a nested zip
    sjis_names: list[str] = field(default_factory=list)  # Z05 (re-decoded as cp932)
    garbled_names: list[str] = field(default_factory=list)  # Z05 (could not re-decode)
    unreadable: list[str] = field(default_factory=list)  # Z06: password or unsupported compression
    budget_exceeded: bool = False  # Z07
    packages: list[ZipMember] = field(default_factory=list)
    files: list[ZipMember] = field(default_factory=list)  # everything else (incl. nested zips)


@dataclass
class InputRecord:
    name: str  # file name only (never the full path: it contains the Windows user name)
    kind: str  # "zip" | "unitypackage"
    size: int = 0
    sha256: str = ""
    zip: ZipRecord | None = None
    packages: list[Package] = field(default_factory=list)


@dataclass
class Limits:
    max_text_bytes: int = 64 << 20
    max_read_bytes: int = 8192 << 20
    zip_depth: int = 2


def expand_inputs(args: list[str]) -> tuple[list[Path], list[str]]:
    """Files to read, and user-facing messages for skipped arguments."""
    files: list[Path] = []
    messages: list[str] = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            found = sorted((f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED),
                           key=lambda f: f.as_posix().lower())
            if not found:
                messages.append(f"{p.name}: zip も unitypackage も見つかりませんでした")
            files += found
        elif p.is_file():
            if p.suffix.lower() in SUPPORTED:
                files.append(p)
            else:
                messages.append(f"{p.name}: 対応していない形式です（zip か unitypackage を指定してください）")
        else:
            messages.append(f"{a}: 見つかりません")
    return files, messages


def decode_member_name(info: zipfile.ZipInfo) -> tuple[str, str]:
    """(name, status) where status is "" | "sjis" | "garbled".

    Names without the UTF-8 flag are decoded as cp437 by zipfile; Japanese Windows writes
    them in cp932, so re-decode. orig_filename keeps 0x5C bytes that zipfile may turn into "/".
    """
    raw = info.orig_filename
    # UNVERIFIED: tested with zips written by the tests, not by real Japanese Windows zippers.
    if info.flag_bits & UTF8_FLAG or raw.isascii():
        return raw.replace("\\", "/"), ""
    try:
        return raw.encode("cp437").decode("cp932").replace("\\", "/"), "sjis"
    except UnicodeError:
        return raw.replace("\\", "/"), "garbled"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def read_input(path: Path, limits: Limits) -> InputRecord:
    if path.suffix.lower() == ".unitypackage":
        rec = InputRecord(path.name, "unitypackage")
        with path.open("rb") as f:
            pkg = read_unitypackage(path.name, f, max_text_bytes=limits.max_text_bytes)
        rec.size, rec.sha256 = pkg.size, pkg.sha256
        rec.packages.append(pkg)
        return rec
    rec = InputRecord(path.name, "zip", size=path.stat().st_size, sha256=_sha256_file(path))
    rec.zip = ZipRecord(path.name)
    budget = Budget(limits.max_read_bytes)
    try:
        with zipfile.ZipFile(path) as zf:
            _read_zip(zf, "", 1, rec, limits, budget)
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError) as e:
        rec.zip.broken.append(f"{path.name}（{type(e).__name__}: {e}）")
    except BudgetExceeded:
        rec.zip.budget_exceeded = True
    return rec


def _read_zip(zf: zipfile.ZipFile, prefix: str, depth: int, rec: InputRecord, limits: Limits,
              budget: Budget) -> None:
    z = rec.zip
    assert z is not None
    for info in zf.infolist():
        if info.is_dir():
            continue
        name, status = decode_member_name(info)
        if name.endswith("/"):
            continue
        shown = prefix + name
        if status == "sjis":
            z.sjis_names.append(shown)
        elif status == "garbled":
            z.garbled_names.append(shown)
        low = name.lower()
        if info.flag_bits & ENCRYPTED_FLAG:
            z.unreadable.append(shown)
            z.files.append(ZipMember(shown, info.file_size))
            continue
        if low.endswith(".unitypackage"):
            try:
                f = zf.open(info)
            except NotImplementedError:
                # e.g. Deflate64, which Windows Explorer uses for large files; Python cannot read it.
                z.unreadable.append(shown)
                z.files.append(ZipMember(shown, info.file_size))
                continue
            z.packages.append(ZipMember(shown, info.file_size))
            with f:
                pkg = read_unitypackage(shown, f, max_text_bytes=limits.max_text_bytes, budget=budget)
            rec.packages.append(pkg)
            if pkg.budget_exceeded:
                raise BudgetExceeded()
            continue
        z.files.append(ZipMember(shown, info.file_size))
        if low.endswith(".zip") and depth < limits.zip_depth:
            data = bytearray()
            try:
                with zf.open(info) as f:
                    while chunk := f.read(CHUNK):
                        budget.take(len(chunk))
                        data += chunk
                with zipfile.ZipFile(io.BytesIO(bytes(data))) as inner:
                    _read_zip(inner, shown + "/", depth + 1, rec, limits, budget)
            except NotImplementedError:
                z.unreadable.append(shown)
            except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, ValueError, zlib.error) as e:
                z.broken.append(f"{shown}（{type(e).__name__}: {e}）")


def make_names_unique(inputs: list[InputRecord]) -> None:
    """Package names key the analysis; give duplicates a " (2)" suffix."""
    seen: Counter[str] = Counter()
    for r in inputs:
        for p in r.packages:
            seen[p.name] += 1
            if seen[p.name] > 1:
                p.name = f"{p.name} ({seen[p.name]})"
