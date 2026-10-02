"""One check from files to saved results, shared by the command line and the local app."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from .archive import InputRecord, Limits, make_names_unique, read_input
from .checks import Analysis, Options, analyze, exit_code, summary, zip_counts
from .draft import render_draft
from .html_report import AppChrome, render_html
from .known import KnownAssets
from .report import render_report, save, screen_lines, verdict_line


@dataclass
class Settings:
    limits: Limits
    opts: Options
    max_referrers: int = 5
    verbose: bool = False
    report: bool = True
    draft: bool = True


@dataclass
class Outcome:
    code: int
    inputs: list[InputRecord]
    analysis: Analysis
    folder: Path | None = None
    saved: tuple[Path | None, Path | None, Path | None] = (None, None, None)  # report.txt, draft, report.html


def inspect(files: list[tuple[Path, str]], s: Settings, known: KnownAssets, say: Callable[[str], None],
            color: bool = False) -> Outcome | None:
    """Read and judge (path, display name) pairs and print the screen; None when nothing was readable."""
    inputs: list[InputRecord] = []
    for f, name in files:
        say(f"調べています: {name}")
        try:
            inputs.append(read_input(f, s.limits, name))
        except OSError as e:
            say(f"{name}: 読めませんでした（{e.strerror or e}）")
    if not inputs:
        say("調べられるファイルがありませんでした。")
        return None
    make_names_unique(inputs)
    analysis = analyze(inputs, known, s.opts)
    for r in inputs:
        if r.zip is not None:
            say("")
            say(r.name)
            say("  " + zip_counts(r.zip))
    say("")
    for line in screen_lines(analysis.findings, s.verbose, color):
        say(line)
    say("")
    say(f"結果: {summary(analysis.findings)}")
    say(verdict_line(analysis.findings, color))
    return Outcome(exit_code(analysis.findings), inputs, analysis)


def save_outcome(o: Outcome, s: Settings, known: KnownAssets, now: datetime, folder: Path) -> None:
    """Write report.txt / report.html / readme-draft.md as the settings ask. Raises OSError."""
    report_text = render_report(o.inputs, o.analysis, known, now, s.max_referrers) if s.report else None
    html_text = render_html(o.inputs, o.analysis, known, now, s.max_referrers) if s.report else None
    draft_text = render_draft(o.inputs, o.analysis, known) if s.draft else None
    o.folder = folder
    o.saved = save(folder, report_text, draft_text, html_text)


def app_page(o: Outcome, s: Settings, known: KnownAssets, now: datetime, app: AppChrome) -> str:
    return render_html(o.inputs, o.analysis, known, now, s.max_referrers, app)
