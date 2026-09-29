"""Mock VRChat for tests.

Two pieces:

- ``osc``: a fake VRChat OSC endpoint. It *receives* on the port real VRChat
  listens on (default 9000) and *sends* to the port real VRChat sends to
  (default 9001), so a product under test talks to it exactly as it would
  talk to VRChat.
- ``log``: a generator/appender for ``output_log_*.txt`` lines in the format
  VRChat writes, so log-watching code can be exercised without the game.

Everything here runs on Linux with no VRChat, Unity or SteamVR.
"""

from .log import LogWriter, format_line, join_lines, player_joined, player_left, left_room
from .osc import FakeVRChat, OscRecorder, free_udp_port
from .oscquery import OscQueryProbe, ProbeResult

__all__ = [
    "FakeVRChat",
    "OscRecorder",
    "OscQueryProbe",
    "ProbeResult",
    "free_udp_port",
    "LogWriter",
    "format_line",
    "join_lines",
    "player_joined",
    "player_left",
    "left_room",
]
