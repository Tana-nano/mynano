"""会話を記憶に変える / 忘れる。

M1 で作った `app.ingest()` と `app.run_decay()` をそのまま呼ぶだけ。
人間が `/sleep` と `nano decay` を叩いていたものを、無意識が勝手にやるようになる。
"""

from __future__ import annotations


def run(app, job) -> str:
    return str(app.ingest())


def run_decay(app, job) -> str:
    return str(app.run_decay())
