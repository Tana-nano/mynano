"""osc-doctor command line: collect facts, judge, print, save the report."""

from __future__ import annotations

import argparse
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, TextIO

from pythonosc.udp_client import SimpleUDPClient

from . import DISPLAY_NAME, VERSION, cache, checks, oscquery, paths, receiver, report
from .console import setup_console
from .sysinfo import INSTALLER_EXE, VR_RUNTIME_EXES, VRCHAT_EXE, PsutilSystemInfo, SystemInfo, parse_osc_arg

SEND_TEST_TEXT = "OSCドクター: 送信テスト"


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
    p = argparse.ArgumentParser(prog="osc-doctor", description=f"{DISPLAY_NAME}: VRChat の OSC が動かない原因を調べます")
    p.add_argument("--seconds", type=_ranged(1, 120), default=10, help="受信の計測時間（秒、既定 10）")
    p.add_argument("--browse-seconds", type=_ranged(1, 30), default=3, help="VRChat の OSCQuery を探す時間（秒、既定 3）")
    p.add_argument("--in-port", type=_ranged(1, 65535), help="VRChat の受信ポート（既定 9000）")
    p.add_argument("--out-port", type=_ranged(1, 65535), help="VRChat の送信ポート（既定 9001）")
    p.add_argument("--oscquery-port", type=_ranged(1, 65535), help="VRChat の OSCQuery ポート（既定 9001）")
    p.add_argument("--send-test", action="store_true", help="チャットボックスに送信テストを送る")
    p.add_argument("--fix-cache", action="store_true", help="アバター設定キャッシュを退避する（確認あり）")
    p.add_argument("--yes", action="store_true", help="確認を省略する")
    p.add_argument("--verbose", action="store_true", help="受信したアドレスの一覧も表示する")
    p.add_argument("--out", help="レポートの保存先フォルダ")
    p.add_argument("--no-report", action="store_true", help="レポートを保存しない")
    p.add_argument("--no-pause", action="store_true", help="終了時に Enter を待たない（引数なしの起動時のみ待ちます）")
    p.add_argument("--version", action="version", version=f"{DISPLAY_NAME} {VERSION}")
    return p


@dataclass
class Env:
    """Everything that touches the outside world, injectable for tests."""

    sysinfo: SystemInfo = field(default_factory=PsutilSystemInfo)
    browser: oscquery.Browser | None = field(default_factory=oscquery.ZeroconfBrowser)
    advertise: oscquery.Advertiser | None = oscquery.zeroconf_advertise
    sleep: Callable[[float], None] = time.sleep
    now: Callable[[], datetime] = datetime.now
    input: Callable[[str], str] = input
    vrc_dir: Path | None = None
    output_dir: Path | None = None
    fixed_host: str = "0.0.0.0"
    send: Callable[[str, int, str, list], None] | None = None
    # Hook for tests: called once the receiver is up (ports known), before counting down.
    on_listening: Callable[["receiver.Receiver"], None] | None = None


def _send(host: str, port: int, address: str, args: list) -> None:
    SimpleUDPClient(host, port).send_message(address, args)


def rx_summary(stats: list[receiver.AddressStats], seconds: float, vrmode: int | None) -> checks.RxSummary:
    total = sum(s.count for s in stats)
    fixed = sum(s.count for s in stats if receiver.ROUTE_FIXED in s.routes)
    oq = sum(s.count for s in stats if receiver.ROUTE_OSCQUERY in s.routes)
    tracking = [s for s in stats if s.address.startswith(receiver.TRACKING_PREFIX) and receiver.ROUTE_OSCQUERY in s.routes]
    tcount = sum(s.count for s in tracking)
    head = next((s for s in tracking if s.address.endswith("/head/pose")), None)
    rate_src = head or (max(tracking, key=lambda s: s.count) if tracking else None)
    rate = rate_src.count / seconds if rate_src and seconds > 0 else None
    params = sum(1 for s in stats if s.address.startswith(receiver.PARAM_PREFIX))
    return checks.RxSummary(total, fixed, oq, len(stats), params, tcount, rate, vrmode)


