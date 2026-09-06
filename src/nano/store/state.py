"""working_state — 常にプロンプトへ載る作業状態。

無意識デーモンが人格の周辺（current_focus / mood / user_model）を書き換える
唯一の窓口。書き換えは必ず監査ログに残す。「気づかないうちに別人になっていた」
を防ぐための仕掛けであり、人格の連続性を守る実装上の要。
"""

from __future__ import annotations

from typing import Iterable

from .db import Database, now

KEY_IDENTITY = "identity"        # 自己像（無意識が更新、変更は遅い）
KEY_USER_MODEL = "user_model"    # ユーザー像
KEY_CURRENT_FOCUS = "current_focus"  # いま気にしていること
KEY_MOOD = "mood"
KEY_THREAD = "thread"            # 直近の話の流れ

DEFAULT_KEYS = (KEY_IDENTITY, KEY_USER_MODEL, KEY_CURRENT_FOCUS, KEY_MOOD, KEY_THREAD)


def get(db: Database, key: str, default: str = "") -> str:
    row = db.one("SELECT value FROM working_state WHERE key=?", (key,))
    return default if row is None else row["value"]


def all_state(db: Database, keys: Iterable[str] = DEFAULT_KEYS) -> dict[str, str]:
    return {key: get(db, key) for key in keys}


def set_value(db: Database, key: str, value: str, updated_by: str = "system") -> None:
    old = get(db, key)
    if old == value:
        return
    timestamp = now()
    db.execute(
        "INSERT INTO working_state(key, value, updated_at, updated_by) VALUES(?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, "
        "updated_by=excluded.updated_by",
        (key, value, timestamp, updated_by),
    )
    db.execute(
        "INSERT INTO working_state_log(ts, key, old_value, new_value, updated_by) VALUES(?,?,?,?,?)",
        (timestamp, key, old, value, updated_by),
    )


def history(db: Database, key: str | None = None, limit: int = 50) -> list[dict]:
    if key:
        rows = db.query(
            "SELECT * FROM working_state_log WHERE key=? ORDER BY id DESC LIMIT ?", (key, limit)
        )
    else:
        rows = db.query("SELECT * FROM working_state_log ORDER BY id DESC LIMIT ?", (limit,))
    return [dict(row) for row in rows]
