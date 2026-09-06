"""記憶を新しい埋め込みモデルで埋め直す。

モデルの差し替えを「破壊」ではなく「交換」にするための手続き。
ノートの本文・リンク・重要度・半減期は一切変わらない。
変わるのは、それらを検索するための座標だけ。

臓器を取り替えるのであって、記憶を捨てるのではない。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..store import identity as identity_store
from ..store import notes as notes_store

BATCH = 32


@dataclass
class ReembedReport:
    notes: int
    backup_path: str
    identity: str

    def __str__(self) -> str:
        return (
            f"{self.notes} 件の記憶を {self.identity} で埋め直しました。\n"
            f"念のため、前の状態は {self.backup_path} に残してあります。"
        )


def run(app, on_progress: Callable[[int, int], None] | None = None) -> ReembedReport:
    # 先にバックアップ。途中で落ちても元に戻せるようにしてから触る。
    backup_path = app.db.backup(app.config.backup_dir)

    targets = notes_store.iter_notes(
        app.db,
        states=(notes_store.STATE_ACTIVE, notes_store.STATE_COLD, notes_store.STATE_MERGED),
    )
    total = len(targets)

    for start in range(0, total, BATCH):
        batch = targets[start : start + BATCH]
        payloads = [
            note.content + ("\n" + note.context if note.context else "") for note in batch
        ]
        for note, vector in zip(batch, app.embedder.embed_documents(payloads)):
            notes_store.set_vector(app.db, note.id, vector)
        if on_progress is not None:
            on_progress(min(start + BATCH, total), total)

    identity_store.record(app.db, app.embedder.identity)
    app.index.load()  # 新しい座標で索引を作り直す
    return ReembedReport(notes=total, backup_path=str(backup_path), identity=app.embedder.identity)
