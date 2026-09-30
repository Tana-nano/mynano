"""Read a .unitypackage (gzip tar) in one streaming pass, in memory, without extracting.

Layout: <guid>/pathname, <guid>/asset.meta, <guid>/asset (absent for folders), <guid>/preview.png.
Members of one GUID arrive in any order, so they are gathered per GUID and assembled at the end.
"""

from __future__ import annotations

import hashlib
import re
import tarfile
import zipfile
import zlib
from dataclasses import dataclass, field
from typing import BinaryIO

from . import refs as refs_mod
from .refs import Ref

GUID_RE = re.compile(r"^[0-9a-fA-F]{32}$")
META_GUID = re.compile(r"^guid:\s*([0-9a-fA-F]{32})\s*$", re.MULTILINE)
META_FOLDER = re.compile(r"^folderAsset:\s*yes\s*$", re.MULTILINE)
DRIVE_RE = re.compile(r"^[A-Za-z]:")
KNOWN_LEAVES = ("pathname", "asset.meta", "asset", "preview.png")
CHUNK = 1 << 20
TEXT_SNIFF = 8192
PATHNAME_MAX = 64 * 1024

# P10: facts worth showing about editor scripts (not a malware verdict).
SCRIPT_KEYWORDS = ("InitializeOnLoad", "Process.Start", "DllImport", "UnityWebRequest", "HttpClient", "WebClient")


class BudgetExceeded(Exception):
    pass


