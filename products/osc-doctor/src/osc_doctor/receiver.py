"""Receive what VRChat sends, on the fixed port and via OSCQuery, and tally it."""

from __future__ import annotations

import logging
import random
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer

from . import oscquery

log = logging.getLogger(__name__)

TRACKING_PREFIX = "/tracking/vrsystem/"
VRMODE = "/avatar/parameters/VRMode"
AVATAR_CHANGE = "/avatar/change"
PARAM_PREFIX = "/avatar/parameters/"

ROUTE_FIXED = "fixed"
ROUTE_OSCQUERY = "oscquery"


def type_tag(v: Any) -> str:
    if isinstance(v, bool):
        return "T" if v else "F"
    if isinstance(v, int):
        return "i"
    if isinstance(v, float):
        return "f"
    if isinstance(v, str):
        return "s"
    if isinstance(v, (bytes, bytearray)):
        return "b"
    return "?"


@dataclass
class AddressStats:
    address: str
    count: int = 0
    types: set[str] = field(default_factory=set)
    routes: set[str] = field(default_factory=set)
    mins: list[float] = field(default_factory=list)
    maxs: list[float] = field(default_factory=list)

    @property
    def type_label(self) -> str:
        # T/F are both "bool" to a reader.
        tags = {"T" if t in "TF" else t for t in self.types}
        return ",".join(sorted("bool" if t == "T" else t for t in tags))


class Collector:
    """Thread-safe tally. Values are not kept except tracking min/max and the last VRMode."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.stats: dict[str, AddressStats] = {}
        self.vrmode: int | None = None

    def record(self, route: str, address: str, args: tuple[Any, ...]) -> None:
        with self._lock:
            st = self.stats.get(address)
            if st is None:
                st = self.stats[address] = AddressStats(address)
            st.count += 1
            st.routes.add(route)
            st.types.add("".join(type_tag(a) for a in args) or "-")
            if address.startswith(TRACKING_PREFIX):
                nums = [float(a) for a in args if isinstance(a, (int, float)) and not isinstance(a, bool)]
                if not st.mins:
                    st.mins, st.maxs = list(nums), list(nums)
                else:
                    for i, v in enumerate(nums[: len(st.mins)]):
                        st.mins[i] = min(st.mins[i], v)
                        st.maxs[i] = max(st.maxs[i], v)
            if address == VRMODE and args:
                a = args[0]
                if isinstance(a, bool):
                    self.vrmode = int(a)
                elif isinstance(a, (int, float)):
                    self.vrmode = int(a)

    def snapshot(self) -> list[AddressStats]:
        with self._lock:
            return sorted(
                (AddressStats(s.address, s.count, set(s.types), set(s.routes), list(s.mins), list(s.maxs))
                 for s in self.stats.values()),
                key=lambda s: s.address,
            )

    def total(self, route: str | None = None) -> int:
        with self._lock:
            if route is None:
                return sum(s.count for s in self.stats.values())
            # Count by route is approximate when an address arrives on both; count it for each.
            return sum(s.count for s in self.stats.values() if route in s.routes)


class _ExclusiveUDPServer(ThreadingOSCUDPServer):
    """Never share a port: on Windows, 127.0.0.1 can otherwise be bound over another app's 0.0.0.0."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            # UNVERIFIED: behaviour on real Windows with another OSC app on the port.
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # type: ignore[attr-defined]
        super().server_bind()


def _dispatcher(collector: Collector, route: str) -> Dispatcher:
    d = Dispatcher()
    d.set_default_handler(lambda address, *args: collector.record(route, address, args))
    return d


class Receiver:
    def __init__(
        self,
        collector: Collector,
        fixed_port: int | None,
        advertise: oscquery.Advertiser | None = oscquery.zeroconf_advertise,
        fixed_host: str = "0.0.0.0",
    ) -> None:
        self.collector = collector
        self.fixed_port = fixed_port
        self.fixed_host = fixed_host
        self.advertise = advertise
        self.name = f"{oscquery.OWN_PREFIX}{random.randint(1000, 9999)}"
        self.fixed_bound = False
        self.fixed_error = ""
        self.osc_port: int | None = None
        self.http_port: int | None = None
        self.advertised = False
        self.advertise_error = ""
        self._servers: list[Any] = []
        self._closers: list[Callable[[], None]] = []
        self._adv_thread: threading.Thread | None = None

    def _serve(self, server: Any) -> None:
        self._servers.append(server)
        threading.Thread(target=server.serve_forever, daemon=True).start()

    def start(self) -> "Receiver":
        if self.fixed_port:
            try:
                self._serve(_ExclusiveUDPServer((self.fixed_host, self.fixed_port),
                                                _dispatcher(self.collector, ROUTE_FIXED)))
                self.fixed_bound = True
            except OSError as e:
                self.fixed_error = str(e)
        udp = _ExclusiveUDPServer((oscquery.LOOPBACK, 0), _dispatcher(self.collector, ROUTE_OSCQUERY))
        self.osc_port = udp.server_address[1]
        self._serve(udp)
        http = oscquery.start_http(self.name, self.osc_port)
        self.http_port = http.server_address[1]
        self._serve(http)
        if self.advertise is not None:
            self._adv_thread = threading.Thread(target=self._advertise, daemon=True)
            self._adv_thread.start()
        return self

    def _advertise(self) -> None:
        assert self.advertise is not None and self.http_port and self.osc_port
        try:
            self._closers.append(self.advertise(self.name, self.http_port, self.osc_port))
            self.advertised = True
        except Exception as e:
            log.warning("mDNS advertisement failed: %s", e)
            self.advertise_error = str(e)

    def ready(self, timeout: float = 10.0) -> "Receiver":
        if self._adv_thread is not None:
            self._adv_thread.join(timeout)
        return self

    def stop(self) -> None:
        self.ready(5)
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


def wait(seconds: int, sleep: Callable[[float], None] = time.sleep,
         tick: Callable[[int], None] | None = None) -> tuple[bool, int]:
    """Count down one second at a time. Returns (completed, seconds waited); Ctrl+C stops early."""
    done = 0
    try:
        for left in range(seconds, 0, -1):
            if tick:
                tick(left)
            sleep(1)
            done += 1
    except KeyboardInterrupt:
        return False, done
    return True, done
