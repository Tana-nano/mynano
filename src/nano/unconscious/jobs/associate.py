"""連想 — 無意識にしかできない仕事。

想起は「いま話していること」に引きずられる。だから、誰も探しにいかない
組み合わせの記憶は永遠に出会わない。それを無作為に引き合わせるのがここ。

「寝ている間に何か考えていた」の実体はこのジョブである。
"""

from __future__ import annotations

import random

from ...memory import prompts
from ...memory.decay import SECONDS_PER_DAY, initial_half_life, retrievability
from ...store import graph as graph_store
from ...store import notes as notes_store
from ...store.db import now

RELATIONS = {"similar", "elaborates", "causes", "contradicts"}


def _neglect_weight(note: notes_store.Note, at: float) -> float:
    """しばらく思い出していない記憶ほど、道連れに選ばれやすくする。

    重要度は一切見ない。ここで重要度をかけると、いつも同じ重要な記憶ばかりが
    連想の相手に選ばれるようになる。それは §6 の罠（連想強化を一律にかけて
    どうでもいい記憶が生き延びた）の裏返しで、今度は「重要でない記憶は
    いつまで経っても誰とも引き合わされない」という別の偏りになる。
    連想の相手を選ぶ基準は「最近思い出したか」だけにする。
    """
    days_since = max(0.0, (at - note.last_accessed_at) / SECONDS_PER_DAY)
    return days_since + 1.0


def _weighted_sample_without_replacement(
    pool: list[notes_store.Note], weights: list[float], k: int
) -> list[notes_store.Note]:
    """重み付きで、かつ重複無しに k 件引く。

    `random.choices` は重複ありにしか使えないので、選んでは除く、を繰り返す。
    候補は多くても数千件規模なので、この素朴さで困らない。
    """
    remaining_notes = list(pool)
    remaining_weights = list(weights)
    chosen: list[notes_store.Note] = []
    for _ in range(min(k, len(remaining_notes))):
        index = random.choices(range(len(remaining_notes)), weights=remaining_weights, k=1)[0]
        chosen.append(remaining_notes.pop(index))
        remaining_weights.pop(index)
    return chosen


def sample(app, count: int, at: float | None = None) -> list[notes_store.Note]:
    """1件は「思い出しやすい記憶」から、残りは「しばらく思い出していない記憶」を優先して引く。

    全部を重要度で引くと、いつも同じ顔ぶれが並んで新しい繋がりが生まれない。
    かといって道連れまで重要度で選ぶと、逆に地味な記憶がいつまでも
    誰とも引き合わされなくなる。だから道連れは `last_accessed_at` の古さだけで
    重み付けし、無作為に（重複無しで）引く。
    既にリンクがある相手は候補から外す。既知の関係を再発見しても意味がないので。
    """
    at = now() if at is None else at
    active = notes_store.iter_notes(app.db, states=(notes_store.STATE_ACTIVE,))
    if len(active) < 2:
        return []

    weights = [
        max(1e-6, note.importance * (0.3 + retrievability(note, at, app.config.decay)))
        for note in active
    ]
    seed = random.choices(active, weights=weights, k=1)[0]

    linked = {
        row["dst_id"]
        for row in app.db.query("SELECT dst_id FROM links WHERE src_id=?", (seed.id,))
    }
    linked.add(seed.id)

    # まだ繋がっていない記憶を優先する。既知の関係を再発見しても意味がないので。
    pool = [note for note in active if note.id not in linked]
    if not pool:
        # 記憶が少ないうちは全部が繋がっていることもある。そのときは諦めずに、
        # 既に繋がっている相手から引く（別の関係や、並べて初めて言えることが残っている）。
        pool = [note for note in active if note.id != seed.id]
    if not pool:
        return []
    companion_weights = [_neglect_weight(note, at) for note in pool]
    others = _weighted_sample_without_replacement(pool, companion_weights, count - 1)
    return [seed, *others]


def run(app, job) -> str:
    config = app.config.unconscious
    notes = sample(app, config.associate_sample)
    if len(notes) < 2:
        return "引き合わせる記憶が足りない"

    by_id = {note.id: note for note in notes}
    payload = app.llm.chat_json(prompts.associate(notes, app.config.persona.name), task="associate")
    if not payload.get("related"):
        return f"#{'/#'.join(str(n.id) for n in notes)} に繋がりは無かった"

    added = 0
    for pair in payload.get("pairs", []) or []:
        try:
            left, right = int(pair["a"]), int(pair["b"])
        except (KeyError, TypeError, ValueError):
            continue
        if left not in by_id or right not in by_id or left == right:
            continue
        relation = str(pair.get("relation", "similar"))
        if relation not in RELATIONS:
            relation = "similar"
        weight = _clamp(pair.get("weight", 0.5))
        graph_store.add(app.db, left, right, relation, weight, created_by="associate", symmetric=True)
        added += 1

    insight = str(payload.get("insight") or "").strip()
    if not insight:
        return f"リンク {added} 本（気づきは無し）"

    importance = _clamp(payload.get("importance", 0.4))
    note = notes_store.insert(
        app.db,
        insight,
        kind=notes_store.KIND_REFLECTION,
        context="無作為に並べた記憶から浮かんだこと",
        tags=["associate"],
        importance=importance,
        half_life_days=initial_half_life(importance, app.config.decay),
    )
    vector = app.embedder.embed_documents([insight])[0]
    notes_store.set_vector(app.db, note.id, vector)
    app.index.add(note.id, vector, notes_store.STATE_ACTIVE)
    for source in notes:
        graph_store.add(app.db, note.id, source.id, "elaborates", 0.6, created_by="associate")
    return f"リンク {added} 本 / 気づき #{note.id}: {insight}"


def _clamp(value, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return 0.5
