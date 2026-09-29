"""VRChat ``output_log_*.txt`` generator.

Line format (as parsed by VRCX ``Dotnet/LogWatcher.cs`` and other community
tools; VRChat does not document it officially, so treat as UNVERIFIED against
the very latest client and keep ``shared/fixtures/output_log_sample.txt``
updated from a real log when possible):

    2026.09.29 23:41:07 Log        -  [Behaviour] OnPlayerJoined Natsumi-sama (usr_...)
    2026.09.29 23:41:07 Log        -  [Behaviour] OnPlayerLeft Rize (usr_...)
    2026.09.29 23:40:59 Log        -  [Behaviour] Joining wrld_<id>:12345~private(usr_<id>)~region(jp)
    2026.09.29 23:40:59 Log        -  [Behaviour] Entering Room: VRChat Home
    2026.09.29 23:59:01 Log        -  [Behaviour] OnLeftRoom

File name: ``output_log_YYYY-MM-DD_HH-MM-SS.txt`` under
``%LOCALAPPDATA%Low\\VRChat\\VRChat\\`` on Windows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

TIMESTAMP_FMT = "%Y.%m.%d %H:%M:%S"
_LEVEL_PAD = {"Log": "Log        ", "Warning": "Warning    ", "Error": "Error      "}


def format_line(ts: datetime, message: str, level: str = "Log") -> str:
    return f"{ts.strftime(TIMESTAMP_FMT)} {_LEVEL_PAD.get(level, level.ljust(11))}-  {message}"


def player_joined(ts: datetime, display_name: str, user_id: str | None = None) -> str:
    suffix = f" ({user_id})" if user_id else ""
    return format_line(ts, f"[Behaviour] OnPlayerJoined {display_name}{suffix}")


def player_left(ts: datetime, display_name: str, user_id: str | None = None) -> str:
    suffix = f" ({user_id})" if user_id else ""
    return format_line(ts, f"[Behaviour] OnPlayerLeft {display_name}{suffix}")


def join_lines(
    ts: datetime,
    world_id: str,
    instance_id: str,
    world_name: str,
    owner_user_id: str | None = None,
    access: str = "private",
    region: str = "jp",
) -> list[str]:
    """The pair of lines VRChat writes when entering an instance."""
    owner = f"({owner_user_id})" if owner_user_id else ""
    location = f"{world_id}:{instance_id}~{access}{owner}~region({region})"
    return [
        format_line(ts, f"[Behaviour] Joining {location}"),
        format_line(ts, f"[Behaviour] Entering Room: {world_name}"),
    ]


def left_room(ts: datetime) -> str:
    return format_line(ts, "[Behaviour] OnLeftRoom")


def log_filename(started: datetime) -> str:
    return f"output_log_{started.strftime('%Y-%m-%d_%H-%M-%S')}.txt"


class LogWriter:
    """Append VRChat-shaped lines to a log file, advancing a fake clock.

    Example::

        w = LogWriter(tmp_path, start=datetime(2026, 9, 29, 23, 0))
        w.join("wrld_x", "1234", "Sleep World")
        w.player_joined("Alice", "usr_a")
        w.advance(minutes=30)
        w.player_left("Alice", "usr_a")
    """

    def __init__(self, directory: Path, start: datetime | None = None, encoding: str = "utf-8") -> None:
        self.now = start or datetime.now()
        self.path = Path(directory) / log_filename(self.now)
        self.encoding = encoding
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch()

    def advance(self, **delta: float) -> None:
        self.now += timedelta(**delta)

    def write(self, *lines: str) -> None:
        with self.path.open("a", encoding=self.encoding, newline="\n") as f:
            for line in lines:
                f.write(line + "\n")

    def raw(self, message: str, level: str = "Log") -> None:
        self.write(format_line(self.now, message, level))

    def join(self, world_id: str, instance_id: str, world_name: str, **kw: str) -> None:
        self.write(*join_lines(self.now, world_id, instance_id, world_name, **kw))

    def player_joined(self, display_name: str, user_id: str | None = None) -> None:
        self.write(player_joined(self.now, display_name, user_id))

    def player_left(self, display_name: str, user_id: str | None = None) -> None:
        self.write(player_left(self.now, display_name, user_id))

    def leave(self) -> None:
        self.write(left_room(self.now))
