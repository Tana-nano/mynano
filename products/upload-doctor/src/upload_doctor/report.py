"""Screen lines and the shareable report. Every line goes through the Masker."""

from __future__ import annotations

import platform
import unicodedata
from datetime import datetime

from . import DISPLAY_NAME, VERSION
from .checks import CONF_LABEL, Finding, candidates, summary
from .editorlog import LogFacts
from .mask import Masker
from .project import ProjectFacts
from .rules import Rules

SCREEN_EVIDENCE = 3
VERBOSE_EVIDENCE = 20
REPORT_LINE_CHARS = 200
REPORT_EVIDENCE_LINES = 60
PROMO = "作者の他のツール: VRChat の OSC が動かないときの「OSCドクター」もあります（Booth）"
INDENT = " " * 13
_MATCH_LABEL = {"match": "一致", "mismatch": "不一致", "unknown": "不明"}


def width(s: str) -> int:
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, cols: int) -> str:
    return s + " " * max(1, cols - width(s))


def clip(s: str, n: int = REPORT_LINE_CHARS) -> str:
    return s if len(s) <= n else s[: n - 1] + "…"


def log_status(lf: LogFacts | None) -> str:
    if lf is None or not lf.found:
        return "なし"
    if lf.unreadable:
        return "開けません"
    when = f"{lf.mtime:%Y-%m-%d %H:%M}" if lf.mtime else "?"
    tail = "、末尾のみ" if lf.truncated else ""
    return f"あり（{when}、{lf.lines:,} 行、対象プロジェクト: {_MATCH_LABEL[lf.project_match]}{tail}）"


class _Budget:
    def __init__(self, n: int | None):
        self.left = n

    def take(self, want: int) -> int:
        if self.left is None:
            return want
        got = min(want, self.left)
        self.left -= got
        return got


def finding_block(n: int, f: Finding, per_finding: int, budget: _Budget | None = None, clip_lines: bool = False) -> list[str]:
    conf = pad(f"確からしさ:{CONF_LABEL[f.confidence]}", 15) if f.confidence else ""
    lines = [f"{n:>2}. " + pad(f"[{f.status}]", 7) + conf + f.title]
    shown = f.evidence[:per_finding]
    if budget is not None:
        shown = shown[: budget.take(len(shown))]
    for i, e in enumerate(shown):
        e = clip(e) if clip_lines else e
        lines.append(INDENT + ("根拠: " if i == 0 else "      ") + e)
    rest = f.total - len(shown)
    if rest > 0:
        lines.append(INDENT + ("根拠: " if not shown else "      ") + f"ほか {rest} 件")
    lines += [INDENT + "→ " + a for a in f.advice]
    lines += [INDENT + "※ " + x for x in f.notes]
    return lines


def ok_line(findings: list[Finding]) -> str | None:
    oks = [f.title for f in findings if f.level == "ok"]
    return "問題なしの項目: " + " / ".join(oks) if oks else None


def candidate_lines(
    findings: list[Finding], per_finding: int, budget: _Budget | None = None, clip_lines: bool = False,
    heading: str = "原因の候補（上ほど可能性が高い順）",
) -> list[str]:
    cands = candidates(findings)
    if not cands:
        return ["原因の候補は見つかりませんでした"]
    lines = [heading]
    for i, f in enumerate(cands, 1):
        lines += finding_block(i, f, per_finding, budget, clip_lines)
    return lines


def log_detail_lines(lf: LogFacts | None, rules: Rules) -> list[str]:
    if lf is None or not lf.found or lf.unreadable:
        return ["（Editor.log なし）"]
    c = lf.compile
    lines = [
        "コンパイルエラー: "
        + " / ".join(f"{label} {c[k].unique} 件（延べ {c[k].total} 回）" for k, label in (("assets", "Assets"), ("sdk", "SDK"), ("other", "その他")))
    ]
    for r in rules.log_rules:
        h = lf.rule_hits.get(r.id)
        lines.append(f"{r.id}: {h.count if h else 0} 回")
    for kind, (cnt, _) in sorted(lf.unclassified.items()):
        lines.append(f"未分類 {kind}: {cnt} 回")
    return lines


def header_lines(pf: ProjectFacts | None, lf: LogFacts | None, rules: Rules) -> list[str]:
    return [
        f"{DISPLAY_NAME} {VERSION}",
        f"プロジェクト: {pf.root if pf else '?'}",
        f"Editor.log: {log_status(lf)}",
        f"規則表: {rules.checked_on.isoformat()} 時点（{rules.origin}）",
    ]


def screen(findings: list[Finding], pf: ProjectFacts, lf: LogFacts | None, rules: Rules, mask: Masker, verbose: bool) -> str:
    lines = header_lines(pf, lf, rules) + [""]
    lines += candidate_lines(findings, VERBOSE_EVIDENCE if verbose else SCREEN_EVIDENCE)
    if ok := ok_line(findings):
        lines.append(ok)
    if verbose:
        lines += ["", "読んだファイル:"] + ["  " + x for x in pf.read_files]
        lines += ["", "Editor.log の内訳:"] + ["  " + x for x in log_detail_lines(lf, rules)]
    lines += ["", summary(findings)]
    return "\n".join(mask(x) for x in lines)


def render_report(findings: list[Finding], pf: ProjectFacts, lf: LogFacts | None, rules: Rules, mask: Masker, now: datetime) -> str:
    lines = [
        f"{DISPLAY_NAME} {VERSION} 診断レポート",
        f"実行日時: {now:%Y-%m-%d %H:%M:%S}",
        f"Windows: {platform.platform()}",
        f"規則表: {rules.checked_on.isoformat()} 時点（{rules.origin}）",
        f"プロジェクト: {pf.root}",
        f"Unity: {pf.unity_version or '不明'}（推奨 {rules.recommended_unity}）",
        f"Editor.log: {log_status(lf)}",
        "",
        summary(findings),
        "",
    ]
    lines += candidate_lines(
        findings, VERBOSE_EVIDENCE, _Budget(REPORT_EVIDENCE_LINES), clip_lines=True,
        heading="== 原因の候補（上ほど可能性が高い順） ==",
    )
    lines += ["", "== 問題なしの項目 =="]
    lines += [f"- {f.title}" for f in findings if f.level == "ok"] or ["（なし）"]
    lines += ["", "== パッケージ（Packages/） =="]
    lines += [f"{p.id} {p.version or '?'}" for p in sorted(pf.packages.values(), key=lambda p: p.id)] or ["（なし）"]
    lines += ["", "== Editor.log の内訳 =="] + log_detail_lines(lf, rules)
    lines += ["", "== 読んだファイル =="] + pf.read_files
    lines += ["", PROMO]
    return "\n".join(mask(x) for x in lines) + "\n"
