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
