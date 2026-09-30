"""OSCQuery: advertise ourselves so VRChat sends to us, and find VRChat's own service.

- VRChat discovers apps via mDNS ``_oscjson._tcp``, reads ``/?HOST_INFO`` for the
  UDP port and ``/`` for the address space, and sends ``/avatar/*`` and
  ``/tracking/vrsystem/*`` to apps exposing those paths
  (github.com/vrchat-community/osc/wiki/OSCQuery).
- VRChat advertises itself as ``VRChat-Client-XXXXXX`` (vrc-oscquery-lib issue #28).
  HOST_INFO keys: NAME, OSC_IP, OSC_PORT, OSC_TRANSPORT (vrc-oscquery-lib HostInfo.cs).
"""

from __future__ import annotations

import json
import logging
import socket
import time
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable, Protocol

log = logging.getLogger(__name__)

LOOPBACK = "127.0.0.1"
VRCHAT_PREFIX = "VRChat-Client-"
OWN_PREFIX = "OscDoctor-"


def address_space() -> dict[str, Any]:
    """Expose /avatar and /tracking/vrsystem so VRChat sends both to us."""
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


def start_http(name: str, osc_port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((LOOPBACK, 0), make_http_handler(name, osc_port))


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


# --- finding VRChat -------------------------------------------------------


@dataclass(frozen=True)
class VrcQuery:
    name: str
    osc_ip: str
    osc_port: int
    has_avatar: bool
    via: str  # "mdns" | "direct"


@dataclass(frozen=True)
class Endpoint:
    name: str
    host: str
    port: int


class Browser(Protocol):
    def browse(self, seconds: float) -> list[Endpoint]: ...


class ZeroconfBrowser:
    """Lists ``_oscjson._tcp`` services whose instance name starts with ``VRChat-Client-``."""

    def __init__(self, interfaces: Any = None) -> None:
        self.interfaces = interfaces

    def browse(self, seconds: float) -> list[Endpoint]:
        from zeroconf import ServiceBrowser, Zeroconf

        kwargs = {"interfaces": self.interfaces} if self.interfaces is not None else {}
        zc = Zeroconf(**kwargs)
        names: list[str] = []

        class Listener:
            def add_service(self, _zc: Any, _type: str, name: str) -> None:
                names.append(name)

            def update_service(self, *_: Any) -> None:
                pass

            def remove_service(self, *_: Any) -> None:
                pass

        try:
            ServiceBrowser(zc, "_oscjson._tcp.local.", Listener())
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline and not any(n.startswith(VRCHAT_PREFIX) for n in names):
                time.sleep(0.1)
            out: list[Endpoint] = []
            for n in dict.fromkeys(names):
                if not n.startswith(VRCHAT_PREFIX):
                    continue
                info = zc.get_service_info("_oscjson._tcp.local.", n, timeout=1500)
                if info is None or not info.port:
                    continue
                addrs = info.parsed_addresses() or [LOOPBACK]
                out.append(Endpoint(n.split("._oscjson")[0], addrs[0], int(info.port)))
            return out
        finally:
            zc.close()


def fetch_json(host: str, port: int, suffix: str, timeout: float = 1.5) -> dict[str, Any]:
    with urllib.request.urlopen(f"http://{host}:{port}{suffix}", timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError("not a JSON object")
    return data


def read_vrchat(host: str, port: int, via: str) -> VrcQuery | None:
    """Read HOST_INFO and root. None if it doesn't answer like an OSCQuery server."""
    try:
        info = fetch_json(host, port, "/?HOST_INFO")
        osc_port = int(info["OSC_PORT"])
    except Exception as e:
        log.info("no OSCQuery at %s:%s (%s)", host, port, e)
        return None
    name = str(info.get("NAME") or "")
    if name.startswith(OWN_PREFIX):
        return None
    try:
        root = fetch_json(host, port, "/")
        has_avatar = "avatar" in (root.get("CONTENTS") or {})
    except Exception:
        has_avatar = False
    return VrcQuery(name, str(info.get("OSC_IP") or LOOPBACK), osc_port, has_avatar, via)


@dataclass
class DiscoveryResult:
    vrc: VrcQuery | None = None
    mdns_ok: bool = True
    mdns_error: str = ""


def discover(browser: Browser | None, seconds: float, direct_port: int) -> DiscoveryResult:
    res = DiscoveryResult()
    if browser is None:
        res.mdns_ok = False
        res.mdns_error = "disabled"
    else:
        try:
            for ep in browser.browse(seconds):
                vrc = read_vrchat(ep.host, ep.port, "mdns")
                if vrc is not None:
                    res.vrc = vrc
                    return res
        except Exception as e:
            log.warning("mDNS browse failed: %s", e)
            res.mdns_ok = False
            res.mdns_error = str(e)
    # UNVERIFIED: VRChat's OSCQuery HTTP defaults to TCP 9001 (vrc-oscquery-lib Readme).
    res.vrc = read_vrchat(LOOPBACK, direct_port, "direct")
    return res