class Budget:
    """Total bytes allowed to be read from an input (zip bomb guard)."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.used = 0

    def take(self, n: int) -> None:
        self.used += n
        if self.used > self.limit:
            raise BudgetExceeded()


@dataclass
class Entry:
    guid: str
    pathname: str
    is_folder: bool
    size: int = 0
    sha256: str = ""
    refs: list[Ref] = field(default_factory=list)
    starts_yaml: bool = False
    textual: bool = False
    too_large: bool = False
    keywords: frozenset[str] = frozenset()

    @property
    def basename(self) -> str:
        return self.pathname.rsplit("/", 1)[-1]

    @property
    def ext(self) -> str:
        name = self.basename
        dot = name.rfind(".")
        return name[dot:].lower() if dot > 0 else ""


@dataclass
class Anomaly:
    code: str  # P01, P02, P03, P14
    detail: str


@dataclass
class Package:
    name: str
    entries: dict[str, Entry] = field(default_factory=dict)
    anomalies: list[Anomaly] = field(default_factory=list)
    root_files: int = 0
    size: int = 0
    sha256: str = ""
    budget_exceeded: bool = False

    @property
    def broken(self) -> bool:
        return any(a.code == "P01" for a in self.anomalies)

    def files(self) -> list[Entry]:
        return sorted((e for e in self.entries.values() if not e.is_folder), key=lambda e: e.pathname)


@dataclass
class _Asset:
    size: int
    sha256: str
    starts_yaml: bool
    textual: bool
    too_large: bool
    yaml_refs: list[Ref]
    asmdef_refs: list[Ref]
    keywords: frozenset[str]


@dataclass
class _Parts:
    pathname: str | None = None
    pathname_bad_utf8: bool = False
    meta: str | None = None
    asset: _Asset | None = None


class _HashingReader:
    def __init__(self, raw: BinaryIO, budget: Budget | None) -> None:
        self.raw = raw
        self.budget = budget
        self.hash = hashlib.sha256()
        self.size = 0

    def read(self, n: int = -1) -> bytes:
        data = self.raw.read(n)
        if data:
            if self.budget is not None:
                self.budget.take(len(data))
            self.hash.update(data)
            self.size += len(data)
        return data


def _read_capped(f: BinaryIO, cap: int) -> tuple[bytes, bool]:
    data = f.read(cap + 1)
    if len(data) > cap:
        while f.read(CHUNK):
            pass
        return data[:cap], True
    return data, False


def _read_asset(f: BinaryIO, max_text: int) -> _Asset:
    h = hashlib.sha256()
    size = 0
    buf: bytearray | None = None
    starts_yaml = textual = too_large = False
    first = True
    while chunk := f.read(CHUNK):
        h.update(chunk)
        size += len(chunk)
        if first:
            first = False
            starts_yaml = refs_mod.is_yaml(chunk[:16])
            textual = b"\0" not in chunk[:TEXT_SNIFF]
            if textual:
                buf = bytearray()
        if buf is not None:
            if len(buf) + len(chunk) > max_text:
                buf = None
                too_large = True
            else:
                buf += chunk
    yaml_refs: list[Ref] = []
    asmdef_refs: list[Ref] = []
    keywords: frozenset[str] = frozenset()
    if buf is not None:
        text = bytes(buf).decode("utf-8", errors="replace")
        if starts_yaml:
            yaml_refs = refs_mod.extract_yaml(text)
        else:
            asmdef_refs = refs_mod.extract_asmdef(text)
            keywords = frozenset(k for k in SCRIPT_KEYWORDS if k in text)
    return _Asset(size, h.hexdigest(), starts_yaml, textual, too_large, yaml_refs, asmdef_refs, keywords)


def is_unsafe_path(pathname: str) -> bool:
    if pathname.startswith(("/", "\\")) or DRIVE_RE.match(pathname):
        return True
    return any(seg == ".." for seg in re.split(r"[/\\]", pathname))


def read_unitypackage(name: str, raw: BinaryIO, *, max_text_bytes: int = 64 << 20,
                      budget: Budget | None = None) -> Package:
    pkg = Package(name)
    reader = _HashingReader(raw, budget)
    parts: dict[str, _Parts] = {}
    bad_dirs: set[str] = set()
    members = 0
    error: str | None = None
    try:
        with tarfile.open(fileobj=reader, mode="r|gz") as tf:  # type: ignore[call-overload]
            for m in tf:
                members += 1
                name_ = m.name.replace("\\", "/")
                # UNVERIFIED: only one real export (lilToon 1.7.0) was seen; it had no "./" prefix and no .icon.png.
                while name_.startswith("./"):
                    name_ = name_[2:]
                if m.isdir() or not name_:
                    continue
                if not m.isfile():
                    pkg.anomalies.append(Anomaly("P03", name_))
                    continue
                segs = name_.split("/")
                if len(segs) == 1:
                    pkg.root_files += 1  # e.g. .icon.png shown by the import dialog
                    continue
                if len(segs) != 2 or not GUID_RE.match(segs[0]):
                    if segs[0] not in bad_dirs:
                        bad_dirs.add(segs[0])
                        pkg.anomalies.append(Anomaly("P14", f"想定外のメンバー: {name_}"))
                    continue
                guid, leaf = segs[0].lower(), segs[1]
                p = parts.setdefault(guid, _Parts())
                f = tf.extractfile(m)
                if f is None:
                    continue
                if leaf == "pathname":
                    data, _ = _read_capped(f, PATHNAME_MAX)
                    try:
                        text = data.decode("utf-8")
                    except UnicodeDecodeError:
                        text = data.decode("utf-8", errors="replace")
                        p.pathname_bad_utf8 = True
                    p.pathname = text.split("\n", 1)[0].rstrip("\r")
                elif leaf == "asset.meta":
                    data, _ = _read_capped(f, max_text_bytes)
                    p.meta = data.decode("utf-8", errors="replace")
                elif leaf == "asset":
                    p.asset = _read_asset(f, max_text_bytes)
                elif leaf == "preview.png":
                    pass
                else:
                    pkg.anomalies.append(Anomaly("P14", f"想定外のメンバー: {name_}"))
    except BudgetExceeded:
        pkg.budget_exceeded = True
    except (tarfile.TarError, EOFError, OSError, zlib.error, ValueError, zipfile.BadZipFile) as e:
        error = f"{type(e).__name__}: {e}"
    if not pkg.budget_exceeded:
        try:
            while reader.read(CHUNK):
                pass
        except BudgetExceeded:
            pkg.budget_exceeded = True
        except (OSError, zlib.error, zipfile.BadZipFile):
            pass
    pkg.size, pkg.sha256 = reader.size, reader.hash.hexdigest()

    if error is not None:
        if members == 0:
            pkg.anomalies.append(Anomaly("P01", "unitypackage として読めません" + (f"（{error}）" if error else "")))
        else:
            pkg.anomalies.append(Anomaly("P01", f"途中で読めなくなりました（{error}）。読めたところまでで調べています"))
    elif members == 0 and not pkg.budget_exceeded:
        pkg.anomalies.append(Anomaly("P01", "中身が空です"))

    for guid in sorted(parts):
        _assemble(pkg, guid, parts[guid])
    return pkg


def _assemble(pkg: Package, guid: str, p: _Parts) -> None:
    if p.pathname is None:
        pkg.anomalies.append(Anomaly("P14", f"pathname がありません: {guid}"))
        return
    path = p.pathname
    if not path:
        pkg.anomalies.append(Anomaly("P14", f"pathname が空です: {guid}"))
        return
    if is_unsafe_path(path):
        pkg.anomalies.append(Anomaly("P02", path))
    elif not path.startswith(("Assets/", "Packages/")):
        pkg.anomalies.append(Anomaly("P14", f"Assets/ でも Packages/ でも始まりません: {path}"))
    if p.pathname_bad_utf8:
        pkg.anomalies.append(Anomaly("P14", f"pathname が UTF-8 ではありません: {path}"))
    if p.meta is not None:
        m = META_GUID.search(p.meta)
        if m and m.group(1).lower() != guid:
            pkg.anomalies.append(Anomaly("P14", f".meta の guid がフォルダ名と違います: {path}"))
    entry = Entry(guid, path, is_folder=p.asset is None)
    entry.refs = refs_mod.extract_yaml(p.meta) if p.meta else []
    a = p.asset
    if a is not None:
        entry.size, entry.sha256 = a.size, a.sha256
        entry.starts_yaml, entry.textual, entry.too_large = a.starts_yaml, a.textual, a.too_large
        entry.refs += a.yaml_refs
        if entry.ext in refs_mod.ASMDEF_EXTS:
            entry.refs += a.asmdef_refs
        if entry.ext == ".cs":
            entry.keywords = a.keywords
    pkg.entries[guid] = entry
