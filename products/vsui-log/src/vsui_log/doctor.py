"""Diagnostics and anonymized samples the owner can send us to tune defaults."""

from __future__ import annotations

import csv
import re
import socket
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .card import find_font
from .logparse import LogParser
from .logtail import LOG_GLOB
from .paths import AppPaths

_USR = re.compile(r"usr_[0-9a-fA-F-]+")
_WRLD = re.compile(r"wrld_[0-9a-fA-F-]+")
_GRP = re.compile(r"grp_[0-9a-fA-F-]+")


def newest_log(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None
    files = sorted(directory.glob(LOG_GLOB), key=lambda p: p.stat().st_mtime)
    return files[-1] if files else None


def mask_log_lines(lines: list[str], parser: LogParser, limit: int = 20) -> list[str]:
    """Return up to ``limit`` matching lines with names, user/world/group ids and world names masked."""
    names: dict[str, str] = {}
    worlds: dict[str, str] = {}
    out: list[str] = []
    for raw in lines:
        line = raw.lstrip("﻿").rstrip("\r\n")
        ev = parser.parse(line)
        if ev is None:
            continue
        masked = line
        if ev.name:
            alias = names.setdefault(ev.name, f"Player{len(names) + 1}")
            masked = masked.replace(ev.name, alias)
        if ev.world_name:
            alias = worlds.setdefault(ev.world_name, f"World{len(worlds) + 1}")
            masked = masked.replace(ev.world_name, alias)
        masked = _USR.sub("usr_xxxx", masked)
        masked = _WRLD.sub("wrld_xxxx", masked)
        masked = _GRP.sub("grp_xxxx", masked)
        out.append(masked)
    return out[-limit:]


def log_sample(log_dir: Path, parser: LogParser, limit: int = 20) -> list[str]:
    path = newest_log(log_dir)
    if path is None:
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    return mask_log_lines(text.splitlines(), parser, limit)


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def diagnose(cfg: dict[str, Any], paths: AppPaths) -> list[str]:
    log_path = newest_log(paths.log_dir)
    font = find_font()
    lines = [
        f"設定ファイル : {paths.config_path}{'' if paths.config_path.exists() else '（未作成）'}",
        f"データベース : {paths.db_path}",
        f"出力先       : {paths.output_dir}",
        f"VRChat ログ  : {paths.log_dir}{'' if paths.log_dir.is_dir() else '（見つかりません）'}",
        f"最新のログ   : {log_path.name if log_path else 'なし'}",
        f"OSC モード   : {cfg['osc']['mode']}",
        f"ポート {cfg['osc']['listen_port']} : {'空き' if port_free(cfg['osc']['listen_port']) else '使用中（他の OSC アプリ）'}",
    ]
    if cfg["osc"]["direct_port"]:
        p = cfg["osc"]["direct_port"]
        lines.append(f"ポート {p} : {'空き' if port_free(p) else '使用中'}")
    lines.append(f"フォント     : {font or '見つかりません（共有カードが作れません）'}")
    return lines


class PoseRecorder:
    """Collects head poses for ``doctor --pose-sample``. Numbers only, no personal data."""

    def __init__(self) -> None:
        self.t0: float | None = None
        self.rows: list[list[float]] = []

    def __call__(self, _ts: datetime, args: tuple) -> None:
        if len(args) < 6:
            return
        now = _time.monotonic()
        if self.t0 is None:
            self.t0 = now
        self.rows.append([round(now - self.t0, 3), *[float(a) for a in args[:6]]])

    def write_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t", "x", "y", "z", "rx", "ry", "rz"])
            w.writerows(self.rows)


def record_pose(start_receiver: Callable[[PoseRecorder], Callable[[], None]], seconds: float) -> PoseRecorder:
    rec = PoseRecorder()
    stop = start_receiver(rec)
    try:
        _time.sleep(seconds)
    finally:
        stop()
    return rec
