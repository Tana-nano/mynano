"""対話 REPL。

/why を最初から入れているのは、記憶が効いているか目視できないと
重みも半減期も一切チューニングできないから。記憶システムでは
可観測性が機能そのものより先に必要になる。
"""

from __future__ import annotations

import sys
from datetime import datetime

from ..app import App
from ..memory.retrieve import Recall, recall_explicit
from ..store import stars as stars_store
from ..store import state as state_store
from ..store.db import to_iso

HELP = """\
コマンド:
  /why              直前の応答でどの記憶を、なぜ引いたか
  /recall <語>      明示検索（薄れた記憶・統合された記憶も掘り起こす）
  /focus [文]       いま気にしていること（無意識が書き換える場所を手で覗く/置く）
  /again            同じプロンプトのまま応答を出し直す（前のは ✗ になり、ORPO の対になる）
  /star [n] [理由]  「これがわたしだ」と思った応答に印を付ける（n=いくつ前か。既定1）
  /avoid [n] [理由] 「こうは喋ってほしくない」応答に印を付ける
  /unstar [n]       付けた印を外す
  /stars [件数]     いままでに付けた印
  /sleep            未処理の会話を記憶に変える（書き込みパイプライン）
  /decay            忘却処理を実行する（cold化と統合）
  /stats            記憶の量
  /help /quit
"""


def _split_count(argument: str) -> tuple[int, str]:
    """「/star 3 いい返し」の 3 と理由を分ける。数字が無ければ直近（1）。"""
    head, _, tail = argument.partition(" ")
    if head.isdigit():
        return max(1, int(head)), tail.strip()
    return 1, argument.strip()


def _mark(app: App, argument: str, rating: int) -> None:
    back, reason = _split_count(argument)
    try:
        exchange = app.star(back=back, rating=rating, reason=reason)
    except IndexError as error:
        print(error)
        return
    label = "⭐" if rating > 0 else "✗"
    excerpt = exchange.answer[:60] + ("…" if len(exchange.answer) > 60 else "")
    print(f"{label} {excerpt}")
    if rating > 0:
        print("   （このときのプロンプトごと保存しました。nano dataset で教師データになります）")


def _read(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return "/quit"


def run(app: App, session_id: str | None = None) -> int:
    session_id = session_id or datetime.now().strftime("s%Y%m%d-%H%M%S")
    name = app.config.persona.name
    last_recall: Recall | None = None

    print(f"— {name} / session {session_id} —")
    print("/help でコマンド一覧。Ctrl-D か /quit で終了（終了時に会話を記憶へ変換します）。\n")

    while True:
        line = _read("あなた> ").strip()
        if not line:
            continue

        if line.startswith("/"):
            command, _, argument = line.partition(" ")
            argument = argument.strip()

            if command in ("/quit", "/exit"):
                break
            if command == "/help":
                print(HELP)
                continue
            if command == "/why":
                print(last_recall.trace() if last_recall else "まだ何も想起していません。")
                continue
            if command == "/recall":
                if not argument:
                    print("使い方: /recall <語>")
                    continue
                found = recall_explicit(app.db, argument)
                if not found:
                    print("該当なし。")
                for note in found:
                    mark = "" if note.state == "active" else f" [{note.state}]"
                    print(f"  #{note.id}{mark} ({to_iso(note.created_at)[:10]}) {note.content}")
                continue
            if command == "/focus":
                if argument:
                    state_store.set_value(app.db, state_store.KEY_CURRENT_FOCUS, argument, "human")
                print("いま気にしていること:", state_store.get(app.db, state_store.KEY_CURRENT_FOCUS) or "(なし)")
                continue
            if command == "/again":
                print(f"{name}> ", end="", flush=True)
                try:
                    app.again(on_token=lambda token: print(token, end="", flush=True))
                except IndexError as error:
                    print(f"\r{error}")
                    continue
                except Exception as error:  # ローカルサーバー未起動などはここに来る
                    print(f"\n[エラー] {error}", file=sys.stderr)
                    continue
                print("\n")
                continue
            if command == "/star":
                _mark(app, argument, stars_store.RATING_KEEP)
                continue
            if command == "/avoid":
                _mark(app, argument, stars_store.RATING_AVOID)
                continue
            if command == "/unstar":
                back, _ = _split_count(argument)
                try:
                    exchange = app.unstar(back=back)
                except IndexError as error:
                    print(error)
                    continue
                print("印を外しました。" if exchange else "そこには印が付いていません。")
                continue
            if command == "/stars":
                limit = int(argument) if argument.isdigit() else 10
                marks = stars_store.recent(app.db, limit=limit)
                if not marks:
                    print("まだ何にも印を付けていません。")
                for turn in marks:
                    label = "⭐" if turn.star.rating > 0 else "✗"
                    reason = f"  — {turn.star.reason}" if turn.star.reason else ""
                    print(f"  {label} {to_iso(turn.ts)[:16]} {turn.answer[:56]}{reason}")
                counts = stars_store.counts(app.db)
                print(f"  合計: ⭐{counts['keep']} / ✗{counts['avoid']}")
                continue
            if command == "/sleep":
                print(app.ingest())
                continue
            if command == "/decay":
                print(app.run_decay())
                continue
            if command == "/stats":
                for key, value in app.stats().items():
                    print(f"  {key}: {value}")
                continue
            print("不明なコマンド。/help を見てください。")
            continue

        print(f"{name}> ", end="", flush=True)
        try:
            _, last_recall = app.say(line, session_id, on_token=lambda token: print(token, end="", flush=True))
        except Exception as error:  # ローカルサーバー未起動などはここに来る
            print(f"\n[エラー] {error}", file=sys.stderr)
            continue
        print("\n")

    print("\n会話を記憶に変換しています…")
    print(" ", app.ingest())
    return 0
