"""Screen lines and the shareable report (IDs and the Windows user name masked)."""

from __future__ import annotations

import platform
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from . import DISPLAY_NAME, VERSION
from .checks import Facts, Finding, summary
from .receiver import AddressStats

_USR = re.compile(r"usr_[0-9A-Za-z-]+")
_AVTR = re.compile(r"avtr_[0-9A-Za-z-]+")
_WRLD = re.compile(r"wrld_[0-9A-Za-z-]+")
_USERS = re.compile(r"([A-Za-z]:[\\/]+Users[\\/]+)[^\\/\r\n]+", re.IGNORECASE)
_HOME_POSIX = re.compile(r"/(home|Users)/[^/\s]+")

PROMO = "作者の他のツール: VR 睡眠を記録するツール「V睡ログ」もあります（Booth）"


def mask(text: str) -> str:
    text = _USR.sub("usr_xxxx", text)
    text = _AVTR.sub("avtr_xxxx", text)
    text = _WRLD.sub("wrld_xxxx", text)
    text = _USERS.sub("%USERPROFILE%", text)
    return _HOME_POSIX.sub("~", text)


def width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, cols: int) -> str:
    return s + " " * max(1, cols - width(s))


def finding_lines(findings: list[Finding]) -> list[str]:
    lines: list[str] = []
    for x in findings:
        lines.append(pad(f"[{x.status}]", 7) + pad(x.label, 15) + x.message)
        for a in x.actions:
            lines.append(" " * 9 + "→ " + a)
    return lines


def address_lines(stats: list[AddressStats]) -> list[str]:
    if not stats:
        return ["（なし）"]
    lines = []
    for s in stats:
        routes = "+".join(sorted("OSCQuery" if r == "oscquery" else "固定" for r in s.routes))
        lines.append(f"{s.address}  型={s.type_label}  {s.count} 件  経路={routes}")
    return lines


def tracking_lines(stats: list[AddressStats], seconds: float) -> list[str]:
    lines = []
    for s in stats:
        if not s.address.startswith("/tracking/"):
            continue
        rate = s.count / seconds if seconds > 0 else 0.0
        rng = ", ".join(f"[{a:.3f}, {b:.3f}]" for a, b in zip(s.mins, s.maxs))
        lines.append(f"{s.address}  {s.count} 件  約 {rate:.1f} 件/秒  範囲 {rng}")
    return lines or ["（なし）"]


def render_report(
    findings: list[Finding],
    facts: Facts,
    stats: list[AddressStats],
    measured_seconds: float,
    now: datetime,
) -> str:
    lines = [
        f"{DISPLAY_NAME} {VERSION} 診断レポート",
        f"実行日時: {now:%Y-%m-%d %H:%M:%S}",
        f"Windows: {platform.platform()}",
        f"計測時間: {measured_seconds:.0f} 秒{'（0 件のため 1 回延長）' if facts.extended else ''}",
        "",
        f"■ 結果: {summary(findings)}",
        *finding_lines(findings),
        "",
        "■ 受信したアドレス",
        *address_lines(stats),
        "",
        "■ トラッキング（頭・手首）",
        *tracking_lines(stats, measured_seconds),
        "",
        "■ ポート",
    ]
    for p, st in sorted(facts.ports.items()):
        owner = st.owner or ("使用中（アプリ名不明）" if st.in_use else "空き")
        lines.append(f"{p}: {owner}")
    lines += [
        f"VRChat の受信ポート: {facts.vrc_in}（既定・起動引数では {facts.nominal_in}）",
        f"固定ポート {facts.out_port} での受信: {'した' if facts.fixed_bound else 'していない（使用中）'}",
    ]
    oq = facts.discovery_vrc
    lines += [
        "",
        "■ VRChat の OSCQuery",
        f"{oq.name}（{oq.via}、受信ポート {oq.osc_port}、アバター {'あり' if oq.has_avatar else 'なし'}）" if oq else "見つかりませんでした",
        f"mDNS: {'使用可' if facts.mdns_ok else '使用不可'}",
        "",
        "■ キャッシュ",
        (f"{facts.cache.path}  ユーザー {facts.cache.users}・ファイル {facts.cache.files} 件"
         if facts.cache else "なし"),
    ]
    lines += ["", PROMO, ""]
    return mask("\n".join(lines))


def write_report(text: str, out_dir: Path, now: datetime) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"report-{now:%Y%m%d-%H%M%S}.txt"
    # BOM so Notepad on older Windows opens it as UTF-8.
    path.write_text(text, encoding="utf-8-sig", newline="\r\n")
    return path
