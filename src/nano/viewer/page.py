"""HTML の組み立て。

テンプレートは1枚の自己完結した HTML で、外部の JS も CSS も読み込まない。
CDN を使えばグラフ描画は数行で済むが、ネットが無いと魂が見えなくなる。
「完全ローカル運用」と「10年後も動く」を掲げている以上、そこは自前で書く。
"""

from __future__ import annotations

import json
from pathlib import Path

TEMPLATE = Path(__file__).with_name("index.html")


def render(title: str, payload: dict | None = None, api_base: str | None = None) -> str:
    """データを埋め込んだ HTML を返す。

    payload を渡せば単体で完結したファイルになり、api_base を渡せば
    起動中のサーバーから読みにいく形になる。
    """
    if payload is None:
        data = "null"
    else:
        # 記憶の本文に "</script>" が含まれていてもタグを閉じさせない
        data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")

    return (
        TEMPLATE.read_text(encoding="utf-8")
        .replace("__NANO_TITLE__", _escape(title))
        .replace("__NANO_DATA__", data)
        .replace("__NANO_API__", json.dumps(api_base) if api_base else "null")
    )


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
