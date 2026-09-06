"""気づき — 記憶から一段高い推論を作る。

発火条件は Generative Agents 方式。定期実行ではなく、
**前回以降に積み上がった重要度がしきい値を超えたとき**に動く。
何も起きていない日には何も考えない。
"""

from __future__ import annotations

from ...memory import prompts
from ...memory.decay import initial_half_life
from ...store import graph as graph_store
from ...store import notes as notes_store
from ...store.db import Database, now

META_KEY = "last_reflect_at"


def last_reflect_at(db: Database) -> float:
    row = db.one("SELECT value FROM meta WHERE key=?", (META_KEY,))
    return float(row["value"]) if row else 0.0


def mark_reflected(db: Database, at: float) -> None:
    db.execute(
        "INSERT INTO meta(key, value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (META_KEY, str(at)),
    )


def accumulated_importance(db: Database, since: float) -> float:
    return (
        db.scalar(
            "SELECT COALESCE(SUM(importance), 0) FROM notes WHERE created_at > ? AND state='active'",
            (since,),
        )
        or 0.0
    )


def run(app, job) -> str:
    config = app.config.unconscious
    since = last_reflect_at(app.db)
    accumulated = accumulated_importance(app.db, since)
    if accumulated < config.reflect_importance_threshold:
        return f"重要度の蓄積 {accumulated:.2f} < 閾値 {config.reflect_importance_threshold}。まだ考えない"

    rows = app.db.query(
        """SELECT * FROM notes WHERE created_at > ? AND state='active'
           ORDER BY importance DESC, created_at DESC LIMIT 20""",
        (since,),
    )
    recent = [notes_store.Note.from_row(row) for row in rows]
    if not recent:
        return "対象の記憶が無い"

    payload = app.llm.chat_json(prompts.reflect(recent, app.config.persona.name), task="reflect")
    known = {note.id for note in recent}
    created: list[int] = []

    for insight in payload.get("insights", []) or []:
        content = str(insight.get("content", "")).strip()
        if not content:
            continue
        importance = _clamp(insight.get("importance", 0.5))
        note = notes_store.insert(
            app.db,
            content,
            kind=notes_store.KIND_REFLECTION,
            context="最近の記憶から言えること",
            tags=["reflection"],
            importance=importance,
            half_life_days=initial_half_life(importance, app.config.decay),
        )
        vector = app.embedder.embed_documents([content])[0]
        notes_store.set_vector(app.db, note.id, vector)
        app.index.add(note.id, vector, notes_store.STATE_ACTIVE)
        for evidence in insight.get("evidence", []) or []:
            try:
                target = int(evidence)
            except (TypeError, ValueError):
                continue
            if target in known:
                graph_store.add(app.db, note.id, target, "elaborates", 0.7, created_by="reflect")
        created.append(note.id)

    mark_reflected(app.db, now())
    if not created:
        return f"重要度 {accumulated:.2f} を検討したが、言えることは無かった"
    return f"気づき {len(created)} 件: " + " / ".join(
        f"#{note_id}" for note_id in created
    )


def _clamp(value, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return 0.5
