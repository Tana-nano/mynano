"""Fakes shared by osc-doctor tests (module name kept unique across products)."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from osc_doctor import cli, oscquery
from osc_doctor.sysinfo import PortState, ProcInfo

NOW = datetime(2026, 9, 30, 22, 15, 30)


@dataclass
class FakeSys:
    procs: list[ProcInfo] = field(default_factory=list)
    ports: dict[int, PortState] = field(default_factory=dict)

    def processes(self) -> list[ProcInfo]:
        return list(self.procs)

    def udp_port(self, port: int) -> PortState:
        return self.ports.get(port, PortState(False))


def vrchat(*cmdline: str) -> ProcInfo:
    return ProcInfo(100, "VRChat.exe", ("VRChat.exe", *cmdline))


@dataclass
class FakeBrowser:
    endpoints: list[oscquery.Endpoint] = field(default_factory=list)
    error: Exception | None = None

    def browse(self, seconds: float) -> list[oscquery.Endpoint]:
        if self.error:
            raise self.error
        return list(self.endpoints)


def short_sleep(_s: float) -> None:
    time.sleep(0.05)


def make_env(tmp_path: Path, **kw) -> cli.Env:
    base = dict(
        sysinfo=FakeSys(),
        browser=FakeBrowser(),
        advertise=None,
        sleep=short_sleep,
        now=lambda: NOW,
        input=lambda _p: "n",
        vrc_dir=tmp_path / "vrchat",
        output_dir=tmp_path / "out",
        fixed_host="127.0.0.1",
    )
    base.update(kw)
    return cli.Env(**base)


def run_cli(argv: list[str], env: cli.Env) -> tuple[int, str]:
    buf = io.StringIO()
    code = cli.main(argv, env=env, out=buf)
    return code, buf.getvalue()


def make_cache(vrc_dir: Path, users: int = 1, files: int = 2) -> None:
    for u in range(users):
        d = vrc_dir / "OSC" / f"usr_0000000{u}-aaaa-bbbb-cccc-dddddddddddd" / "Avatars"
        d.mkdir(parents=True, exist_ok=True)
        for i in range(files):
            (d / f"avtr_{i:08d}-1111-2222-3333-444444444444.json").write_text("{}", encoding="utf-8")
