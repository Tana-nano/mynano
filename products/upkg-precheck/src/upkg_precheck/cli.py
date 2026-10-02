"""Command line: read inputs, judge, print, save the results; the drop screen when used by mouse."""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, TextIO

from . import APP_NAME, DISPLAY_NAME, known as known_mod
from .app import App
from .archive import SUPPORTED, Limits, expand_inputs
from .checks import Options
from .console import enable_color, setup_console
from .known import KnownAssets
from .pipeline import Outcome, Settings, inspect, save_outcome
from .report import header, run_dir_name

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
    p.add_argument("--no-report", action="store_true", help="レポート（report.txt・report.html）を保存しない")
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
    color: bool | None = None  # None: decide from the real console
    open_file: Callable[[Path], None] | None = None  # None: open_in_browser
    open_url: Callable[[str], object] | None = None  # None: open_url


def open_in_browser(path: Path) -> None:
    """Show report.html (or a folder in Explorer) on Windows; elsewhere do nothing."""
    # UNVERIFIED: os.startfile with a .html file or a folder was not run on Windows in development.
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]


def open_url(url: str) -> None:
    """Open the drop screen in the default browser."""
    # UNVERIFIED: webbrowser on Windows (it uses os.startfile for the default browser).
    import webbrowser

    webbrowser.open(url)


def windows_documents() -> Path | None:
    """The real Documents folder on Windows (follows OneDrive redirection), or None."""
    if os.name != "nt":
        return None
    # Checked on Windows 11 without OneDrive (2026-10-01).
    # UNVERIFIED: a Documents folder redirected to OneDrive. Falls back to ~/Documents on any error.
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]

        # FOLDERID_Documents {FDD39AD0-238F-46AF-ADB4-6C85480369C7}
        fid = GUID(0xFDD39AD0, 0x238F, 0x46AF, (ctypes.c_ubyte * 8)(0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7))
        buf = ctypes.c_wchar_p()
        shell32 = ctypes.windll.shell32  # type: ignore[attr-defined]
        if shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(buf)) != 0:
            return None
        try:
            return Path(buf.value) if buf.value else None
        finally:
            ctypes.windll.ole32.CoTaskMemFree(buf)  # type: ignore[attr-defined]
    except Exception:
        return None


def documents_dir(environ: Mapping[str, str], known_folder: Callable[[], Path | None] = windows_documents) -> Path:
    override = environ.get("UPKG_PRECHECK_DOCS")
    if override:
        return Path(override)
    for docs in (known_folder(), Path.home() / "Documents"):
        if docs is not None and docs.is_dir():
            return docs
    return Path.cwd()


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

    color = env.color if env.color is not None else (env.out is None and enable_color(out))
    apps: list[App] = []
    try:
        code = run(argv, env, say, interactive=pause, color=color, apps=apps)
    except Exception as e:  # last resort: never close the window with a bare traceback
        say(f"予期しないエラーが起きました: {type(e).__name__}: {e}")
        code = 2
    try:
        if pause:
            try:
                env.input("\n使い終わったら、Enter キーを押すと閉じます…" if apps else "\nEnter キーを押すと閉じます…")
            except (EOFError, KeyboardInterrupt):
                pass
    finally:
        for a in apps:
            a.stop()
    return code


def run(argv: list[str], env: Env, say: Callable[[str], None], interactive: bool = False, color: bool = False,
        apps: list[App] | None = None) -> int:
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
    settings = Settings(Limits(args.max_text_mb << 20, args.max_read_mb << 20, args.zip_depth),
                        Options(max_path=args.max_path, max_referrers=args.max_referrers, allow_exe=args.allow_exe),
                        args.max_referrers, args.verbose, not args.no_report, not args.no_draft)
    environ = os.environ if env.environ is None else env.environ
    root = Path(args.out) if args.out else documents_dir(environ) / APP_NAME
    root_label = str(root) if args.out else f"ドキュメント\\{APP_NAME}"
    if not args.paths:
        # Double click: open the drop screen instead of explaining how to drag onto the icon.
        if interactive and apps is not None and _serve(env, say, known, settings, root, root_label, apps, None):
            return 0
        say(USAGE)
        return 2

    files, messages = expand_inputs(args.paths)
    for m in messages:
        say(m)
    o = inspect(files, settings, known, say, color)
    if o is None:
        return 2
    if args.no_report and args.no_draft:
        return o.code
    now = env.now()
    first = next((Path(a) for a in args.paths
                  if Path(a).is_dir() or (Path(a).is_file() and Path(a).suffix.lower() in SUPPORTED)), files[0][0])
    folder = root / run_dir_name(first, now)
    try:
        save_outcome(o, settings, known, now, folder)
    except OSError as e:
        say(f"保存できませんでした: {folder}（{e.strerror or e}）")
        return 2
    rp, dp, hp = o.saved
    if hp:
        say(f"結果のページ: {hp}")
    if rp:
        say(f"レポート: {rp}")
    if dp:
        say(f"説明書の下書き: {dp}")
    # Drag & drop: show the result on the drop screen, where the next file can be dropped.
    # Batch runs (any option given) stay quiet.
    if hp and interactive:
        if apps is not None and _serve(env, say, known, settings, root, root_label, apps, (o, now)):
            return o.code
        try:
            (env.open_file or open_in_browser)(hp)
        except OSError as e:
            say(f"結果のページを開けませんでした（{e.strerror or e}）。上の場所から開いてください。")
    return o.code


def _serve(env: Env, say: Callable[[str], None], known: KnownAssets, settings: Settings, root: Path,
           root_label: str, apps: list[App], result: tuple[Outcome, datetime] | None) -> bool:
    """Start the drop screen and open it in the browser; False if it could not start."""
    app = App(known, settings, root, root_label, env.now, say, env.open_file or open_in_browser)
    try:
        url = app.start()
    except OSError as e:
        say(f"検品の画面を用意できませんでした（{e.strerror or e}）。")
        app.stop()
        return False
    apps.append(app)
    if result is not None:
        url = app.url(app.add_result(*result))
    say("")
    if result is None:
        say("ブラウザで検品の画面を開きます。調べたいファイルを、その画面にドロップしてください。")
    else:
        say("結果をブラウザで開きます。続けて別のファイルを調べるときは、その画面にドロップしてください。")
    say(f"画面が開かないときは、このアドレスをブラウザに貼ってください: {url}")
    say("この窓を閉じると、画面からは調べられなくなります。")
    try:
        (env.open_url or open_url)(url)
    except Exception as e:  # the address above still works
        say(f"ブラウザを開けませんでした（{e}）。")
    return True
