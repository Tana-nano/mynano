"""nano のコマンドライン入口。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import calibration as calibration_module
from .. import doctor as doctor_module
from ..app import App
from ..config import load_config
from ..memory import reembed as reembed_module
from ..memory.retrieve import recall, recall_explicit
from ..persona import dataset as dataset_module
from ..persona import drift as drift_module
from ..store import archive, entities as entities_store, identity as identity_store  # noqa: E501
from ..store import jobs as jobs_store
from ..store import proposals as proposals_store, stars as stars_store
from ..store import state as state_store
from ..store.db import to_iso
from ..unconscious.daemon import Daemon
from ..viewer import data as graph_data
from ..viewer import page as graph_page
from ..viewer import server as graph_server
from . import chat as chat_cli


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nano", description="ローカル永続AIコンパニオン")
    parser.add_argument("--config", default=None, help="config.toml のパス")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="LLM/埋め込みサーバーを使わずスタブで動かす（配線確認・テスト用）",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    chat = sub.add_parser("chat", help="対話する")
    chat.add_argument("--session", default=None)

    daemon = sub.add_parser("daemon", help="無意識を常駐させる")
    daemon.add_argument("--once", action="store_true", help="1 tick だけ動かして終わる")
    daemon.add_argument("--verbose", action="store_true", help="することが無くても喋る")
    daemon.add_argument(
        "--now", action="store_true", help="アイドルを待たずに動かす（夜間処理を手で走らせる用）"
    )

    sub.add_parser("doctor", help="実機に載せる前の点検（繋がるか・次元・ものさし・基準）")
    sub.add_parser("jobs", help="無意識のジョブキューを見る")
    sub.add_parser("review", help="無意識からの人格変更の提案を承認/却下する")

    sub.add_parser("sleep", help="未処理の会話を記憶に変える（書き込みパイプライン）")
    sub.add_parser("decay", help="忘却処理（cold化と統合）")
    sub.add_parser("stats", help="記憶の量を見る")
    calibrate = sub.add_parser(
        "calibrate", help="いまの埋め込みモデルのものさしを実測する（モデルを替えたら回す）"
    )
    calibrate.add_argument("--pairs", type=int, default=calibration_module.MAX_PAIRS)

    reembed = sub.add_parser("reembed", help="記憶を今の埋め込みモデルで埋め直す")
    reembed.add_argument("--yes", action="store_true", help="確認を飛ばす")

    graph = sub.add_parser("graph", help="記憶グラフを見る（ブラウザ）")
    graph.add_argument("--export", metavar="FILE", help="サーバーを立てず、単体のHTMLに書き出す")
    graph.add_argument("--port", type=int, default=graph_server.DEFAULT_PORT)
    graph.add_argument("--host", default="127.0.0.1")
    graph.add_argument("--limit", type=int, default=graph_data.DEFAULT_LIMIT,
                       help="描く記憶の上限。多すぎると読めなくなる")
    graph.add_argument("--no-open", action="store_true", help="ブラウザを開かない")

    sub.add_parser("export", help="ノートを Markdown に書き出す")
    sub.add_parser("backup", help="soul.db のスナップショットを取る")

    search = sub.add_parser("recall", help="記憶を検索する")
    search.add_argument("query")
    search.add_argument("--explicit", action="store_true", help="意味検索ではなく文字列で探す")

    probe = sub.add_parser("probe", help="人格プローブを実行し、基準からのずれを測る")
    probe.add_argument("--save-baseline", action="store_true", help="今回の応答を新しい基準にする")

    stars = sub.add_parser("stars", help="⭐ を付けた応答を見る（人格の教師データの素材）")
    stars.add_argument("--limit", type=int, default=20)
    stars.add_argument(
        "--avoid", action="store_true", help="「こうは喋ってほしくない」側だけ見る"
    )

    dataset = sub.add_parser(
        "dataset", help="⭐ から QLoRA の教師データを書き出す（soul/export/train/）"
    )
    dataset.add_argument(
        "--force",
        action="store_true",
        help="人格ベースラインが無くても書き出す（計測を飛ばすことになる。非推奨）",
    )

    state = sub.add_parser("state", help="working_state の確認と設定")
    state.add_argument("key", nargs="?")
    state.add_argument("value", nargs="?")
    state.add_argument("--history", action="store_true", help="書き換えの監査ログを見る")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "doctor":
        if args.offline:
            # 点検の相手は実機の構成そのもの。--offline で診ても、
            # スタブが健康だと報告されるだけで何の役にも立たない。
            print(
                "doctor は実機の構成を診るものなので --offline とは併用できません。",
                file=sys.stderr,
            )
            return 2
        # App を組み立てない。埋め込みが食い違っていると App.build は起動を止めるが、
        # まさにその状態を診るための道具なので、止まってしまっては役に立たない。
        report = doctor_module.run(load_config(args.config))
        print(report.render())
        return 1 if report.failed else 0

    holder = "daemon" if args.command == "daemon" else "chat"
    try:
        app = App.create(
            config_path=args.config,
            offline=args.offline,
            holder=holder,
            # 埋め直しだけは、モデルが変わっている状態で起動できないと始まらない
            allow_new_embedder=(args.command == "reembed"),
        )
    except identity_store.EmbeddingMismatch as mismatch:
        print(mismatch, file=sys.stderr)
        return 2
    try:
        return _dispatch(app, args)
    finally:
        app.close()


def _dispatch(app: App, args) -> int:
    if args.command == "chat":
        return chat_cli.run(app, args.session)

    if args.command == "daemon":
        daemon = Daemon(app, verbose=args.verbose, force=args.now)
        if not args.once:
            return daemon.run()
        message = daemon.tick()
        print(message or "することなし")
        return 0

    if args.command == "jobs":
        summary = jobs_store.summary(app.db)
        if not summary:
            print("キューは空です。")
        for kind, states in sorted(summary.items()):
            print(f"{kind}: " + ", ".join(f"{state}={count}" for state, count in sorted(states.items())))
        failures = jobs_store.recent_failures(app.db)
        if failures:
            print("\n最近の失敗:")
            for failure in failures:
                print(f"  {to_iso(failure['updated_at'])} {failure['kind']}: {failure['last_error'][:120]}")
        pending_proposals = proposals_store.count_pending(app.db)
        if pending_proposals:
            print(f"\n人格変更の提案が {pending_proposals} 件、承認待ちです（nano review）")
        return 0

    if args.command == "review":
        return _review(app)

    if args.command == "sleep":
        print(app.ingest())
        return 0

    if args.command == "decay":
        print(app.run_decay())
        return 0

    if args.command == "stats":
        for key, value in app.stats().items():
            print(f"{key}: {value}")
        if app.calibration is None:
            print("calibration: 未測定（しきい値は config.toml の絶対値を使用中 — nano calibrate）")
        else:
            print(
                f"calibration: {to_iso(app.calibration.measured_at)[:10]} 実測 "
                f"({app.calibration.source}, {app.calibration.similarity.n} ペア)"
            )
        top = entities_store.counts(app.db, limit=10)
        if top:
            print("よく出てくる固有名詞: " + ", ".join(f"{name}({count})" for name, count in top))
        return 0

    if args.command == "calibrate":
        print(f"{app.embedder.identity} のものさしを測っています…")
        measured = calibration_module.measure(app, max_pairs=args.pairs)
        target = calibration_module.save(app.config, measured)
        app.reload_calibration()
        print()
        print(measured.describe())
        print()
        print("設定値（左: config.toml の絶対値 / 右: 実測に基づく実効値）")
        for label, absolute, effective in calibration_module.recommendations(measured, app.config):
            print(f"  {label}")
            print(f"      {absolute:.3f}  →  {effective:.3f}")
        print()
        print(f"保存しました: {target}")
        print("これ以降、しきい値は測定した分布に対する相対位置で決まります。")
        return 0

    if args.command == "reembed":
        current = identity_store.recorded(app.db)
        count = app.db.scalar("SELECT COUNT(*) FROM notes") or 0
        print(f"記憶 {count} 件を {app.embedder.identity} で埋め直します。")
        if current and current != app.embedder.identity:
            print(f"（いまの魂は {current} で作られています）")
        print("ノートの本文・リンク・重要度・半減期は変わりません。変わるのは検索用の座標だけです。")
        if not args.yes:
            try:
                if input("続けますか? [y/N] ").strip().lower() != "y":
                    print("やめました。")
                    return 0
            except EOFError:
                print("やめました。")
                return 0

        def progress(done: int, total: int) -> None:
            print(f"  {done}/{total}", end="\r", flush=True)

        report = reembed_module.run(app, on_progress=progress)
        print(" " * 30, end="\r")
        print(report)
        print("分布も変わっているので、続けて `nano calibrate` を回してください。")
        return 0

    if args.command == "graph":
        if args.export:
            payload = graph_data.build(app.db, app.config.decay, limit=args.limit)
            target = Path(args.export)
            target.parent.mkdir(parents=True, exist_ok=True)
            html = graph_page.render(f"{app.config.persona.name} の記憶", payload=payload.to_dict())
            target.write_text(html, encoding="utf-8")
            print(f"{payload.stats['shown']} 件の記憶を {target} に書き出しました。")
            print("このファイル1枚で完結しています。外部の読み込みはありません。")
            return 0
        return graph_server.serve(
            app, host=args.host, port=args.port, limit=args.limit, open_browser=not args.no_open
        )

    if args.command == "export":
        count = archive.export_notes(app.db, app.config.export_dir)
        print(f"{count} 件のノートを {app.config.export_dir} に書き出しました。")
        return 0

    if args.command == "backup":
        target = app.db.backup(app.config.backup_dir)
        print(f"スナップショット: {target}")
        return 0

    if args.command == "recall":
        if args.explicit:
            found = recall_explicit(app.db, args.query)
            for note in found:
                mark = "" if note.state == "active" else f" [{note.state}]"
                print(f"#{note.id}{mark} ({to_iso(note.created_at)[:10]}) {note.content}")
            if not found:
                print("該当なし。")
            return 0
        result = recall(
            app.db,
            app.index,
            app.embedder,
            args.query,
            app.config.retrieval,
            app.config.decay,
            touch=False,
        )
        print(result.trace())
        return 0

    if args.command == "probe":
        report = drift_module.run(
            app.config, app.db, app.llm, app.embedder, save_baseline=args.save_baseline
        )
        if not report.results:
            print("プローブが定義されていません。", app.config.probes_path)
            return 1
        if report.baseline_created:
            print(f"基準を保存しました: {drift_module.baseline_path(app.config)}")
        mean = report.mean_similarity
        if mean is None:
            print(f"{len(report.results)} 問に回答。次回からずれを測れます。")
            return 0
        print(f"平均類似度: {mean:.3f}（1.0 に近いほど「同じ存在」）")
        print("ずれの大きい質問:")
        for result in report.worst():
            print(f"  {result.similarity:.3f} [{result.probe.category}] {result.probe.prompt}")
            print(f"        → {result.answer[:120]}")
        return 0

    if args.command == "stars":
        rating = stars_store.RATING_AVOID if args.avoid else None
        marks = stars_store.recent(app.db, limit=args.limit, rating=rating)
        if not marks:
            print("まだ何にも印が付いていません（nano chat の /star）。")
        for turn in marks:
            label = "⭐" if turn.star.rating > 0 else "✗"
            print(f"{label} {to_iso(turn.ts)[:16]} #{turn.star.event_id}")
            print(f"    あなた: {turn.user_text[:80]}")
            print(f"    {app.config.persona.name}: {turn.answer[:80]}")
            if turn.star.reason:
                print(f"    理由: {turn.star.reason}")
        counts = stars_store.counts(app.db)
        print(f"\n合計: ⭐{counts['keep']} / ✗{counts['avoid']}")
        return 0

    if args.command == "dataset":
        try:
            target, built = dataset_module.export(
                app.config, app.db, embedding_identity=app.embedder.identity, force=args.force
            )
        except dataset_module.BaselineMissing as missing:
            print(missing, file=sys.stderr)
            return 2
        print(f"{built} → {target}")
        if not built.keep:
            print("⭐ がまだありません。まずは会話しながら /star を押してください。")
            return 0
        if not built.pairs and built.avoid:
            print(
                "ORPO の対はまだ0件です。chat の中で /again を使うと、"
                "同じプロンプトに対する ⭐ と ✗ が揃って対になります。"
            )
        print("学習の順番（CLAUDE.md §8）: 計測 → 少量・低rank → 再計測")
        print("  1. nano probe          （学習前のずれを記録）")
        print("  2. QLoRA（8B / 低rank / ORPO寄り。大量の SFT は人格を薄める）")
        print("  3. nano probe          （別人になっていないかを同じ物差しで測る）")
        return 0

    if args.command == "state":
        if args.key and args.history:
            for row in state_store.history(app.db, args.key):
                print(f"{to_iso(row['ts'])} {row['key']} ({row['updated_by']}): {row['new_value'][:100]}")
            return 0
        if args.key and args.value is not None:
            state_store.set_value(app.db, args.key, args.value, updated_by="human")
            print(f"{args.key} を設定しました。")
            return 0
        for key, value in state_store.all_state(app.db).items():
            print(f"{key}: {value or '(なし)'}")
        return 0

    return 1


def _review(app: App) -> int:
    """人格変更の提案を人間が裁く。

    無意識は identity / user_model を書き換えられない。ここを通ったものだけが
    working_state に入り、監査ログには updated_by='human' として残る。
    """
    pending = proposals_store.pending(app.db)
    if not pending:
        print("承認待ちの提案はありません。")
        return 0

    for proposal in pending:
        print(f"\n── 提案 #{proposal.id} [{proposal.target}] {to_iso(proposal.created_at)}")
        print(f"いま  : {proposal.current_value or '(未設定)'}")
        print(f"提案  : {proposal.proposed_value}")
        if proposal.rationale:
            print(f"理由  : {proposal.rationale}")
        try:
            answer = input("承認する? [y/n/s=保留/q=終了] ").strip().lower()
        except EOFError:
            answer = "q"

        if answer == "q":
            break
        if answer == "s":
            continue
        if answer == "y":
            state_store.set_value(app.db, proposal.target, proposal.proposed_value, updated_by="human")
            proposals_store.decide(app.db, proposal.id, proposals_store.STATUS_ACCEPTED)
            print("反映しました。")
        else:
            proposals_store.decide(app.db, proposal.id, proposals_store.STATUS_REJECTED)
            print("却下しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
