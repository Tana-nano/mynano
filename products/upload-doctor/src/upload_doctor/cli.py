"""upload-doctor command line: read the project and Editor.log, judge, print, save the report."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Sequence, TextIO

from . import DISPLAY_NAME, VERSION, checks, editorlog, paths, project, report, selfcheck
from .console import setup_console
from .mask import Masker
from .rules import RulesError, load

PROMPT = "Unity プロジェクトのフォルダをここにドラッグして Enter: "


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="upload-doctor", description=f"{DISPLAY_NAME}: アバターのアップロード失敗の原因候補を調べます")
    p.add_argument("project", nargs="?", metavar="PROJECT", help="Unity プロジェクトのフォルダ")
    p.add_argument("--editor-log", help="Editor.log の場所（既定 %%LOCALAPPDATA%%\\Unity\\Editor\\Editor.log）")
    p.add_argument("--rules", help="規則表 JSON を差し替える")
    p.add_argument("--verbose", action="store_true", help="根拠の全件・読んだファイル・内訳も表示する")
    p.add_argument("--out", help="レポートの保存先フォルダ")
    p.add_argument("--no-report", action="store_true", help="レポートを保存しない")
    p.add_argument("--no-pause", action="store_true", help="終了時に Enter を待たない")
    p.add_argument("--self-check", action="store_true", help=argparse.SUPPRESS)
    p.add_argument("--version", action="version", version=f"{DISPLAY_NAME} {VERSION}")
    return p


def should_pause(argv: Sequence[str]) -> bool:
    """Wait for Enter only for double-click / drag-and-drop starts (no '--' options at all)."""
    return not any(a.startswith("--") for a in argv)


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    input_fn: Callable[[str], str] = input,
    now: datetime | None = None,
    env: Mapping[str, str] | None = None,
) -> int:
    out = stdout or sys.stdout
    if stdout is None:
        setup_console()
    env = os.environ if env is None else env
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = build_parser().parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    try:
        return _run(args, out, input_fn, now, env)
    except KeyboardInterrupt:
        print("\n中断しました。", file=out)
        return 2


def _run(args: argparse.Namespace, out: TextIO, input_fn: Callable[[str], str], now: datetime | None, env: Mapping[str, str]) -> int:
    if args.self_check:
        return selfcheck.run(out)

    try:
        rules = load(args.rules)
    except RulesError as e:
        print(f"規則表が不正です: {e}", file=out)
        return 2

    raw = args.project
    if raw is None:
        try:
            raw = input_fn(PROMPT)
        except EOFError:
            raw = ""
    raw = project.clean_path_arg(raw)
    if not raw:
        print("プロジェクトのフォルダが指定されていません。", file=out)
        return 2
    root = Path(raw)
    mask = Masker([raw, os.path.abspath(raw)])
    if not root.is_dir():
        print(f"フォルダが見つかりません: {raw}", file=out)
        return 2
    if not project.is_unity_project(root):
        print(f"Unity プロジェクトのフォルダではありません（Assets と ProjectSettings がありません）: {raw}", file=out)
        for c in project.nearby_projects(root):
            print(f"  このフォルダではありませんか: {c.name}", file=out)
        return 2

    # Taken after the prompt: a double-clicked exe may wait minutes before a folder is dropped.
    now = now or datetime.now()
    pf = project.collect(root, rules, env)
    log_path = Path(project.clean_path_arg(args.editor_log)) if args.editor_log else paths.default_editor_log(env)
    lf = editorlog.parse(log_path, rules, pf.root)
    if lf.project_match == "mismatch" and lf.log_project:
        mask = Masker([raw, os.path.abspath(raw)], [lf.log_project])
    findings = checks.judge(pf, lf, rules, now.date())

    print(report.screen(findings, pf, lf, rules, mask, args.verbose), file=out)

    if not args.no_report:
        folder = Path(args.out) if args.out else paths.output_dir(env)
        dest = folder / f"report-{now:%Y%m%d-%H%M%S}.txt"
        try:
            folder.mkdir(parents=True, exist_ok=True)
            dest.write_text(report.render_report(findings, pf, lf, rules, mask, now), encoding="utf-8-sig")
            print(mask(f"レポートを保存しました: {dest}"), file=out)
        except OSError as e:
            print(mask(f"レポートを保存できませんでした: {dest}（{e.strerror or e}）"), file=out)
    return checks.exit_code(findings)
