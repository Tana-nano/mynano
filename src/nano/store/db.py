"""SQLite 接続とマイグレーション。

サーバー常駐のDBを使わないのは、魂が1ファイルで持ち運べることが
このプロジェクトで最も価値のある性質だから。
"""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Sequence

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
SCHEMA_VERSION = "3"


def now() -> float:
    """全時刻は UTC の Unix 秒。タイムゾーンで記憶が壊れないように。"""
    return time.time()


def to_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        # 対話とデーモンの2プロセスが同じ soul.db を触る。書き込みの衝突は待って解決する。
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.migrate()

    # あとから足した列。`CREATE TABLE IF NOT EXISTS` は既存のテーブルには効かないので、
    # 既に魂を持っている人の soul.db にはここを通して足す。
    # 消す/型を変える方向のマイグレーションは書かない（禁則1と同じ理由で、
    # 一生モノの DB に対して不可逆な操作を自動で走らせない）。
    ADDED_COLUMNS: tuple[tuple[str, str, str], ...] = (
        # ⭐ を出したのがどのモデル／アダプタか。M4 で世代をまたいで ⭐ が貯まるため。
        ("stars", "model", "TEXT NOT NULL DEFAULT ''"),
        ("stars", "adapter", "TEXT NOT NULL DEFAULT ''"),
    )

    def migrate(self) -> None:
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        for table, column, ddl in self.ADDED_COLUMNS:
            self._add_column(table, column, ddl)
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (SCHEMA_VERSION,),
        )

    def _add_column(self, table: str, column: str, ddl: str) -> None:
        existing = {row["name"] for row in self.conn.execute(f"PRAGMA table_info({table})")}
        if not existing or column in existing:
            return
        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    # --- 薄いヘルパー。ORM は入れない（寿命の問題） ---
    def execute(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        return self.conn.execute(sql, params)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        return self.conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = self.one(sql, params)
        return None if row is None else row[0]

    @contextmanager
    def transaction(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        """immediate=True は最初から書き込みロックを取る。

        ジョブの取り合いやリースの奪取など、read-modify-write を
        別プロセスと競う場面では必ず immediate を使うこと。
        遅延ロックだと両者が読んでから両者が書こうとして片方が失敗する。
        """
        self.conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        try:
            yield self.conn
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        else:
            self.conn.execute("COMMIT")

    def backup(self, directory: str | Path) -> Path:
        """VACUUM INTO による一貫性のあるスナップショット。稼働中でも安全。"""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        target = directory / f"soul-{stamp}.db"
        self.conn.execute("VACUUM INTO ?", (str(target),))
        return target

    def close(self) -> None:
        self.conn.close()
