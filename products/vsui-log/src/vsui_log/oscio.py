"""OSC in/out with a minimal OSCQuery service.

VRChat finds OSCQuery apps over mDNS (``_oscjson._tcp``), reads ``/?HOST_INFO``
for the UDP port and ``/`` for the address space, and sends ``/avatar/*`` and
``/tracking/vrsystem/*`` to apps that expose those paths. This lets us run next
to OyasumiVR without fighting over port 9001.
(github.com/vrchat-community/osc/wiki/OSCQuery, vrc-oscquery-lib Readme)
"""

from __future__ import annotations

import json
import logging
import random
import socket
import threading
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

log = logging.getLogger(__name__)

HEAD_POSE = "/tracking/vrsystem/head/pose"
AFK = "/avatar/parameters/AFK"
VRMODE = "/avatar/parameters/VRMode"
OUT_SLEEPING = "/avatar/parameters/VsuiLog/Sleeping"
OUT_VISITORS = "/avatar/parameters/VsuiLog/Visitors"
CHATBOX = "/chatbox/input"

LOOPBACK = "127.0.0.1"


class PortInUse(Exception):
    def __init__(self, port: int) -> None:
        super().__init__(port)
        self.port = port


@dataclass
class Handlers:
    pose: Callable[[datetime, tuple], None]
    afk: Callable[[datetime, Any], None]
    vrmode: Callable[[datetime, Any], None]
    oyasumi: Callable[[datetime, Any], None] | None = None
    oyasumi_address: str | None = None


def build_dispatcher(h: Handlers, clock: Callable[[], datetime]) -> Dispatcher:
    d = Dispatcher()
    d.map(HEAD_POSE, lambda _addr, *args: h.pose(clock(), args))
    d.map(AFK, lambda _addr, *args: args and h.afk(clock(), args[0]))
    d.map(VRMODE, lambda _addr, *args: args and h.vrmode(clock(), args[0]))
    if h.oyasumi and h.oyasumi_address:
        d.map(h.oyasumi_address, lambda _addr, *args: args and h.oyasumi(clock(), args[0]))
    d.set_default_handler(lambda *_: None)
    return d


def address_space() -> dict[str, Any]:
    """OSCQuery root: expose /avatar and /tracking/vrsystem so VRChat sends them to us."""
    return {
        "DESCRIPTION": "root node",
        "FULL_PATH": "/",
        "ACCESS": 0,
        "CONTENTS": {
            "avatar": {
                "FULL_PATH": "/avatar",
                "ACCESS": 2,
                "CONTENTS": {"change": {"FULL_PATH": "/avatar/change", "ACCESS": 2, "TYPE": "s"}},
            },
            "tracking": {
                "FULL_PATH": "/tracking",
                "ACCESS": 0,
                "CONTENTS": {"vrsystem": {"FULL_PATH": "/tracking/vrsystem", "ACCESS": 2, "CONTENTS": {}}},
            },
        },
    }


def host_info(name: str, osc_port: int) -> dict[str, Any]:
    return {
        "NAME": name,
        "OSC_IP": LOOPBACK,
        "OSC_PORT": osc_port,
        "OSC_TRANSPORT": "UDP",
        "EXTENSIONS": {"ACCESS": True, "VALUE": True, "DESCRIPTION": True},
    }


def _lookup(root: dict[str, Any], path: str) -> dict[str, Any] | None:
    node = root
    for part in [p for p in path.split("/") if p]:
        node = (node.get("CONTENTS") or {}).get(part)
        if node is None:
            return None
    return node


def make_http_handler(name: str, osc_port: int) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path, _, query = self.path.partition("?")
            if query.startswith("HOST_INFO"):
                body: dict[str, Any] | None = host_info(name, osc_port)
            else:
                body = _lookup(address_space(), path or "/")
            if body is None:
                self.send_error(404)
                return
            data = json.dumps(body).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *_: Any) -> None:
            pass

    return Handler


Advertiser = Callable[[str, int, int], Callable[[], None]]


def zeroconf_advertise(name: str, http_port: int, osc_port: int) -> Callable[[], None]:
    """Announce _oscjson._tcp and _osc._udp on mDNS. Returns a closer."""
    from zeroconf import ServiceInfo, Zeroconf

    zc = Zeroconf()
    # UNVERIFIED: VRChat on Windows discovering a loopback-advertised service.
    addr = [socket.inet_aton(LOOPBACK)]
    infos = [
        ServiceInfo("_oscjson._tcp.local.", f"{name}._oscjson._tcp.local.", addresses=addr, port=http_port,
                    properties={"txtvers": "1"}, server=f"{name}.local."),
        ServiceInfo("_osc._udp.local.", f"{name}._osc._udp.local.", addresses=addr, port=osc_port,
                    properties={"txtvers": "1"}, server=f"{name}.local."),
    ]
    for info in infos:
        zc.register_service(info)

    def close() -> None:
        for info in infos:
            try:
                zc.unregister_service(info)
            except Exception:  # pragma: no cover - best effort on shutdown
                pass
        zc.close()

    return close


