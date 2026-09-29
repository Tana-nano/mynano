"""Follow the VRChat log that is actually being written.

The file with the newest modification time wins (not the newest name): with two
VRChat clients the older-named file may still be the live one, and a closed
client's log stops changing (cf. OyasumiVR issue #275).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .logparse import LogEvent, LogParser

LOG_GLOB = "output_log_*.txt"
FORMAT_WARN_AFTER = timedelta(minutes=60)


@dataclass
class _FileState:
    offset: int = 0
    pending: bytes = b""
    opened_at: datetime | None = None
    lines: int = 0
    matches: int = 0


@dataclass
class LogTailer:
    directory: Path
    parser: LogParser
    current: Path | None = None
    _files: dict[Path, _FileState] = field(default_factory=dict)
    _warned: set[Path] = field(default_factory=set)

    def newest_file(self) -> Path | None:
        if not self.directory.is_dir():
            return None
        candidates = []
        for p in self.directory.glob(LOG_GLOB):
            try:
                candidates.append((p.stat().st_mtime, p.name, p))
            except OSError:
                continue
        return max(candidates)[2] if candidates else None

    def poll(self, now: datetime) -> list[LogEvent]:
        newest = self.newest_file()
        if newest is None:
            return []
        self.current = newest
        state = self._files.setdefault(newest, _FileState(opened_at=now))
        try:
            with newest.open("rb") as f:
                f.seek(state.offset)
                chunk = f.read()
        except OSError:
            return []
        if not chunk:
            return []
        state.offset += len(chunk)
        data = state.pending + chunk
        *complete, state.pending = data.split(b"\n")
        events: list[LogEvent] = []
        for raw in complete:
            line = raw.decode("utf-8", errors="replace")
            if not line.strip():
                continue
            state.lines += 1
            ev = self.parser.parse(line)
            if ev is not None:
                state.matches += 1
                events.append(ev)
        return events

    def format_warning_due(self, now: datetime) -> bool:
        """True once per file if it has been read for an hour with lines but no match."""
        if self.current is None or self.current in self._warned:
            return False
        s = self._files.get(self.current)
        if s is None or s.opened_at is None or s.lines == 0 or s.matches:
            return False
        if now - s.opened_at >= FORMAT_WARN_AFTER:
            self._warned.add(self.current)
            return True
        return False
