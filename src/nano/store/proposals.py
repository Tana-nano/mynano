"""人格に触れる変更の提案。

無意識は identity（自己像）と user_model（あなた像）を**書き換えない**。提案するだけ。
反映されるのは人間が `nano review` で承認したときだけで、その記録は
`working_state_log` に updated_by='human' として残る。

記憶や関心が勝手に育つのは構わない。だが人格の芯が、気づかないうちに
別のものにすり替わっているのは困る。その歯止めがこのテーブル。
"""

from __future__ import annotations

from dataclasses import dataclass

from .db import Database, now

STATUS_PENDING = "pending"
STATUS_ACCEPTED = "accepted"
STATUS_REJECTED = "rejected"

# 提案の対象にできるもの。ここに無いキーは無意識が直接書き換えてよい（current_focus など）。
GUARDED_KEYS = ("identity", "user_model")


@dataclass
class Proposal:
    id: int
    created_at: float
    target: str
    current_value: str
    proposed_value: str
    rationale: str
    status: str

    @classmethod
    def from_row(cls, row) -> "Proposal":
        return cls(
            id=row["id"],
            created_at=row["created_at"],
            target=row["target"],
            current_value=row["current_value"],
            proposed_value=row["proposed_value"],
            rationale=row["rationale"],
            status=row["status"],
        )


def propose(
    db: Database,
    target: str,
    proposed_value: str,
    current_value: str = "",
    rationale: str = "",
) -> int | None:
    """提案を積む。同じ内容が既に待っているなら積まない。"""
    proposed_value = proposed_value.strip()
    if not proposed_value or proposed_value == current_value.strip():
        return None
    duplicate = db.scalar(
        "SELECT COUNT(*) FROM proposals WHERE target=? AND proposed_value=? AND status=?",
        (target, proposed_value, STATUS_PENDING),
    )
    if duplicate:
        return None
    cursor = db.execute(
        """INSERT INTO proposals(created_at, target, current_value, proposed_value, rationale, status)
           VALUES(?,?,?,?,?,?)""",
        (now(), target, current_value, proposed_value, rationale, STATUS_PENDING),
    )
    return cursor.lastrowid


def pending(db: Database, limit: int = 20) -> list[Proposal]:
    rows = db.query(
        "SELECT * FROM proposals WHERE status=? ORDER BY created_at LIMIT ?",
        (STATUS_PENDING, limit),
    )
    return [Proposal.from_row(row) for row in rows]


def get(db: Database, proposal_id: int) -> Proposal | None:
    row = db.one("SELECT * FROM proposals WHERE id=?", (proposal_id,))
    return None if row is None else Proposal.from_row(row)


def decide(db: Database, proposal_id: int, status: str, decided_by: str = "human") -> None:
    db.execute(
        "UPDATE proposals SET status=?, decided_at=?, decided_by=? WHERE id=?",
        (status, now(), decided_by, proposal_id),
    )


def count_pending(db: Database) -> int:
    return db.scalar("SELECT COUNT(*) FROM proposals WHERE status=?", (STATUS_PENDING,)) or 0
