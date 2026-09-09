"""無意識がやる各仕事のテスト。

とくに重要なのは curate の境界。
current_focus は勝手に変わってよいが、identity は人間の承認なしに1文字も変わってはいけない。
"""

from __future__ import annotations

import random

from nano.store import graph as graph_store
from nano.store import jobs as jobs_store
from nano.store import notes as notes_store
from nano.store import proposals as proposals_store
from nano.store import state as state_store
from nano.store.db import now as db_now
from nano.unconscious.jobs import associate, curate, ingest, reflect, remember

from conftest import DAY, converse

CONVERSATION = [
    "妹の名前はミオ。高校生で吹奏楽部にいる",
    "ミオはトランペットを吹いていて、来月コンクールがある",
    "猫のクロは12歳になった。最近あまり動かない",
    "好きな作家は伊坂幸太郎で、特にラッシュライフが好き",
]


def add_note(app, content, importance=0.5, kind=notes_store.KIND_FACT):
    note = notes_store.insert(app.db, content, importance=importance, kind=kind, half_life_days=30.0)
    vector = app.embedder.embed_documents([content])[0]
    notes_store.set_vector(app.db, note.id, vector)
    app.index.add(note.id, vector)
    return note


# --- write / decay ---
def test_write_job_turns_conversation_into_memory(app):
    converse(app, CONVERSATION)
    message = remember.run(app, None)
    assert "新しい記憶" in message
    assert app.db.scalar("SELECT COUNT(*) FROM notes") > 0


def test_decay_job_runs(app):
    assert "cold化" in remember.run_decay(app, None)


# --- associate ---
def test_associate_prefers_memories_that_are_not_yet_linked(app):
    seed = add_note(app, "妹の名前はミオ", importance=0.9)
    linked = add_note(app, "ミオはトランペットを吹く")
    unlinked = add_note(app, "紫陽花は梅雨に咲く")
    graph_store.add(app.db, seed.id, linked.id, "similar", 0.9, symmetric=True)

    picked = {note.id for note in associate.sample(app, count=2)}
    if seed.id in picked:
        assert linked.id not in picked, "既に繋がっている相手を引き合わせても意味がない"
        assert unlinked.id in picked


def test_associate_falls_back_when_everything_is_linked(app):
    """記憶が少なく全部が繋がっているうちも、諦めずに引き合わせること。"""
    first = add_note(app, "妹の名前はミオ")
    second = add_note(app, "ミオはトランペットを吹く")
    graph_store.add(app.db, first.id, second.id, "similar", 0.9, symmetric=True)
    assert len(associate.sample(app, count=2)) == 2


def test_associate_prefers_neglected_companions(app):
    """道連れは重要度で選ばない。長く思い出していない記憶ほど選ばれやすくすること。"""
    at = db_now()
    fresh_ids = [add_note(app, f"最近思い出した記憶{i}", importance=0.5).id for i in range(3)]
    stale_ids = [
        add_note(app, f"ずっと思い出していない記憶{i}", importance=0.5).id for i in range(3)
    ]
    # 実際に「久しく思い出していない」状態を last_accessed_at で作る。
    for note_id in stale_ids:
        app.db.execute(
            "UPDATE notes SET last_accessed_at=? WHERE id=?", (at - 200 * DAY, note_id)
        )
    # cold な記憶（高重要度）も混ぜて、絶対に選ばれないことを確かめる。
    cold_note = add_note(app, "もう思い出さない記憶", importance=0.9)
    app.db.execute(
        "UPDATE notes SET last_accessed_at=? WHERE id=?", (at - 400 * DAY, cold_note.id)
    )
    notes_store.set_state(app.db, cold_note.id, notes_store.STATE_COLD)

    random.seed(20260909)
    picks = {note_id: 0 for note_id in fresh_ids + stale_ids}
    trials = 300
    for _ in range(trials):
        drawn = associate.sample(app, count=3, at=at)
        for note in drawn:
            assert note.id != cold_note.id, "cold な記憶は絶対に道連れにしない"
            if note.id in picks:
                picks[note.id] += 1

    fresh_total = sum(picks[i] for i in fresh_ids)
    stale_total = sum(picks[i] for i in stale_ids)
    assert stale_total > fresh_total * 2, (
        f"長く思い出していない記憶が優先されていない: stale={stale_total} fresh={fresh_total}"
    )


def test_associate_creates_links_and_an_insight(app):
    add_note(app, "妹のミオは吹奏楽部でトランペットを吹いている")
    add_note(app, "ミオの吹奏楽部は来月コンクールに出る")
    add_note(app, "今日の昼は冷やし中華にした")

    before_links = app.db.scalar("SELECT COUNT(*) FROM links")
    before_notes = app.db.scalar("SELECT COUNT(*) FROM notes")
    for _ in range(8):  # 無作為に引くので何度か試す
        associate.run(app, None)
        if app.db.scalar("SELECT COUNT(*) FROM links") > before_links:
            break

    assert app.db.scalar("SELECT COUNT(*) FROM links") > before_links
    insights = app.db.query(
        "SELECT * FROM notes WHERE kind=? AND tags_json LIKE '%associate%'",
        (notes_store.KIND_REFLECTION,),
    )
    if insights:  # 気づきが出たなら、想起できる形になっていること
        assert app.db.scalar("SELECT COUNT(*) FROM notes") > before_notes
        assert notes_store.get_vector(app.db, insights[0]["id"]) is not None


def test_associate_needs_at_least_two_memories(app):
    add_note(app, "ひとつだけの記憶")
    assert "足りない" in associate.run(app, None)


