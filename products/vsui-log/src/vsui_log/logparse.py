"""Parse VRChat ``output_log_*.txt`` lines into events.

Line shape (per VRCX Dotnet/LogWatcher.cs; not officially documented):
    2026.09.29 23:41:07 Log        -  [Behaviour] OnPlayerJoined Name (usr_...)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Mapping

LINE_RE = re.compile(r"^(?P<ts>\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\s+(?P<level>\S+)\s+-\s+(?P<msg>.*)$")
TS_FMT = "%Y.%m.%d %H:%M:%S"

_NAME = r"(?P<name>.+?)(?: \((?P<user_id>usr_[0-9a-fA-F-]+)\))?$"
DEFAULT_PATTERNS: dict[str, str] = {
    "joining": r"^\[Behaviour\] Joining (?P<location>wrld_\S+)",
    "entering_room": r"^\[Behaviour\] Entering Room: (?P<world_name>.+)$",
    "player_joined": r"^\[Behaviour\] OnPlayerJoined " + _NAME,
    "player_left": r"^\[Behaviour\] OnPlayerLeft " + _NAME,
    "left_room": r"^\[Behaviour\] OnLeftRoom",
    # UNVERIFIED: the exact authentication line in current clients.
    "authenticated": r"^\[Behaviour\] User Authenticated: " + _NAME,
}

ACCESS_KINDS = ("private", "friends", "hidden", "group")


@dataclass(frozen=True)
class LogEvent:
    kind: str
    ts: datetime
    name: str | None = None
    user_id: str | None = None
    location: str | None = None
    world_name: str | None = None


@dataclass(frozen=True)
class Location:
    world_id: str
    instance_id: str
    access: str


def parse_location(location: str) -> Location:
    world_id, _, rest = location.partition(":")
    parts = rest.split("~")
    instance_id = parts[0]
    access = "public"
    for part in parts[1:]:
        head = part.split("(", 1)[0]
        if head in ACCESS_KINDS:
            access = head
            break
    return Location(world_id, instance_id, access)


class LogParser:
    def __init__(self, overrides: Mapping[str, str] | None = None) -> None:
        patterns = dict(DEFAULT_PATTERNS)
        for key, value in (overrides or {}).items():
            if value:
                patterns[key] = value
        self.patterns = {k: re.compile(v) for k, v in patterns.items()}

    def parse(self, line: str) -> LogEvent | None:
        line = line.lstrip("﻿").rstrip("\r\n")
        m = LINE_RE.match(line)
        if not m:
            return None
        msg = m.group("msg")
        for kind, rx in self.patterns.items():
            hit = rx.search(msg)
            if not hit:
                continue
            try:
                ts = datetime.strptime(m.group("ts"), TS_FMT)
            except ValueError:
                return None
            g = hit.groupdict()
            return LogEvent(
                kind=kind,
                ts=ts,
                name=(g.get("name") or "").strip() or None,
                user_id=g.get("user_id") or None,
                location=g.get("location"),
                world_name=(g.get("world_name") or "").strip() or None,
            )
        return None