def run(args: argparse.Namespace, env: Env, out: TextIO) -> int:
    def say(line: str = "") -> None:
        print(line, file=out, flush=True)

    say(f"{DISPLAY_NAME} {VERSION}")
    facts = checks.Facts(explicit_in=args.in_port, explicit_out=args.out_port)

    # 1. system
    try:
        procs = env.sysinfo.processes()
    except Exception:
        procs = []
    names = {p.name.lower() for p in procs}
    vrc = next((p for p in procs if p.name.lower() == VRCHAT_EXE), None)
    facts.vrc_running = vrc is not None
    facts.launch = parse_osc_arg(vrc.cmdline) if vrc else None
    facts.installer_running = INSTALLER_EXE in names
    facts.vr_runtime = any(n in names for n in VR_RUNTIME_EXES)

    def port_state(p: int) -> None:
        try:
            facts.ports[p] = env.sysinfo.udp_port(p)
        except Exception:
            pass

    for p in {facts.nominal_in, facts.out_port}:
        port_state(p)

    # 2. receive: never take the fixed port from another app.
    out_state = facts.port(facts.out_port)
    fixed = None if out_state.in_use else facts.out_port
    collector = receiver.Collector()
    rcv = receiver.Receiver(collector, fixed, advertise=env.advertise, fixed_host=env.fixed_host).start()
    facts.fixed_bound = rcv.fixed_bound

    # 3. find VRChat's OSCQuery in parallel
    oq_port = checks.resolve_oscquery_port(args.oscquery_port, facts.launch)
    disc_box: list[oscquery.DiscoveryResult] = []
    disc_thread = threading.Thread(
        target=lambda: disc_box.append(oscquery.discover(env.browser, args.browse_seconds, oq_port)), daemon=True)
    disc_thread.start()

    if env.on_listening:
        env.on_listening(rcv)

    # 4. measure
    say(f"計測中… {args.seconds} 秒（体を少し動かす・手の形を変える・しゃべってください）")
    tick = lambda left: print(f"\r残り {left:>3} 秒", end="", file=out, flush=True)  # noqa: E731
    clear = lambda: print("\r" + " " * 16 + "\r", end="", file=out)  # noqa: E731
    completed, measured = receiver.wait(args.seconds, env.sleep, tick)
    clear()
    if completed and collector.total() == 0 and facts.vrc_running:
        facts.extended = True
        say("まだ何も届いていません。アバターを動かす・手の形を変える・しゃべってください。もう一度計測します…")
        _, more = receiver.wait(args.seconds, env.sleep, tick)
        measured += more
        clear()
    measured = max(measured, 1)

    disc_thread.join(args.browse_seconds + 5)
    rcv.stop()
    disc = disc_box[0] if disc_box else oscquery.DiscoveryResult(mdns_ok=False, mdns_error="timeout")
    facts.discovery_vrc = disc.vrc
    facts.mdns_ok = disc.mdns_ok and not rcv.advertise_error
    if disc.vrc is not None and disc.vrc.osc_port not in facts.ports:
        port_state(disc.vrc.osc_port)

    stats = collector.snapshot()
    facts.rx = rx_summary(stats, float(measured), collector.vrmode)
    facts.cache = cache.summarize(env.vrc_dir or paths.vrc_dir())

    findings = checks.judge(facts)

    # 5. optional send test
    if args.send_test:
        if facts.vrc_running:
            host = disc.vrc.osc_ip if disc.vrc else "127.0.0.1"
            (env.send or _send)(host, facts.vrc_in, "/chatbox/input", [SEND_TEST_TEXT, True, False])
            findings.append(checks.Finding("SEND_TEST", checks.INFO, "送信テスト",
                                           f"ポート {facts.vrc_in} にチャットを送りました",
                                           ("頭の上に「OSCドクター: 送信テスト」が出ていれば、VRChat への送信は正常です",)))
        else:
            findings.append(checks.Finding("SEND_TEST", checks.INFO, "送信テスト", "VRChat が起動していないため送りませんでした"))

    # 6. show
    say("")
    for line in report.finding_lines(findings):
        say(line)
    if args.verbose:
        say("")
        say("受信したアドレス:")
        for line in report.address_lines(stats):
            say("  " + line)
    say("")
    now = env.now()
    out_dir = Path(args.out) if args.out else (env.output_dir or paths.output_dir())
    code = checks.exit_code(findings)
    if args.no_report:
        say(f"結果: {checks.summary(findings)}")
    else:
        text = report.render_report(findings, facts, stats, float(measured), now)
        try:
            path = report.write_report(text, out_dir, now)
            say(f"結果: {checks.summary(findings)}。レポートを保存しました: {path}")
        except OSError as e:
            say(f"結果: {checks.summary(findings)}。レポートを保存できませんでした: {e}")

    # 7. optional cache backup
    if args.fix_cache:
        code = max(code, fix_cache(env, out_dir, now, args.yes, say))
    return code


def fix_cache(env: Env, out_dir: Path, now: datetime, yes: bool, say: Callable[[str], None]) -> int:
    vdir = env.vrc_dir or paths.vrc_dir()
    summ = cache.summarize(vdir)
    say("")
    if summ is None:
        say("アバター設定のキャッシュ（OSC フォルダ）はありません。何もしませんでした。")
        return 0
    backup = out_dir / "backup"
    say(f"アバター設定のキャッシュ {summ.files} 件を退避します:")
    say(f"  {summ.path}")
    say(f"  → {backup}\\OSC-{now:%Y%m%d-%H%M%S}")
    if not yes:
        try:
            ans = env.input("よろしいですか？ (y/N): ")
        except EOFError:
            ans = ""
        if ans.strip().lower() not in ("y", "yes"):
            say("中止しました。何も変更していません。")
            return 0
    try:
        dest = cache.move_cache(vdir, backup, now)
    except cache.CacheMoveError as e:
        say(f"退避できませんでした（{e}）。何も変更していません。VRChat を終了してから、もう一度実行してください。")
        return 2
    say(f"退避しました: {dest}")
    say("VRChat で OSC を Disable → Enable にするか、アバターを着替え直してください。元に戻すときは、退避したフォルダを OSC という名前で元の場所に戻します。")
    return 0


def main(argv: list[str] | None = None, env: Env | None = None, out: TextIO | None = None) -> int:
    setup_console()
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 2
    stream = out or sys.stdout
    try:
        return run(args, env or Env(), stream)
    except KeyboardInterrupt:
        print("\n中断しました。", file=stream)
        return 2
