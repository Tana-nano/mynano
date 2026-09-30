"""Probe an app's OSCQuery HTTP endpoint the way VRChat would.

VRChat discovers apps via mDNS (``_oscjson._tcp``), then fetches ``/?HOST_INFO``
for the OSC port and ``/`` for the address space. It sends ``/avatar/*`` to apps
that expose ``/avatar`` and ``/tracking/vrsystem/*`` to apps that expose
``/tracking/vrsystem``. (github.com/vrchat-community/osc/wiki/OSCQuery)
"""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class ProbeResult:
    host_info: dict[str, Any]
    root: dict[str, Any]

    def has_path(self, path: str) -> bool:
        node = self.root
        for part in [p for p in path.split("/") if p]:
            node = (node.get("CONTENTS") or {}).get(part)
            if node is None:
                return False
        return True

    @property
    def osc_port(self) -> int:
        return int(self.host_info["OSC_PORT"])

    @property
    def wants_avatar(self) -> bool:
        return self.has_path("/avatar")

    @property
    def wants_tracking(self) -> bool:
        return self.has_path("/tracking/vrsystem")


class OscQueryProbe:
    def __init__(self, http_port: int, host: str = "127.0.0.1", timeout: float = 2.0) -> None:
        self.base = f"http://{host}:{http_port}"
        self.timeout = timeout

    def _get(self, suffix: str) -> dict[str, Any]:
        with urllib.request.urlopen(self.base + suffix, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def probe(self) -> ProbeResult:
        return ProbeResult(host_info=self._get("/?HOST_INFO"), root=self._get("/"))


class FakeVRChatQuery:
    """VRChat's own OSCQuery service: HTTP ``/?HOST_INFO`` and ``/``, optionally on mDNS.

    Real VRChat advertises ``_oscjson._tcp`` as ``VRChat-Client-XXXXXX``
    (vrc-oscquery-lib issue #28). HOST_INFO keys follow vrc-oscquery-lib
    ``HostInfo.cs``: NAME, OSC_IP, OSC_PORT, OSC_TRANSPORT. ``OSC_PORT`` is the
    UDP port VRChat receives on.
    """

    def __init__(self, osc_port: int, name: str = "VRChat-Client-07091F", has_avatar: bool = True) -> None:
        self.name = name
        self.osc_port = osc_port
        self.has_avatar = has_avatar
        self._server: Any = None
        self._zc: Any = None
        self._infos: list[Any] = []

    def host_info(self) -> dict[str, Any]:
        return {"NAME": self.name, "OSC_IP": "127.0.0.1", "OSC_PORT": self.osc_port, "OSC_TRANSPORT": "UDP"}

    def root(self) -> dict[str, Any]:
        contents: dict[str, Any] = {}
        if self.has_avatar:
            contents["avatar"] = {"FULL_PATH": "/avatar", "ACCESS": 0, "CONTENTS": {}}
        return {"FULL_PATH": "/", "ACCESS": 0, "CONTENTS": contents}

    @property
    def http_port(self) -> int:
        return self._server.server_address[1]

    def start(self) -> "FakeVRChatQuery":
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                body = owner.host_info() if "HOST_INFO" in self.path else owner.root()
                data = json.dumps(body).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return self

    def advertise(self) -> None:
        """Announce on mDNS like VRChat. Raises if multicast is unavailable."""
        import socket

        from zeroconf import ServiceInfo, Zeroconf

        self._zc = Zeroconf(interfaces=["127.0.0.1"])
        info = ServiceInfo(
            "_oscjson._tcp.local.", f"{self.name}._oscjson._tcp.local.",
            addresses=[socket.inet_aton("127.0.0.1")], port=self.http_port,
            properties={"txtvers": "1"}, server=f"{self.name}.local.",
        )
        self._zc.register_service(info)
        self._infos.append(info)

    def stop(self) -> None:
        if self._zc is not None:
            for info in self._infos:
                try:
                    self._zc.unregister_service(info)
                except Exception:
                    pass
            self._zc.close()
            self._zc = None
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> "FakeVRChatQuery":
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()
