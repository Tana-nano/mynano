"""無意識がやる仕事。

各ハンドラは `handler(app, job) -> str`（人が読めるログ行を返す）。
app.llm は実行中だけ CancellableLLM に包まれているので、
対話が割り込めば奥の生成まで中断される。
"""

from __future__ import annotations

from typing import Callable

from . import associate, curate, ingest, reflect, remember

HANDLERS: dict[str, Callable] = {
    "write": remember.run,
    "decay": remember.run_decay,
    "associate": associate.run,
    "reflect": reflect.run,
    "curate": curate.run,
    "ingest": ingest.run,
}

__all__ = ["HANDLERS", "associate", "curate", "ingest", "reflect", "remember"]