# --- reflect ---
def test_reflect_waits_until_enough_has_happened(app):
    """何も起きていない日には何も考えない（Generative Agents の発火条件）。"""
    add_note(app, "些細なこと", importance=0.1)
    assert "まだ考えない" in reflect.run(app, None)
    assert app.db.scalar("SELECT COUNT(*) FROM notes WHERE kind='reflection'") == 0


def test_reflect_fires_once_importance_accumulates(app):
    for index in range(8):
        add_note(app, f"重要な出来事その{index}", importance=0.9)
    message = reflect.run(app, None)

    assert "気づき" in message
    assert app.db.scalar("SELECT COUNT(*) FROM notes WHERE kind='reflection'") > 0


def test_reflect_does_not_repeat_itself_immediately(app):
    for index in range(8):
        add_note(app, f"重要な出来事その{index}", importance=0.9)
    reflect.run(app, None)
    assert "まだ考えない" in reflect.run(app, None), "同じ記憶で何度も考え込まないこと"


# --- curate ---
def test_curate_updates_focus_automatically(app):
    add_note(app, "引っ越し先の内見に行く予定")
    curate.run(app, None)
    assert state_store.get(app.db, state_store.KEY_CURRENT_FOCUS)
    log = state_store.history(app.db, state_store.KEY_CURRENT_FOCUS)
    assert log[0]["updated_by"] == "unconscious"


def test_curate_never_writes_identity_directly(app):
    """人格の芯は、無意識が触れないこと。ここが M2 の一番重い約束。"""
    app.llm.handlers["curate_state"] = lambda messages: {
        "current_focus": "引っ越しのこと",
        "mood": "落ち着かない",
        "identity_proposal": "わたしは相手を急かさない方だ",
        "user_model_proposal": "この人は決める前に長く迷う",
        "rationale": "最近の会話から",
    }
    add_note(app, "引っ越し先を三つに絞った")
    curate.run(app, None)

    assert state_store.get(app.db, state_store.KEY_IDENTITY) == "", "identity が勝手に書き換わった"
    assert state_store.get(app.db, state_store.KEY_USER_MODEL) == ""
    assert state_store.get(app.db, state_store.KEY_CURRENT_FOCUS) == "引っ越しのこと"

    targets = {proposal.target for proposal in proposals_store.pending(app.db)}
    assert targets == {"identity", "user_model"}


def test_accepted_proposal_is_recorded_as_a_human_decision(app):
    proposal_id = proposals_store.propose(app.db, "identity", "わたしは黙って考える方だ")
    state_store.set_value(app.db, "identity", "わたしは黙って考える方だ", updated_by="human")
    proposals_store.decide(app.db, proposal_id, proposals_store.STATUS_ACCEPTED)

    assert state_store.history(app.db, "identity")[0]["updated_by"] == "human"
    assert proposals_store.count_pending(app.db) == 0


def test_curate_resolves_contradictions_when_it_can(app):
    old = add_note(app, "職場は代々木にある")
    new = add_note(app, "職場は新宿に移転した")
    graph_store.add(app.db, old.id, new.id, "contradicts", 0.9)

    app.llm.handlers["resolve_contradiction"] = lambda messages: {
        "verdict": "second",
        "reason": "移転したため",
    }
    curate.run(app, None)

    assert notes_store.get(app.db, old.id).state == notes_store.STATE_COLD
    assert notes_store.get(app.db, new.id).state == notes_store.STATE_ACTIVE


def test_curate_leaves_unclear_contradictions_alone(app):
    """判断がつかないなら消さない。誤って消すほうが害が大きい。"""
    first = add_note(app, "コーヒーは苦手")
    second = add_note(app, "今日はコーヒーを飲んだ")
    graph_store.add(app.db, first.id, second.id, "contradicts", 0.9)

    curate.run(app, None)  # オフラインスタブは常に unclear を返す
    assert notes_store.get(app.db, first.id).state == notes_store.STATE_ACTIVE
    assert notes_store.get(app.db, second.id).state == notes_store.STATE_ACTIVE


# --- ingest ---
def test_ingest_reads_the_inbox_into_memory(app):
    (app.config.inbox_dir / "memo.md").write_text("引っ越し先は中野が第一候補", encoding="utf-8")
    message = ingest.run(app, None)

    assert "取り込んだ" in message
    row = app.db.one("SELECT * FROM events WHERE role='world'")
    assert row is not None and "中野" in row["content"]
    assert not list(app.config.inbox_dir.glob("*.md")), "処理済みへ移動していない"
    assert list((app.config.inbox_dir / "processed").glob("*memo.md"))


def test_ingest_queues_the_write_job(app):
    (app.config.inbox_dir / "memo.txt").write_text("覚えておきたいこと", encoding="utf-8")
    ingest.run(app, None)
    assert "write" in jobs_store.summary(app.db)


def test_ingest_does_not_read_the_same_file_twice(app):
    text = "引っ越し先は中野が第一候補"
    (app.config.inbox_dir / "memo.md").write_text(text, encoding="utf-8")
    ingest.run(app, None)
    before = app.db.scalar("SELECT COUNT(*) FROM events WHERE role='world'")

    (app.config.inbox_dir / "memo.md").write_text(text, encoding="utf-8")  # 同じ内容を置き直す
    ingest.run(app, None)
    assert app.db.scalar("SELECT COUNT(*) FROM events WHERE role='world'") == before


def test_ingest_ignores_unknown_file_types(app):
    (app.config.inbox_dir / "photo.png").write_bytes(b"\x89PNG")
    assert "無かった" in ingest.run(app, None)
    assert (app.config.inbox_dir / "photo.png").exists()
