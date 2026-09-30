"""Screen lines, report.txt and saving (file names only, never full input paths)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from . import DISPLAY_NAME, VERSION
from . import classify as cl
from .archive import InputRecord
from .checks import Analysis, Finding, human_size, kinds_text, summary
from .known import ORDER, KnownAssets

SCREEN_EXAMPLES = 3
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def header(known: KnownAssets) -> str:
    return f"{DISPLAY_NAME} {VERSION}（辞書 {known.built}）"


def finding_lines(f: Finding, limit: int | None) -> list[str]:
    lines = [f"[{f.severity}] {f.code} {f.title}"]
    for i, a in enumerate(f.advice):
        lines.append(("       → " if i == 0 else "         ") + a)
    shown = f.examples if limit is None else f.examples[:limit]
    for e in shown:
        lines.append("         - " + e)
    rest = len(f.examples) - len(shown)
    if rest > 0:
        lines.append(f"         （ほか {rest} 件。すべてはレポートにあります）")
    return lines


def screen_lines(findings: list[Finding], verbose: bool) -> list[str]:
    out: list[str] = []
    for f in findings:
        out += finding_lines(f, None if verbose else SCREEN_EXAMPLES)
    return out


def render_report(inputs: list[InputRecord], analysis: Analysis, known: KnownAssets, now: datetime,
                  max_referrers: int) -> str:
    L: list[str] = [f"{header(known)} レポート", f"実行日時: {now:%Y-%m-%d %H:%M:%S}", ""]
    L.append("■ 入力")
    for r in inputs:
        L.append(f"- {r.name}（{human_size(r.size)}、SHA-256 {r.sha256}）")
        for p in r.packages:
            if r.kind == "zip":
                L.append(f"    - {p.name}（{human_size(p.size)}、SHA-256 {p.sha256}）")
    L += ["", f"■ 結果: {summary(analysis.findings)}", ""]
    for f in analysis.findings:
        L += finding_lines(f, None)
        L.append("")
    L.append("■ パッケージごとの同梱物")
    for s in analysis.summaries.values():
        L.append(f"- {s.name}: {kinds_text(s)}（ファイル {s.files}、フォルダ {s.folders}、合計 {human_size(s.total_size)}）")
        if s.top_folders:
            L.append("    Assets/ 直下: " + ", ".join(s.top_folders))
    L += ["", "■ 外部参照の一覧（内部と Unity 組み込みを除く）"]
    for pr in analysis.refs:
        L.append(f"- {pr.package}（内部 {pr.internal} か所、Unity 組み込み {pr.builtin} か所）")
        for x in sorted(pr.external.values(), key=lambda x: (cl.CATEGORY_LABELS[x.category], x.guid)):
            label = cl.CATEGORY_LABELS[x.category]
            if x.known_id:
                label += f"（{known.name(x.known_id)}）"
            elif x.kind:
                label += f"（{x.kind}）"
            refs = ", ".join(x.referrers[:max_referrers])
            more = len(x.referrers) - max_referrers
            L.append(f"    {x.guid}  {label}  {x.count} か所  参照元: {refs}" + (f" ほか {more} 件" if more > 0 else ""))
    L += ["", "■ 既知アセットの検出一覧"]
    for pname, pm in analysis.matches.items():
        exact: dict[str, int] = {}
        prefix: dict[str, int] = {}
        for m in pm.values():
            if m is not None:
                d = exact if m.exact else prefix
                d[m.id] = d.get(m.id, 0) + 1
        if not exact and not prefix:
            L.append(f"- {pname}: なし")
            continue
        L.append(f"- {pname}")
        for kid in ORDER:
            if kid in exact or kid in prefix:
                L.append(f"    {known.name(kid)}: ID 一致 {exact.get(kid, 0)} 個 / フォルダ名だけの一致 {prefix.get(kid, 0)} 個")
    return "\n".join(L) + "\n"


def run_dir_name(first_input: Path, now: datetime) -> str:
    stem = first_input.name if first_input.is_dir() else first_input.stem
    stem = _UNSAFE.sub("_", stem).strip(" .") or "input"
    return f"{stem}-{now:%Y%m%d-%H%M%S}"


def save(folder: Path, report_text: str | None, draft_text: str | None) -> tuple[Path | None, Path | None]:
    """Write report.txt (UTF-8 with BOM, for Notepad) and readme-draft.md (UTF-8)."""
    folder.mkdir(parents=True, exist_ok=True)
    rp = dp = None
    if report_text is not None:
        rp = folder / "report.txt"
        rp.write_text(report_text, encoding="utf-8-sig", newline="\r\n")
    if draft_text is not None:
        dp = folder / "readme-draft.md"
        dp.write_text(draft_text, encoding="utf-8", newline="\r\n")
    return rp, dp
