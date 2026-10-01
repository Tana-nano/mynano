"""Parse Unity's Editor.log line by line.

UNVERIFIED: no real Editor.log has been seen. Line shapes come from public forum posts; every
pattern is a partial (search) match so that prefixes such as '[Error] 12:34:56 ' do not break it.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .rules import Rules

LOG_LIMIT_BYTES = 50 * 1024 * 1024
HEAD_LINES = 200
SAMPLE_LIMIT = 20
MAX_MISSING_TYPES = 20
CATEGORIES = ("assets", "sdk", "other")

_PROJECT_INLINE = re.compile(r'-projectpath\s+(?:"([^"]+)"|(\S+))', re.IGNORECASE)
_PROJECT_ALONE = re.compile(r"^\s*-projectpath\s*$", re.IGNORECASE)
_QUOTED = re.compile(r"'([^']+)'")
# A type-like word ending in Exception/Error, but not a file name such as '.../VRCApiError.cs'.
_UNCLASSIFIED = re.compile(r"(?<![/\\\w])(\w+(?:Exception|Error))\b(?!\.\w)")
# Asset import records ('Start importing Packages/.../IError.cs using Guid(...)') are not errors;
# seen in a real Windows Editor.log for every script on a project's first import.
_IMPORT_RECORD = re.compile(r"^\s*Start importing ")
FILE_LIMIT = 200
_BARE_CS_ERROR = re.compile(r"\berror (CS\d+)\b")
# Seen in a real Windows Editor.log after a script was deleted while Unity still listed it.
_SOURCE_GONE = re.compile(r"\berror CS2001: Source file '([^']+)' could not be found")
_STACK = re.compile(r"^\s+at\s")


@dataclass
class CompileGroup:
    unique: int = 0
    total: int = 0
    samples: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)  # distinct file paths as written in the log


@dataclass
class RuleHit:
    count: int = 0
    samples: list[str] = field(default_factory=list)


@dataclass
class LogFacts:
    path: Path
    found: bool = False
    unreadable: bool = False
    mtime: datetime | None = None
    lines: int = 0
    truncated: bool = False
    project_match: str = "unknown"  # match | mismatch | unknown
    compile: dict[str, CompileGroup] = field(default_factory=lambda: {c: CompileGroup() for c in CATEGORIES})
    packagecache: bool = False
    other_packages: bool = False
    missing_types: list[str] = field(default_factory=list)
    rule_hits: dict[str, RuleHit] = field(default_factory=dict)
    unclassified: dict[str, list] = field(default_factory=dict)  # kind -> [count, first line]
    missing_sources: list[str] = field(default_factory=list)  # paths from 'error CS2001'
    log_project: str | None = None  # the -projectPath value written at the top of the log

    @property
    def compile_unique(self) -> int:
        return sum(g.unique for g in self.compile.values())


def normalize_path(p: str) -> str:
    return p.strip().strip('"').replace("\\", "/").rstrip("/").casefold()


def origin_of(file: str) -> str:
    f = file.replace("\\", "/")
    low = f.casefold()
    if low.startswith("assets/vrcsdk/") or low.startswith("packages/com.vrchat."):
        return "sdk"
    if low.startswith("assets/"):
        return "assets"
    return "other"


def missing_name(code: str, msg: str) -> str | None:
    q = _QUOTED.findall(msg)
    if not q:
        return None
    if code.upper() == "CS0234" and len(q) >= 2:
        # "The type or namespace name 'X' does not exist in the namespace 'Y'" -> Y.X
        return f"{q[1]}.{q[0]}"
    return q[0]


class _NearTracker:
    """Main pattern on line i counts only if the 'near' pattern is within N lines (either side)."""

    def __init__(self, n: int):
        self.n = n
        self.last_near: int | None = None
        self.pending: deque[tuple[int, str]] = deque()

    def feed(self, i: int, line: str, main: bool, near: bool) -> list[str]:
        confirmed: list[str] = []
        while self.pending and i - self.pending[0][0] > self.n:
            self.pending.popleft()
        if near:
            self.last_near = i
            confirmed.extend(text for _, text in self.pending)
            self.pending.clear()
        if main:
            if self.last_near is not None and i - self.last_near <= self.n:
                confirmed.append(line)
            else:
                self.pending.append((i, line))
        return confirmed


def parse(
    path: Path,
    rules: Rules,
    project_root: Path | None = None,
    limit_bytes: int = LOG_LIMIT_BYTES,
) -> LogFacts:
    facts = LogFacts(path=path)
    try:
        st = path.stat()
    except FileNotFoundError:
        return facts
    except OSError:
        facts.found = True
        facts.unreadable = True
        return facts
    facts.found = True
    facts.mtime = datetime.fromtimestamp(st.st_mtime)

    trackers = {r.id: _NearTracker(r.near_lines) for r in rules.log_rules if r.near is not None}
    seen_errors: dict[tuple[str, str, str, str], str] = {}
    missing_seen: set[str] = set()
    project_arg: str | None = None
    expect_project_value = False
    target = normalize_path(str(project_root)) if project_root is not None else None

    def hit(rule_id: str, text: str) -> None:
        h = facts.rule_hits.setdefault(rule_id, RuleHit())
        h.count += 1
        if len(h.samples) < SAMPLE_LIMIT:
            h.samples.append(text)

    try:
        # UNVERIFIED: whether Windows lets us read Editor.log while Unity holds it open.
        with path.open("rb") as fh:
            if st.st_size > limit_bytes:
                fh.seek(st.st_size - limit_bytes)
                fh.readline()  # drop the partial first line
                facts.truncated = True
            for i, raw in enumerate(fh):
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                facts.lines += 1

                if i < HEAD_LINES and project_arg is None and not facts.truncated:
                    # UNVERIFIED: that Unity writes its command line (with -projectPath) at the top of the log.
                    if expect_project_value and line.strip():
                        project_arg = line.strip().strip('"')
                    elif m := _PROJECT_INLINE.search(line):
                        project_arg = m.group(1) or m.group(2)
                    expect_project_value = project_arg is None and (
                        bool(_PROJECT_ALONE.match(line)) or (expect_project_value and not line.strip())
                    )

                matched = False
                if m := rules.compile_error.search(line):
                    matched = True
                    file, ln, col, code, msg = (m.group(g) for g in ("file", "line", "col", "code", "msg"))
                    key = (file.replace("\\", "/"), ln, col, code.upper())
                    cat = origin_of(file)
                    group = facts.compile[cat]
                    group.total += 1
                    if key not in seen_errors:
                        seen_errors[key] = cat
                        group.unique += 1
                        if len(group.samples) < SAMPLE_LIMIT:
                            group.samples.append(f"{file}({ln},{col}) error {code}: {msg}")
                        if file not in group.files and len(group.files) < FILE_LIMIT:
                            group.files.append(file)
                        if cat == "other":
                            if file.replace("\\", "/").casefold().startswith("library/packagecache/"):
                                facts.packagecache = True
                            else:
                                facts.other_packages = True
                        if code.upper() in ("CS0246", "CS0234"):
                            name = missing_name(code, msg)
                            if name and name.casefold() not in missing_seen and len(facts.missing_types) < MAX_MISSING_TYPES:
                                missing_seen.add(name.casefold())
                                facts.missing_types.append(name)

                for r in rules.log_rules:
                    main = bool(r.regex.search(line))
                    if r.near is None:
                        if main:
                            matched = True
                            hit(r.id, line)
                        continue
                    near = bool(r.near.search(line))
                    if main:
                        matched = True
                    for text in trackers[r.id].feed(i, line, main, near):
                        hit(r.id, text)

                if not matched and not _STACK.match(line) and not _IMPORT_RECORD.match(line):
                    kind = None
                    if m := _SOURCE_GONE.search(line):
                        if m.group(1) not in facts.missing_sources and len(facts.missing_sources) < SAMPLE_LIMIT:
                            facts.missing_sources.append(m.group(1))
                        continue
                    if m := _BARE_CS_ERROR.search(line):
                        kind = f"error {m.group(1)}"
                    elif m := _UNCLASSIFIED.search(line):
                        kind = m.group(1)
                    if kind:
                        entry = facts.unclassified.setdefault(kind, [0, line])
                        entry[0] += 1
    except OSError:
        facts.unreadable = True
        return facts

    facts.log_project = project_arg
    if project_arg is not None and target is not None:
        facts.project_match = "match" if normalize_path(project_arg) == target else "mismatch"
    return facts
