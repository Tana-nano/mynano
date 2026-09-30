"""Fake VRChat OSC endpoint.

Real VRChat (docs.vrchat.com/docs/osc-overview):
- listens on UDP 9000 for messages from external apps
- sends avatar parameter changes etc. to UDP 9001
- avatar parameters live at ``/avatar/parameters/<Name>`` (int / float / bool)
- chatbox: ``/chatbox/input`` with (string text, bool send_immediately, bool notify)

``FakeVRChat`` plays the VRChat side: it records what the product sends and
can emit parameter updates the way VRChat would. Ports are configurable so
tests can pick free ones and run in parallel.
"""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

AVATAR_PARAM_PREFIX = "/avatar/parameters/"
HEAD_POSE = "/tracking/vrsystem/head/pose"
CHATBOX_INPUT = "/chatbox/input"
CHATBOX_TYPING = "/chatbox/typing"


def free_udp_port() -> int:
    """Return a UDP port that is currently free on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@dataclass
class OscMessage:
    address: str
    args: tuple[Any, ...]
    received_at: float = field(default_factory=time.monotonic)


class OscRecorder:
    """Records every OSC message that arrives at ``listen_port``.

    Use this on the *product* side of a test when the product is supposed to
    receive messages from VRChat, or standalone to inspect traffic.
    """

    def __init__(self, listen_port: int | None = None, host: str = "127.0.0.1") -> None:
        self.host = host
        self.listen_port = listen_port or free_udp_port()
        self.messages: list[OscMessage] = []
        self._lock = threading.Lock()
        self._event = threading.Condition(self._lock)
        dispatcher = Dispatcher()
        dispatcher.set_default_handler(self._on_message)
        self._server = ThreadingOSCUDPServer((host, self.listen_port), dispatcher)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _on_message(self, address: str, *args: Any) -> None:
        with self._event:
            self.messages.append(OscMessage(address, tuple(args)))
            self._event.notify_all()

    def start(self) -> "OscRecorder":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()

    def __enter__(self) -> "OscRecorder":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def wait_for(self, address: str, timeout: float = 2.0) -> OscMessage | None:
        """Block until a message with ``address`` arrives (or timeout)."""
        deadline = time.monotonic() + timeout
        with self._event:
            while True:
                for m in self.messages:
                    if m.address == address:
                        return m
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return None
                self._event.wait(remaining)

    def messages_for(self, address: str) -> list[OscMessage]:
        with self._lock:
            return [m for m in self.messages if m.address == address]

    def clear(self) -> None:
        with self._lock:
            self.messages.clear()


class FakeVRChat(OscRecorder):
    """The VRChat side of an OSC conversation.

    - ``in_port``: where the product sends (real VRChat: 9000). We listen here.
    - ``out_port``: where the product listens (real VRChat: 9001). We send here.
    """

    def __init__(
        self,
        in_port: int | None = None,
        out_port: int | None = None,
        host: str = "127.0.0.1",
    ) -> None:
        super().__init__(listen_port=in_port, host=host)
        self.out_port = out_port or free_udp_port()
        self._client = SimpleUDPClient(host, self.out_port)
        self.parameters: dict[str, Any] = {}

    @property
    def in_port(self) -> int:
        return self.listen_port

    def retarget(self, out_port: int) -> None:
        """Send to a different port (e.g. one the app announced via OSCQuery)."""
        self.out_port = out_port
        self._client = SimpleUDPClient(self.host, out_port)

    # --- things VRChat does ---------------------------------------------

    def set_parameter(self, name: str, value: bool | int | float) -> None:
        """Emit an avatar parameter change like VRChat does."""
        self.parameters[name] = value
        self._client.send_message(AVATAR_PARAM_PREFIX + name, value)

    def send_head_pose(self, x: float, y: float, z: float, rx: float, ry: float, rz: float) -> None:
        """Emit ``/tracking/vrsystem/head/pose`` (position XYZ, euler XYZ) like VRChat."""
        self._client.send_message(HEAD_POSE, [float(x), float(y), float(z), float(rx), float(ry), float(rz)])

    def play_pose(self, samples: "list[tuple[float, float, float, float, float, float]]", rate_hz: float = 0) -> None:
        """Send a pose series. ``rate_hz=0`` sends as fast as possible."""
        for s in samples:
            self.send_head_pose(*s)
            if rate_hz:
                time.sleep(1.0 / rate_hz)

    def send(self, address: str, *args: Any) -> None:
        """Send an arbitrary OSC message to the product."""
        self._client.send_message(address, list(args) if len(args) != 1 else args[0])

    # --- inspecting what the product sent to VRChat -----------------------

    def received_parameters(self) -> dict[str, Any]:
        """Latest value per avatar parameter the product sent us."""
        out: dict[str, Any] = {}
        with self._lock:
            for m in self.messages:
                if m.address.startswith(AVATAR_PARAM_PREFIX) and m.args:
                    out[m.address[len(AVATAR_PARAM_PREFIX):]] = m.args[0]
        return out

    def chatbox_texts(self) -> list[str]:
        """Texts the product pushed to the chatbox, in order."""
        return [str(m.args[0]) for m in self.messages_for(CHATBOX_INPUT) if m.args]
