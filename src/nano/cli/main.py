"""nano のコマンドライン入口。"""

from __future__ import annotations

import argparse
import sys

from ..app import App
from ..memory.retrieve import recall, recall_explicit
from ..persona import drift as drift_module
from ..store import archive, entities as entities_store, state as state_store
from ..store.db import to_iso
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

    sub.add_parser("sleep", help="未処理の会話を記憶に変える（書き込みパイプライン）")
    sub.add_parser("decay", help="忘却処理（cold化と統合）")
    sub.add_parser("stats", help="記憶の量を見る")
    sub.add_parser("export", help="ノートを Markdown に書き出す")
    sub.add_parser("backup", help="soul.db のスナップショットを取る")

    search = sub.add_parser("recall", help="記憶を検索する")
    search.add_argument("query")
    search.add_argument("--explicit", action="store_true", help="意味検索ではなく文字列で探す")

    probe = sub.add_parser("probe", help="人格プローブを実行し、基準からのずれを測る")
    probe.add_argument("--save-baseline", action="store_true", help="今回の応答を新しい基準にする")

    state = sub.add_parser("state", help="working_state の確認と設定")
    state.add_argument("key", nargs="?")
    state.add_argument("value", nargs="?")
    state.add_argument("--history", action="store_true", help="書き換えの監査ログを見る")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    app = App.create(config_path=args.config, offline=args.offline)
    try:
        return _dispatch(app, args)
    finally:
        app.close()


def _dispatch(app: App, args) -> int:
    if args.command == "chat":
        return chat_cli.run(app, args.session)

    if args.command == "sleep":
        print(app.ingest())
        return 0

    if args.command == "decay":
        print(app.run_decay())
        return 0

    if args.command == "stats":
        for key, value in app.stats().items():
            print(f"{key}: {value}")
        top = entities_store.counts(app.db, limit=10)
        if top:
            print("よく出てくる固有名詞: " + ", ".join(f"{name}({count})" for name, count in top))
        return 0

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


if __name__ == "__main__":
    sys.exit(main())
