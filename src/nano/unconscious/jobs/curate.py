"""整理 — 矛盾の解決と、いまの状態の更新。

ここが人格に最も近づく仕事なので、境界を明確にしてある。

  自動で書き換える : current_focus / mood        （関心と気分は勝手に動いてよい）
  提案に留める     : identity / user_model        （人格の芯は人間が承認する）

`nano review` で承認されるまで、identity は 1 文字も変わらない。
"""

from __future__ import annotations

from ...memory import prompts
from ...store import notes as notes_store
from ...store import proposals as proposals_store
from ...store import state as state_store

MAX_CONTRADICTIONS = 3


def _resolve_contradictions(app) -> list[str]:
    """食い違う記憶を突き合わせ、古い方を cold にする。

    判断がつかないときは何もしない。誤って消すほうが、残しておくより害が大きい。
    """
    rows = app.db.query(
        """SELECT l.src_id, l.dst_id FROM links l
           JOIN notes a ON a.id = l.src_id AND a.state='active'
           JOIN notes b ON b.id = l.dst_id AND b.state='active'
           WHERE l.relation='contradicts' AND l.src_id < l.dst_id
           LIMIT ?""",
        (MAX_CONTRADICTIONS,),
    )
    log: list[str] = []
    for row in rows:
        first = notes_store.get(app.db, row["src_id"])
        second = notes_store.get(app.db, row["dst_id"])
        if first is None or second is None:
            continue
        payload = app.llm.chat_json(
            prompts.resolve_contradiction(first, second, app.config.persona.name),
            task="resolve_contradiction",
        )
        verdict = str(payload.get("verdict", "unclear"))
        loser = {"first": second, "second": first}.get(verdict)
        if loser is None:
            log.append(f"#{first.id}⇄#{second.id} は判断保留")
            continue
        notes_store.set_state(app.db, loser.id, notes_store.STATE_COLD)
        app.index.set_state(loser.id, notes_store.STATE_COLD)
        log.append(f"#{first.id}⇄#{second.id} → #{loser.id} を cold 化")
    return log


def _update_state(app) -> list[str]:
    rows = app.db.query(
        "SELECT * FROM notes WHERE state='active' ORDER BY created_at DESC LIMIT 20"
    )
    recent = [notes_store.Note.from_row(row) for row in rows]
    if not recent:
        return []

    current = state_store.all_state(app.db)
    payload = app.llm.chat_json(
        prompts.curate_state(recent, current, app.config.persona.name), task="curate_state"
    )
    log: list[str] = []

    for key in (state_store.KEY_CURRENT_FOCUS, state_store.KEY_MOOD):
        value = str(payload.get(key, "") or "").strip()
        if value and value != current.get(key):
            state_store.set_value(app.db, key, value, updated_by="unconscious")
            log.append(f"{key} → {value}")

    rationale = str(payload.get("rationale", "") or "")
    for key, field in (
        (state_store.KEY_IDENTITY, "identity_proposal"),
        (state_store.KEY_USER_MODEL, "user_model_proposal"),
    ):
        value = str(payload.get(field, "") or "").strip()
        if not value:
            continue
        # 書き換えない。提案するだけ。反映は人間が nano review で決める。
        proposal_id = proposals_store.propose(
            app.db, key, value, current_value=current.get(key, ""), rationale=rationale
        )
        if proposal_id is not None:
            log.append(f"{key} の変更を提案 (#{proposal_id}) — 承認待ち")
    return log


def run(app, job) -> str:
    log = _resolve_contradictions(app) + _update_state(app)
    return " / ".join(log) if log else "整えるものは無かった"
