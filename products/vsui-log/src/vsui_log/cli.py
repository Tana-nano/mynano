"""Command line. Double-clicking the exe runs ``run``."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time as _time
import webbrowser
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO

from . import VERSION
from .achievements import ACHIEVEMENTS, current_streak
from .card import FontNotFound, render_card
from .config import ConfigError, ensure_config_file, load_config
from .console import setup_console
from .doctor import PoseRecorder, diagnose, log_sample, record_pose
from .logparse import LogParser
from .oscio import Handlers, OscReceiver, PortInUse, build_dispatcher
from .paths import AppPaths, default_paths
from .report import (
    chapters_text,
    export_csv,
    tonight_html,
    tonight_text,
    tonight_view,
    week_html,
    week_text,
    week_view,
)
from .runner import Runner
from .store import Store

EXIT_OK, EXIT_ERR, EXIT_PORT = 0, 1, 2
NO_DATA = "まだ記録がありません。`vsui-log run` を起動したまま VR 睡眠すると記録されます。"
MSG_NO_POSE_HINT = "頭の動きが 1 件も届きませんでした。VRChat の OSC が有効か、追加の同意が必要でないか確認してください。"


class Ctx:
    def __init__(self, cfg: dict[str, Any], paths: AppPaths, out: TextIO) -> None:
        self.cfg = cfg
        self.paths = paths
        self.out = out

    def print(self, *a: Any) -> None:
        print(*a, file=self.out)

    def store(self) -> Store:
        return Store(self.paths.db_path)

    def output_path(self, name: str) -> Path:
        self.paths.output_dir.mkdir(parents=True, exist_ok=True)
        return self.paths.output_dir / name


def _date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise argparse.ArgumentTypeError("日付は YYYY-MM-DD で指定してください") from None


def _week(s: str) -> tuple[int, int]:
    try:
        y, w = s.upper().split("-W")
        return int(y), int(w)
    except ValueError:
        raise argparse.ArgumentTypeError("週は YYYY-Www（例 2026-W40）で指定してください") from None


def _open(path: Path) -> None:
    if hasattr(os, "startfile"):
        os.startfile(path)  # type: ignore[attr-defined]  # Windows
    else:
        webbrowser.open(path.as_uri())


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vsui-log", description="V睡ログ: VR 睡眠の記録")
    p.add_argument("--version", action="version", version=f"V睡ログ {VERSION}")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("run", help="常駐して記録する（既定）")
    t = sub.add_parser("tonight", help="今夜のまとめ")
    t.add_argument("--date", type=_date)
    t.add_argument("--open", action="store_true")
    w = sub.add_parser("week", help="週次レポート")
    w.add_argument("--week", type=_week)
    w.add_argument("--open", action="store_true")
    c = sub.add_parser("card", help="共有カード PNG")
    c.add_argument("--date", type=_date)
    c.add_argument("--names", action="store_true", help="名前を入れる（相手の同意を得てから）")
    v = sub.add_parser("visitors", help="来客リスト")
    v.add_argument("--date", type=_date)
    th = sub.add_parser("thanks", help="来客に「お礼済み」を付ける")
    th.add_argument("who", help="visitors の番号 または 名前")
    th.add_argument("--date", type=_date)
    e = sub.add_parser("export", help="CSV 出力")
    e.add_argument("--from", dest="start", type=_date)
    e.add_argument("--to", dest="end", type=_date)
    ch = sub.add_parser("chapters", help="来客時刻のチャプターファイル")
    ch.add_argument("--date", type=_date)
    ch.add_argument("--names", action="store_true")
    sub.add_parser("achievements", help="実績一覧")
    f = sub.add_parser("forget", help="記録から人を削除")
    f.add_argument("name", nargs="?")
    f.add_argument("--all", action="store_true")
    f.add_argument("--yes", action="store_true", help="確認しない")
    cf = sub.add_parser("config", help="設定ファイル")
    cf.add_argument("--path", action="store_true", help="場所を表示するだけ")
    d = sub.add_parser("doctor", help="診断")
    d.add_argument("--log-sample", action="store_true", help="名前を伏せたログ 20 行を出力")
    d.add_argument("--pose-sample", nargs="?", const=5.0, type=float, metavar="分", help="頭の動きを記録して CSV 出力")
    return p


# --------------------------------------------------------------------------- commands


def cmd_run(ctx: Ctx, args: argparse.Namespace) -> int:
    runner = Runner(ctx.cfg, ctx.paths, notify=lambda m: ctx.print("\n" + m))
    try:
        runner.start()
    except PortInUse as e:
        ctx.print(f"ポート {e.port} は他の OSC アプリが使っています。設定で osc.mode = \"auto\" にすることをおすすめします。")
        return EXIT_PORT
    except KeyboardInterrupt:
        runner.stop()
        return EXIT_OK
    ctx.print(f"V睡ログ {VERSION} を起動しました。終了するときは Ctrl+C を押してください。")
    errors = 0
    try:
        while True:
            try:
                runner.step()
                errors = 0
            except Exception as e:  # keep recording through one bad step
                errors += 1
                logging.getLogger(__name__).exception("step failed")
                if errors == 1:
                    ctx.print(f"\n予期しないエラーが起きましたが、記録は続けます: {e}")
            ctx.out.write("\r" + runner.status_line().ljust(100))
            ctx.out.flush()
            _time.sleep(1)
    except KeyboardInterrupt:
        ctx.print("\n終了しています…")
    finally:
        runner.stop()
    return EXIT_OK


def cmd_tonight(ctx: Ctx, args: argparse.Namespace) -> int:
    st = ctx.store()
    v = tonight_view(st, args.date)
    if v is None:
        ctx.print(NO_DATA)
        return EXIT_OK
    ctx.print(tonight_text(v))
    path = ctx.output_path(f"tonight_{v.date.isoformat()}.html")
    path.write_text(tonight_html(v), encoding="utf-8")
    ctx.print(f"\nHTML: {path}")
    if args.open:
        _open(path)
    return EXIT_OK


def cmd_week(ctx: Ctx, args: argparse.Namespace) -> int:
    st = ctx.store()
    if args.week:
        year, wk = args.week
    else:
        base = st.latest_night_date() or date.today()
        year, wk, _ = base.isocalendar()
    v = week_view(st, year, wk)
    ctx.print(week_text(v))
    path = ctx.output_path(f"week_{v.label}.html")
    path.write_text(week_html(v), encoding="utf-8")
    ctx.print(f"\nHTML: {path}")
    if args.open:
        _open(path)
    return EXIT_OK


def cmd_card(ctx: Ctx, args: argparse.Namespace) -> int:
    st = ctx.store()
    v = tonight_view(st, args.date)
    if v is None:
        ctx.print(NO_DATA)
        return EXIT_OK
    show = args.names or ctx.cfg["output"]["card_show_names"]
    try:
        img, _ = render_card(v, current_streak(st.all_night_dates(), v.date), show)
    except FontNotFound:
        ctx.print("日本語フォント（游ゴシック / メイリオ / MS ゴシック）が見つからないため、カードを作れませんでした。")
        return EXIT_ERR
    path = ctx.output_path(f"card_{v.date.isoformat()}.png")
    img.save(path)
    ctx.print(f"共有カード: {path}")
    if show:
        ctx.print("※ 名前入りです。公開する前に、写っている人の同意を得てください。")
    return EXIT_OK


def cmd_visitors(ctx: Ctx, args: argparse.Namespace) -> int:
    v = tonight_view(ctx.store(), args.date)
    if v is None or not v.visitors:
        ctx.print("来客はいませんでした。" if v else NO_DATA)
        return EXIT_OK
    for i, x in enumerate(v.visitors, 1):
        ctx.print(f"{i}. {x.time:%H:%M} {x.name}{'  ✓お礼済み' if x.thanked else ''}")
    return EXIT_OK


def cmd_thanks(ctx: Ctx, args: argparse.Namespace) -> int:
    st = ctx.store()
    v = tonight_view(st, args.date)
    if v is None or not v.visitors:
        ctx.print("お礼を付けられる来客がいません。")
        return EXIT_ERR
    target = None
    if args.who.isdigit() and 1 <= int(args.who) <= len(v.visitors):
        target = v.visitors[int(args.who) - 1]
    else:
        target = next((x for x in v.visitors if x.name == args.who), None)
    if target is None:
        ctx.print(f"「{args.who}」は来客リストにいません。`vsui-log visitors` で番号を確認してください。")
        return EXIT_ERR
    st.set_thanked(target.night_id, target.person_id)
    ctx.print(f"{target.name} さんに「お礼済み」を付けました。")
    return EXIT_OK


def cmd_export(ctx: Ctx, args: argparse.Namespace) -> int:
    st = ctx.store()
    dates = st.all_night_dates()
    if not dates:
        ctx.print(NO_DATA)
        return EXIT_OK
    start, end = args.start or dates[0], args.end or dates[-1]
    path = ctx.output_path(f"vsui_export_{date.today():%Y%m%d}.csv")
    n = export_csv(st, start, end, path)
    ctx.print(f"{n} 夜分を書き出しました: {path}")
    return EXIT_OK


def cmd_chapters(ctx: Ctx, args: argparse.Namespace) -> int:
    v = tonight_view(ctx.store(), args.date)
    if v is None:
        ctx.print(NO_DATA)
        return EXIT_OK
    path = ctx.output_path(f"chapters_{v.date.isoformat()}.txt")
    path.write_text(chapters_text(v, args.names), encoding="utf-8")
    ctx.print(f"チャプター: {path}（{len(v.visitors)} 件）")
    return EXIT_OK


def cmd_achievements(ctx: Ctx, args: argparse.Namespace) -> int:
    got = ctx.store().unlocked()
    for key, name in ACHIEVEMENTS.items():
        mark = f"✓ {got[key]['night_date']}" if key in got else "  "
        ctx.print(f"{mark:14} {name}")
    return EXIT_OK


def cmd_forget(ctx: Ctx, args: argparse.Namespace, stdin: TextIO) -> int:
    if not args.all and not args.name:
        ctx.print("削除する名前か --all を指定してください。")
        return EXIT_ERR
    target = "全員" if args.all else f"「{args.name}」"
    if not args.yes:
        ctx.out.write(f"{target}の記録を削除します。元に戻せません。よろしいですか？ [y/N] ")
        ctx.out.flush()
        if stdin.readline().strip().lower() not in ("y", "yes"):
            ctx.print("中止しました。")
            return EXIT_OK
    n = ctx.store().forget(None if args.all else args.name)
    ctx.print(f"{n} 人分の記録を削除しました。")
    return EXIT_OK


def cmd_config(ctx: Ctx, args: argparse.Namespace) -> int:
    created = ensure_config_file(ctx.paths.config_path)
    ctx.print(str(ctx.paths.config_path))
    if created:
        ctx.print("（既定の設定ファイルを作成しました）")
    if not args.path and hasattr(os, "startfile"):
        os.startfile(ctx.paths.config_path)  # type: ignore[attr-defined]
    return EXIT_OK


def cmd_doctor(ctx: Ctx, args: argparse.Namespace) -> int:
    if args.log_sample:
        lines = log_sample(ctx.paths.log_dir, LogParser(ctx.cfg["log"]["patterns"]))
        if not lines:
            ctx.print("対象になるログ行が見つかりませんでした。")
            return EXIT_OK
        path = ctx.output_path("doctor_log_sample.txt")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        ctx.print("\n".join(lines))
        ctx.print(f"\n保存しました（名前・ID・ワールド名は伏せてあります）: {path}")
        return EXIT_OK
    if args.pose_sample is not None:
        osc = ctx.cfg["osc"]

        def start(rec: PoseRecorder):
            noop = lambda *_: None  # noqa: E731
            h = Handlers(pose=rec, afk=noop, vrmode=noop)
            r = OscReceiver(build_dispatcher(h, datetime.now), osc["mode"], osc["listen_port"], 0).start().ready()
            return r.stop

        minutes = max(0.05, args.pose_sample)
        ctx.print(f"{minutes:g} 分間、頭の動きを記録します。VRChat を起動したまま、普段どおり横になってください…")
        try:
            rec = record_pose(start, minutes * 60)
        except PortInUse as e:
            ctx.print(f"ポート {e.port} が使用中です。V睡ログ本体を終了してから実行してください。")
            return EXIT_PORT
        path = ctx.output_path(f"doctor_pose_{datetime.now():%Y%m%d_%H%M}.csv")
        rec.write_csv(path)
        rate = len(rec.rows) / (minutes * 60)
        ctx.print(f"{len(rec.rows)} サンプル（約 {rate:.1f} 回/秒）: {path}")
        if not rec.rows:
            ctx.print(MSG_NO_POSE_HINT)
        return EXIT_OK
    for line in diagnose(ctx.cfg, ctx.paths):
        ctx.print(line)
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    env: Mapping[str, str] | None = None,
    out: TextIO | None = None,
    stdin: TextIO | None = None,
) -> int:
    if out is None:
        out = sys.stdout
        setup_console(sys.stdout, sys.stderr)
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    paths = default_paths(env)
    try:
        ensure_config_file(paths.config_path)
        cfg = load_config(paths.config_path, env)
    except ConfigError as e:
        print(f"設定エラー: {e}", file=out)
        return EXIT_ERR
    except OSError as e:
        print(f"設定ファイルを作成できませんでした: {e}", file=out)
        return EXIT_ERR
    paths = paths.with_overrides(cfg["log"]["directory"], cfg["output"]["directory"])
    ctx = Ctx(cfg, paths, out)
    cmd = args.cmd or "run"
    if cmd == "forget":
        return cmd_forget(ctx, args, stdin or sys.stdin)
    return globals()[f"cmd_{cmd}"](ctx, args)
