"""Processes and UDP port owners. Real implementation uses psutil; tests inject fakes."""

from __future__ import annotations

import os
import re
import socket
from dataclasses import dataclass
from typing import Protocol

VRCHAT_EXE = "vrchat.exe"
INSTALLER_EXE = "install.exe"
# UNVERIFIED: only SteamVR's server is used as a VR-runtime hint; Oculus/Virtual Desktop names unconfirmed.
VR_RUNTIME_EXES = ("vrserver.exe",)

_OSC_ARG = re.compile(r"^--osc=(\d{1,5}):([^:]+):(\d{1,5})$")


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    name: str
    cmdline: tuple[str, ...] = ()


@dataclass(frozen=True)
class PortState:
    in_use: bool
    owner: str | None = None  # process name, None if unknown or free
    owner_pid: int | None = None

    def owned_by(self, exe: str) -> bool:
        return self.owner is not None and self.owner.lower() == exe.lower()


@dataclass(frozen=True)
class LaunchOsc:
    in_port: int
    sender_ip: str
    out_port: int


def parse_osc_arg(cmdline: tuple[str, ...] | list[str]) -> LaunchOsc | None:
    """Find ``--osc=inPort:senderIP:outPort`` (docs.vrchat.com/docs/osc-overview)."""
    for arg in cmdline:
        m = _OSC_ARG.match(arg.strip())
        if m:
            i, o = int(m.group(1)), int(m.group(3))
            if 0 < i < 65536 and 0 < o < 65536:
                return LaunchOsc(i, m.group(2), o)
    return None


class SystemInfo(Protocol):
    def processes(self) -> list[ProcInfo]: ...

    def udp_port(self, port: int) -> PortState: ...


def exclusive_bind_free(port: int) -> bool:
    """True if nothing is bound to ``port`` (tested without stealing it)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)  # type: ignore[attr-defined]
        try:
            s.bind(("0.0.0.0", port))
            return True
        except OSError:
            return False


class PsutilSystemInfo:
    def processes(self) -> list[ProcInfo]:
        import psutil

        out: list[ProcInfo] = []
        for p in psutil.process_iter(["pid", "name"]):
            name = p.info.get("name") or ""
            cmd: tuple[str, ...] = ()
            if name.lower() == VRCHAT_EXE:
                try:
                    cmd = tuple(p.cmdline())
                except Exception:  # AccessDenied etc.
                    cmd = ()
            out.append(ProcInfo(p.info["pid"], name, cmd))
        return out

    def udp_port(self, port: int) -> PortState:
        import psutil

        try:
            conns = psutil.net_connections(kind="udp")
        except Exception:
            # UNVERIFIED: whether non-admin Windows users can list UDP owners.
            return PortState(in_use=not exclusive_bind_free(port))
        for c in conns:
            if c.laddr and c.laddr.port == port:
                name = None
                if c.pid:
                    try:
                        name = psutil.Process(c.pid).name()
                    except Exception:
                        name = None
                return PortState(True, name, c.pid)
        return PortState(in_use=not exclusive_bind_free(port))


def own_pid() -> int:
    return os.getpid()
