"""埋め込みベクトル空間の同一性。

異なる埋め込みモデルで作ったベクトルを同じ空間で比べても意味は無い。
にもかかわらず、次元数さえ合っていればコサイン類似度は「それらしい数字」を返す。
黙って壊れるので、記録して照合する。

    「モデルはいつでも交換可能な臓器で、記憶ストアのほうが本体」

を成り立たせているのは、実のところこの照合と `nano reembed` の組み合わせである。
記録が無ければ交換ではなく破壊になる。
"""

from __future__ import annotations

from .db import Database

META_KEY = "embedding_identity"


class EmbeddingMismatch(RuntimeError):
    """魂に記録された埋め込み空間と、いま使おうとしているものが違う。"""

    def __init__(self, recorded: str, current: str, vectors: int) -> None:
        self.recorded = recorded
        self.current = current
        super().__init__(
            f"埋め込みモデルが変わっています。\n"
            f"  魂に記録されている: {recorded}\n"
            f"  いま使おうとしている: {current}\n"
            f"既存の {vectors} 件のベクトルは前のモデルで作られたもので、"
            f"別のモデルのベクトルと比べても意味がありません（想起が静かに壊れます）。\n\n"
            f"どちらかを選んでください:\n"
            f"  1. 記憶を新しいモデルで埋め直す:  nano reembed\n"
            f"  2. 元のモデル（{recorded}）に config.toml を戻す"
        )


def recorded(db: Database) -> str:
    row = db.one("SELECT value FROM meta WHERE key=?", (META_KEY,))
    return row["value"] if row else ""


def record(db: Database, identity: str) -> None:
    db.execute(
        "INSERT INTO meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (META_KEY, identity),
    )


def vector_count(db: Database) -> int:
    return db.scalar("SELECT COUNT(*) FROM note_vectors") or 0


def check(db: Database, identity: str) -> None:
    """起動時の照合。合わなければ止める。

    黙って続行しない。一生モノの記憶を静かに壊すより、
    起動を止めて人間に判断させるほうがよい。
    """
    known = recorded(db)
    if not known:
        # 初回、または同一性を記録する前に作られた魂
        record(db, identity)
        return
    if known == identity:
        return
    vectors = vector_count(db)
    if vectors == 0:
        # ベクトルがまだ無いなら、混ざりようがないので付け替えてよい
        record(db, identity)
        return
    raise EmbeddingMismatch(known, identity, vectors)
