"""Command line: read inputs, judge, print, save report.txt and readme-draft.md."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, TextIO

from . import APP_NAME, DISPLAY_NAME, known as known_mod
from .archive import SUPPORTED, InputRecord, Limits, expand_inputs, make_names_unique, read_input
from .checks import Options, analyze, exit_code, summary, zip_counts
from .console import setup_console
from .draft import render_draft
from .known import KnownAssets
from .report import header, render_report, run_dir_name, save, screen_lines

USAGE = ("使い方: 検品したい zip（または unitypackage、それらが入ったフォルダ）を、"
         "このアイコンに重ねてドロップしてください。")


class ArgError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise ArgError(message)


def _ranged(lo: int, hi: int) -> Callable[[str], int]:
    def conv(s: str) -> int:
        try:
            v = int(s)
        except ValueError:
            raise argparse.ArgumentTypeError(f"数値で指定してください: {s}") from None
        if not lo <= v <= hi:
            raise argparse.ArgumentTypeError(f"{lo}〜{hi} の範囲で指定してください: {v}")
        return v

    return conv


def build_parser() -> argparse.ArgumentParser:
    p = _Parser(prog="upkg-precheck", description=f"{DISPLAY_NAME}: Booth に出す zip / unitypackage を出品前に検品します")
    p.add_argument("paths", nargs="*", help="zip、unitypackage、またはそれらが入ったフォルダ")
    p.add_argument("--out", help="レポートと下書きの保存先の親フォルダ（既定: ドキュメント\\UpkgPrecheck）")
    p.add_argument("--no-report", action="store_true", help="レポートを保存しない")
    p.add_argument("--no-draft", action="store_true", help="説明書の下書きを保存しない")
    p.add_argument("--max-path", type=_ranged(5, 1000), default=150, help="インポート先のパスの長さの上限（既定 150）")
    p.add_argument("--max-text-mb", type=_ranged(1, 1024), default=64, help="参照を調べるファイル 1 個の上限 MB（既定 64）")
    p.add_argument("--max-read-mb", type=_ranged(1, 65536), default=8192, help="zip から読む合計量の上限 MB（既定 8192）")
    p.add_argument("--max-referrers", type=_ranged(1, 100), default=5, help="参照元の表示件数（既定 5）")
    p.add_argument("--zip-depth", type=_ranged(1, 3), default=2, help="zip の中の zip を開く深さ（既定 2）")
    p.add_argument("--allow-exe", action="store_true", help="実行ファイルを赤ではなく黄にする（ツール商品の検品用）")
    p.add_argument("--verbose", action="store_true", help="例を全件表示する")
    p.add_argument("--no-pause", action="store_true", help="終了時に Enter を待たない")
    p.add_argument("--version", action="store_true", help="バージョンと辞書の日付を表示する")
    return p


@dataclass
class Env:
    """Everything that touches the outside world, injectable for tests."""

    out: TextIO | None = None
    now: Callable[[], datetime] = datetime.now
    input: Callable[[str], str] = input
    isatty: Callable[[], bool] = field(default=lambda: sys.stdin is not None and sys.stdin.isatty())
    environ: Mapping[str, str] | None = None
    known: KnownAssets | None = None


def documents_dir(environ: Mapping[str, str]) -> Path:
    override = environ.get("UPKG_PRECHECK_DOCS")
    if override:
        return Path(override)
    docs = Path.home() / "Documents"
    return docs if docs.is_dir() else Path.cwd()


def main(argv: list[str] | None = None, env: Env | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    env = env or Env()
    if env.out is None:
        setup_console()
    out = env.out or sys.stdout
    # Drag & drop and double click pass no options: keep the console open then.
    pause = not any(a.startswith("-") for a in argv) and env.isatty()

    def say(line: str = "") -> None:
        print(line, file=out, flush=True)

    try:
        code = run(argv, env, say)
    except Exception as e:  # last resort: never close the window with a bare traceback
        say(f"予期しないエラーが起きました: {type(e).__name__}: {e}")
        code = 2
    if pause:
        try:
            env.input("\nEnter キーを押すと閉じます…")
        except (EOFError, KeyboardInterrupt):
            pass
    return code


def run(argv: list[str], env: Env, say: Callable[[str], None]) -> int:
    try:
        args = build_parser().parse_args(argv)
    except ArgError as e:
        say(f"指定が正しくありません: {e}")
        return 2
    try:
        known = env.known or known_mod.load()
    except known_mod.DictionaryError as e:
        say(f"{e}（ツールが壊れている可能性があります。入れ直してください）")
        return 2
    say(header(known))
    if args.version:
        return 0
    if not args.paths:
        say(USAGE)
        return 2

    files, messages = expand_inputs(args.paths)
    for m in messages:
        say(m)
    limits = Limits(args.max_text_mb << 20, args.max_read_mb << 20, args.zip_depth)
    inputs: list[InputRecord] = []
    for f in files:
        say(f"調べています: {f.name}")
        try:
            inputs.append(read_input(f, limits))
        except OSError as e:
            say(f"{f.name}: 読めませんでした（{e.strerror or e}）")
    if not inputs:
        say("調べられるファイルがありませんでした。")
        return 2
    make_names_unique(inputs)

    opts = Options(max_path=args.max_path, max_referrers=args.max_referrers, allow_exe=args.allow_exe)
    analysis = analyze(inputs, known, opts)
    for r in inputs:
        if r.zip is not None:
            say("")
            say(r.name)
            say("  " + zip_counts(r.zip))
    say("")
    for line in screen_lines(analysis.findings, args.verbose):
        say(line)
    say("")
    say(f"結果: {summary(analysis.findings)}")
    code = exit_code(analysis.findings)

    if args.no_report and args.no_draft:
        return code
    now = env.now()
    environ = os.environ if env.environ is None else env.environ
    root = Path(args.out) if args.out else documents_dir(environ) / APP_NAME
    first = next((Path(a) for a in args.paths if Path(a).is_dir() or Path(a).suffix.lower() in SUPPORTED), files[0])
    folder = root / run_dir_name(first, now)
    report_text = None if args.no_report else render_report(inputs, analysis, known, now, args.max_referrers)
    draft_text = None if args.no_draft else render_draft(inputs, analysis, known)
    try:
        rp, dp = save(folder, report_text, draft_text)
    except OSError as e:
        say(f"保存できませんでした: {folder}（{e.strerror or e}）")
        return 2
    if rp:
        say(f"レポート: {rp}")
    if dp:
        say(f"説明書の下書き: {dp}")
    return code
