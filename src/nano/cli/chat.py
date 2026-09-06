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
from ..store import state as state_store
from ..store.db import to_iso

HELP = """\
コマンド:
  /why              直前の応答でどの記憶を、なぜ引いたか
  /recall <語>      明示検索（薄れた記憶・統合された記憶も掘り起こす）
  /focus [文]       いま気にしていること（無意識が書き換える場所を手で覗く/置く）
  /sleep            未処理の会話を記憶に変える（書き込みパイプライン）
  /decay            忘却処理を実行する（cold化と統合）
  /stats            記憶の量
  /help /quit
"""


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
