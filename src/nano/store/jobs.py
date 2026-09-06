"""無意識のジョブキュー。

デーモンはこのキューを消化するだけの存在で、状態は全て soul.db にある。
だからデーモンはいつ落ちてもいいし、落ちた続きから再開できる。
「考えかけたことは、あとで考え直される」を保証しているのがここ。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .db import Database, now

STATUS_PENDING = "pending"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_FAILED = "failed"


@dataclass
class Job:
    id: int
    kind: str
    payload: dict[str, Any]
    priority: int
    attempts: int

    @classmethod
    def from_row(cls, row) -> "Job":
        return cls(
            id=row["id"],
            kind=row["kind"],
            payload=json.loads(row["payload_json"]),
            priority=row["priority"],
            attempts=row["attempts"],
        )


def enqueue(
    db: Database,
    kind: str,
    payload: dict[str, Any] | None = None,
    priority: int = 10,
    run_after: float | None = None,
    dedupe: bool = True,
) -> int | None:
    """ジョブを積む。dedupe なら同じ種類の待ちジョブが既にあるとき積まない。

    定期ジョブは何度でも積まれうるので、既定で重複を排除する。
    デーモンが数日止まっていた後に decay が100件溜まっている、を防ぐ。
    """
    timestamp = now()
    if dedupe and db.scalar(
        "SELECT COUNT(*) FROM jobs WHERE kind=? AND status IN (?,?)",
        (kind, STATUS_PENDING, STATUS_RUNNING),
    ):
        return None
    cursor = db.execute(
        """INSERT INTO jobs(kind, payload_json, priority, run_after, status, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?)""",
        (
            kind,
            json.dumps(payload or {}, ensure_ascii=False),
            priority,
            timestamp if run_after is None else run_after,
            STATUS_PENDING,
            timestamp,
            timestamp,
        ),
    )
    return cursor.lastrowid


def claim(db: Database, at: float | None = None) -> Job | None:
    """実行するジョブを1件取る。

    BEGIN IMMEDIATE の中で選択と状態変更を済ませるので、
    デーモンを二重起動しても同じジョブが二度実行されることはない。
    """
    at = now() if at is None else at
    with db.transaction(immediate=True):
        row = db.one(
            """SELECT * FROM jobs WHERE status=? AND run_after<=?
               ORDER BY priority, run_after, id LIMIT 1""",
            (STATUS_PENDING, at),
        )
        if row is None:
            return None
        db.execute(
            "UPDATE jobs SET status=?, attempts=attempts+1, updated_at=? WHERE id=?",
            (STATUS_RUNNING, at, row["id"]),
        )
        job = Job.from_row(row)
    job.attempts += 1
    return job


def complete(db: Database, job_id: int) -> None:
    db.execute(
        "UPDATE jobs SET status=?, last_error='', updated_at=? WHERE id=?",
        (STATUS_DONE, now(), job_id),
    )


def release(db: Database, job_id: int, run_after: float | None = None) -> None:
    """中断されたジョブを待ち行列へ戻す。attempts は増やしたままにしない。

    対話に割り込まれたのはジョブの失敗ではないので、リトライ回数を消費させない。
    """
    timestamp = now()
    db.execute(
        """UPDATE jobs SET status=?, attempts=max(attempts-1, 0), run_after=?, updated_at=?
           WHERE id=?""",
        (STATUS_PENDING, timestamp if run_after is None else run_after, timestamp, job_id),
    )


def fail(db: Database, job_id: int, error: str, retry_in: float = 300.0, max_attempts: int = 3) -> None:
    timestamp = now()
    row = db.one("SELECT attempts FROM jobs WHERE id=?", (job_id,))
    attempts = row["attempts"] if row else max_attempts
    if attempts >= max_attempts:
        db.execute(
            "UPDATE jobs SET status=?, last_error=?, updated_at=? WHERE id=?",
            (STATUS_FAILED, error[:500], timestamp, job_id),
        )
        return
    db.execute(
        "UPDATE jobs SET status=?, last_error=?, run_after=?, updated_at=? WHERE id=?",
        (STATUS_PENDING, error[:500], timestamp + retry_in, timestamp, job_id),
    )


def reap_stale(db: Database, timeout_s: float = 600.0, at: float | None = None) -> int:
    """running のまま取り残されたジョブを回収する。

    デーモンが強制終了された（電源断・タスク終了）ときの復帰経路。
    これが無いと、一度落ちたジョブ種は二度と動かなくなる。
    """
    at = now() if at is None else at
    cursor = db.execute(
        "UPDATE jobs SET status=?, updated_at=? WHERE status=? AND updated_at < ?",
        (STATUS_PENDING, at, STATUS_RUNNING, at - timeout_s),
    )
    return cursor.rowcount


def summary(db: Database) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for row in db.query("SELECT kind, status, COUNT(*) AS n FROM jobs GROUP BY kind, status"):
        result.setdefault(row["kind"], {})[row["status"]] = row["n"]
    return result


def recent_failures(db: Database, limit: int = 5) -> list[dict]:
    rows = db.query(
        "SELECT kind, last_error, updated_at FROM jobs WHERE status=? ORDER BY updated_at DESC LIMIT ?",
        (STATUS_FAILED, limit),
    )
    return [dict(row) for row in rows]


# --- 定期ジョブの最終実行時刻。既存の meta テーブルを使い、新しい表を増やさない ---
def last_run(db: Database, kind: str) -> float:
    row = db.one("SELECT value FROM meta WHERE key=?", (f"last_run:{kind}",))
    return float(row["value"]) if row else 0.0


def mark_run(db: Database, kind: str, at: float | None = None) -> None:
    db.execute(
        "INSERT INTO meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (f"last_run:{kind}", str(now() if at is None else at)),
    )