def set_exclusive(sock: socket.socket) -> None:
    """Refuse to share the port. Windows otherwise lets 127.0.0.1 be bound over another
    app's 0.0.0.0 on the same port, silently taking its OSC traffic."""
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        # UNVERIFIED: behaviour on real Windows with another OSC app on the port.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # type: ignore[attr-defined]


class ExclusiveUDPServer(ThreadingOSCUDPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        set_exclusive(self.socket)
        super().server_bind()


def _udp_server(port: int, dispatcher: Dispatcher) -> ThreadingOSCUDPServer:
    try:
        return ExclusiveUDPServer((LOOPBACK, port), dispatcher)
    except OSError:
        raise PortInUse(port) from None


class OscReceiver:
    """Starts the UDP listener(s) and, in oscquery/auto mode, the OSCQuery service."""

    def __init__(
        self,
        dispatcher: Dispatcher,
        mode: str = "auto",
        listen_port: int = 9001,
        direct_port: int = 9010,
        advertise: Advertiser | None = zeroconf_advertise,
        on_warning: Callable[[str], None] | None = None,
    ) -> None:
        self.dispatcher = dispatcher
        self.requested_mode = mode
        self.listen_port = listen_port
        self.direct_port = direct_port
        self.advertise = advertise
        self.active_mode: str | None = None
        self.osc_port: int | None = None
        self.http_port: int | None = None
        self.direct_active = False
        self.warnings: list[str] = []
        self.on_warning = on_warning
        self._adv_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.name = f"VsuiLog-{random.randint(1000, 9999)}"
        self._servers: list[Any] = []
        self._closers: list[Callable[[], None]] = []

    def _warn(self, msg: str) -> None:
        self.warnings.append(msg)
        if self.on_warning:
            self.on_warning(msg)

    def _serve(self, server: Any) -> None:
        self._servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def _start_oscquery(self) -> None:
        udp = _udp_server(0, self.dispatcher)
        self.osc_port = udp.server_address[1]
        try:
            http = ThreadingHTTPServer((LOOPBACK, 0), make_http_handler(self.name, self.osc_port))
        except OSError:
            udp.server_close()
            raise
        self.http_port = http.server_address[1]
        self._serve(udp)
        self._serve(http)
        self.active_mode = "oscquery"
        if self.advertise is not None:
            # mDNS probing takes seconds; don't block startup on it.
            self._adv_thread = threading.Thread(target=self._advertise, daemon=True)
            self._adv_thread.start()

    def _advertise(self) -> None:
        assert self.advertise is not None and self.http_port and self.osc_port
        try:
            close = self.advertise(self.name, self.http_port, self.osc_port)
        except Exception as e:
            log.warning("mDNS advertisement failed: %s", e)
            if self.requested_mode == "auto":
                try:
                    with self._lock:
                        self._start_fixed()
                    self._warn("OSCQuery を開始できなかったため、固定ポートで受信します")
                except PortInUse as p:
                    self._warn(f"OSCQuery も固定ポート {p.port} も使えません。他の OSC アプリを確認してください")
            else:
                self._warn("OSCQuery を開始できませんでした（mDNS）。osc.mode = \"auto\" か \"fixed\" を試してください")
            return
        with self._lock:
            self._closers.append(close)

    def ready(self, timeout: float = 10.0) -> "OscReceiver":
        """Wait for the background mDNS advertisement to finish (tests / doctor)."""
        if self._adv_thread is not None:
            self._adv_thread.join(timeout)
        return self

    def _start_fixed(self) -> None:
        udp = _udp_server(self.listen_port, self.dispatcher)
        self.osc_port = self.listen_port
        self._serve(udp)
        self.active_mode = "fixed"

    def start(self) -> "OscReceiver":
        mode = self.requested_mode
        if mode == "fixed":
            self._start_fixed()
        elif mode == "oscquery":
            self._start_oscquery()
        else:
            try:
                self._start_oscquery()
            except Exception as e:
                log.warning("OSCQuery unavailable (%s); falling back to fixed port", e)
                self._warn("OSCQuery を開始できなかったため、固定ポートで受信します")
                self._start_fixed()
        if self.direct_port:
            try:
                self._serve(_udp_server(self.direct_port, self.dispatcher))
                self.direct_active = True
            except PortInUse:
                self._warn(f"直送用ポート {self.direct_port} は使用中のため無効にしました")
        return self

    def stop(self) -> None:
        if self._adv_thread is not None:
            self._adv_thread.join(5)
        for close in self._closers:
            try:
                close()
            except Exception:  # pragma: no cover
                pass
        for s in self._servers:
            s.shutdown()
            s.server_close()
        self._servers.clear()
        self._closers.clear()


class OscSender:
    def __init__(self, host: str, port: int, send_parameters: bool = True) -> None:
        self.client = SimpleUDPClient(host, port)
        self.send_parameters = send_parameters

    def sleeping(self, value: bool) -> None:
        if self.send_parameters:
            self.client.send_message(OUT_SLEEPING, bool(value))

    def visitors(self, count: int) -> None:
        if self.send_parameters:
            self.client.send_message(OUT_VISITORS, int(max(0, min(255, count))))

    def chatbox(self, text: str) -> None:
        self.client.send_message(CHATBOX, [text, True, False])
