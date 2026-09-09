"""⭐ と教師データのテスト。

ここで守りたい性質は「人格の材料が、人間の手だけで、正確な対で集まること」。
つまり:
  - ⭐ が付くのは人間が押したときだけ
  - 保存されるのは応答だけでなく「そのとき渡したプロンプト」
  - 生ログには何が起きても触らない（禁則1）
  - コードが消えても平文から組み直せる（禁則2）
"""

from __future__ import annotations

import json

import pytest

from conftest import write_baseline

from nano.persona import dataset as dataset_module
from nano.store import events as events_store
from nano.store import stars as stars_store


def test_star_keeps_the_prompt_that_actually_produced_the_answer(app):
    """⭐ は応答とプロンプトの対で残る。あとから組み直さない。"""
    app.say("妹の名前はミオ", "s1")
    exchange = app.star(reason="言い方がちょうどよかった")

    star = stars_store.get(app.db, exchange.companion_event_id)
    assert star is not None
    assert star.rating == stars_store.RATING_KEEP
    assert star.reason == "言い方がちょうどよかった"
    # 実際に渡した messages がそのまま入っていること
    assert star.prompt == exchange.messages
    assert star.prompt[0]["role"] == "system"
    assert star.prompt[-1] == {"role": "user", "content": "妹の名前はミオ"}


def test_star_survives_memory_moving_on(app):
    """あとで記憶が増えても、⭐ の中のプロンプトは当時のまま。

    ここが崩れると「モデルが見ていない材料から答えを出す」訓練になる。
    """
    app.say("紫陽花が好き", "s1")
    exchange = app.star()
    snapshot = json.dumps(stars_store.get(app.db, exchange.companion_event_id).prompt)

    app.ingest()  # 記憶が増える
    app.say("今日は雨だった", "s1")

    assert json.dumps(stars_store.get(app.db, exchange.companion_event_id).prompt) == snapshot


def test_star_targets_the_nth_previous_answer(app):
    app.say("ひとつめ", "s1")
    app.say("ふたつめ", "s1")
    app.say("みっつめ", "s1")

    exchange = app.star(back=3)
    assert exchange.user_text == "ひとつめ"


def test_cannot_star_outside_this_conversation(app):
    """過去ログを遡って ⭐ は付けられない（プロンプトが復元できないため）。"""
    with pytest.raises(IndexError):
        app.star()

    app.say("いま話したこと", "s1")
    with pytest.raises(IndexError):
        app.star(back=2)


def test_avoid_and_unstar(app):
    app.say("これは違う", "s1")
    exchange = app.star(rating=stars_store.RATING_AVOID, reason="説明くさい")
    assert stars_store.get(app.db, exchange.companion_event_id).rating == -1
    assert stars_store.counts(app.db) == {"keep": 0, "avoid": 1}

    assert app.unstar() is not None
    assert stars_store.get(app.db, exchange.companion_event_id) is None
    assert app.unstar() is None  # 二度目は何も起きない


def test_restarring_replaces_the_mark(app):
    app.say("やっぱり良い", "s1")
    app.star(rating=stars_store.RATING_AVOID)
    app.star(rating=stars_store.RATING_KEEP, reason="考え直した")

    counts = stars_store.counts(app.db)
    assert counts == {"keep": 1, "avoid": 0}
    assert stars_store.recent(app.db)[0].star.reason == "考え直した"


def test_unstar_never_touches_the_raw_log(app):
    """禁則1: 印を外しても生ログは1行も減らない。"""
    app.say("消えては困る", "s1")
    before = app.db.scalar("SELECT COUNT(*) FROM events")
    app.star()
    app.unstar()
    assert app.db.scalar("SELECT COUNT(*) FROM events") == before


def test_star_is_mirrored_in_plain_text(app):
    """禁則2: DB が消えても、平文だけで教師データを組み直せること。"""
    app.say("平文にも残って", "s1")
    app.star(reason="ここが好き")
    app.unstar()

    lines = (app.config.archive_dir / "stars.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # 付けた行と外した行。上書きせず積む
    starred = json.loads(lines[0])
    assert starred["action"] == "star"
    assert starred["reason"] == "ここが好き"
    assert starred["user"] == "平文にも残って"
    assert starred["prompt"][0]["role"] == "system"
    assert json.loads(lines[1])["action"] == "unstar"


def test_dataset_contains_only_starred_turns(app):
    app.say("採用される", "s1")
    app.star(reason="よい")
    app.say("採用されない", "s1")
    app.say("避けたい", "s1")
    app.star(rating=stars_store.RATING_AVOID)

    built = dataset_module.build(app.db)
    assert len(built.keep) == 1
    assert len(built.avoid) == 1
    sample = built.keep[0]
    assert sample.messages[-1]["role"] == "assistant"
    assert sample.messages[-2] == {"role": "user", "content": "採用される"}
    assert sample.reason == "よい"


def test_export_requires_a_persona_baseline(app):
    """計測が先、学習が後。基準が無いまま教師データを出させない。"""
    app.say("何か", "s1")
    app.star()

    with pytest.raises(dataset_module.BaselineMissing):
        dataset_module.export(app.config, app.db, embedding_identity=app.embedder.identity)

    write_baseline(app.config, app.embedder.identity)
    target, built = dataset_module.export(app.config, app.db, embedding_identity=app.embedder.identity)

    assert len(built.keep) == 1
    written = (target / "sft.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(written) == 1
    record = json.loads(written[0])
    assert record["messages"][-1]["role"] == "assistant"
    manifest = json.loads((target / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"]["sft"] == 1
    assert manifest["baseline"] is True
    # 魂ディレクトリの外には出さない
    assert target.is_relative_to(app.config.soul_dir)


def test_export_can_be_forced_without_a_baseline(app):
    app.say("急ぎ", "s1")
    app.star()
    target, built = dataset_module.export(app.config, app.db, force=True)
    assert len(built.keep) == 1
    assert (target / "sft.jsonl").exists()


def test_stats_counts_the_fuel_for_m4(app):
    app.say("ひとつ", "s1")
    app.star()
    stats = app.stats()
    assert stats["starred"] == 1
    assert stats["avoided"] == 0


# --- /again と ORPO の対 -------------------------------------------------


@pytest.fixture
def varying_replies(app):
    """出し直すたびに違う応答を返すスタブ。

    OfflineLLM は決定的なので、素のままだと /again が一字一句同じ答えを返す。
    それは対にならない（下の test_identical_answers_do_not_pair で担保している）ので、
    ペアリングを試すテストではここで揺らす。
    """
    counter = {"n": 0}

    def reply(messages):
        counter["n"] += 1
        return f"応答その{counter['n']}"

    app.llm.handlers["reply"] = reply
    return app


def test_again_reuses_the_exact_same_prompt(app):
    """出し直しは前回と同じ messages で行う。ここが対の根拠になる。"""
    app.say("何か言って", "s1")
    first = app.exchanges[-1]
    second = app.again()

    assert second.messages == first.messages
    assert second.user_text == first.user_text
    assert second.companion_event_id != first.companion_event_id


def test_again_marks_the_previous_answer_as_avoid(app):
    app.say("何か言って", "s1")
    first = app.exchanges[-1]
    app.again()

    star = stars_store.get(app.db, first.companion_event_id)
    assert star is not None
    assert star.rating == stars_store.RATING_AVOID
    assert star.reason == "出し直しを求められた"


def test_again_does_not_overwrite_a_star(app):
    """⭐ を付けたうえで別案を見たいだけ、ということがある。"""
    app.say("何か言って", "s1")
    first = app.exchanges[-1]
    app.star(reason="これは好き")
    app.again()

    assert stars_store.get(app.db, first.companion_event_id).rating == stars_store.RATING_KEEP


def test_again_builds_an_orpo_pair(varying_replies):
    app = varying_replies
    app.say("何か言って", "s1")
    rejected = app.exchanges[-1]
    app.again()
    app.star(reason="こっちのほうがいい")

    built = dataset_module.build(app.db)
    assert len(built.pairs) == 1
    pair = built.pairs[0]
    assert pair.prompt == rejected.messages       # 末尾の assistant を含まない
    assert pair.chosen == app.exchanges[-1].answer
    assert pair.rejected == rejected.answer


def test_pairs_need_an_identical_prompt(app):
    """別々の発話に付いた ⭐ と ✗ は対にしない（比べているのが応答の差ではなくなる）。"""
    app.say("ひとつめ", "s1")
    app.star()
    app.say("ふたつめ", "s1")
    app.star(rating=stars_store.RATING_AVOID)

    built = dataset_module.build(app.db)
    assert len(built.keep) == 1
    assert len(built.avoid) == 1
    assert built.pairs == []


def test_superseded_answer_never_becomes_a_memory(app):
    """出し直された応答は記憶にしない。ただし生ログからは消えない（禁則1）。"""
    app.say("最初の言い方は違った", "s1")
    superseded = app.exchanges[-1]
    app.again()

    events_before = app.db.scalar("SELECT COUNT(*) FROM events")
    app.ingest()

    # 生ログは1行も減らない
    assert app.db.scalar("SELECT COUNT(*) FROM events") == events_before
    # 未処理のまま取り残されてもいない（毎tick蒸し返されると無意識が止まらなくなる）
    assert app.db.scalar(
        "SELECT episode_id FROM events WHERE id=?", (superseded.companion_event_id,)
    ) is not None
    # 撤回した言葉が記憶になっていない
    notes = [row["content"] for row in app.db.query("SELECT content FROM notes")]
    assert all(superseded.answer not in content for content in notes)


def test_identical_answers_do_not_pair(app):
    """温度0で出し直すと一字一句同じ答えが返る。それを対にしても学習にならない。"""
    app.say("同じ答えが返る", "s1")
    app.again()
    app.star()

    built = dataset_module.build(app.db)
    assert len(built.keep) == 1 and len(built.avoid) == 1
    assert built.pairs == []


def test_orpo_pairs_are_exported(varying_replies):
    import json as _json

    app = varying_replies
    app.say("出し直してみる", "s1")
    app.again()
    app.star()
    write_baseline(app.config, app.embedder.identity)

    target, built = dataset_module.export(app.config, app.db, embedding_identity=app.embedder.identity)
    lines = (target / "orpo.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = _json.loads(lines[0])
    assert set(record) == {"prompt", "chosen", "rejected", "meta"}
    assert record["chosen"] != record["rejected"]
    assert record["prompt"][-1]["role"] == "user"


# --- 世代（どのモデルが出した応答への ⭐ か） --------------------------------
#
# LoRA を当てたあとも ⭐ は貯まり続ける。当てる前の ⭐ と混ぜて次の学習に使うと、
# 前回焼いた訛りを自分自身から学び直すことになる。分けられるように出どころを刻む。


def test_a_star_records_which_model_answered(app):
    app.say("何か", "s1")
    app.star()

    star = stars_store.get(app.db, app.exchanges[-1].companion_event_id)
    assert star is not None
    assert star.model == "offline-stub"
    assert star.adapter == ""


def test_the_adapter_is_recorded_when_one_is_loaded(app):
    app.config.llm.adapter = "nano-v1"
    app.say("当てたあとの会話", "s1")
    app.star()

    star = stars_store.get(app.db, app.exchanges[-1].companion_event_id)
    assert star.adapter == "nano-v1"

    built = dataset_module.build(app.db)
    assert built.keep[0].generation == "offline-stub+nano-v1"


def test_pairs_are_not_made_across_generations(app):
    """版をまたいだ ⭐/✗ を対にしない。

    プロンプトを組み直さない理由と同じ。対の2つは「同じ入力に対する別々の出力」で
    なければならず、片方が別のモデルの出力なら、差はサンプリングの揺れではなく
    モデルの差になる。それを学習すると「前の自分より今の自分を好め」を教えることになる。
    """
    app.say("同じ問い", "s1")
    old = app.exchanges[-1]
    stars_store.put(
        app.db,
        old.companion_event_id,
        rating=stars_store.RATING_AVOID,
        prompt=old.messages,
        model="offline-stub",
        adapter="",
    )
    # 同じプロンプトに、LoRA を当てたあとの応答として ⭐ が付いた形を作る
    new_event = events_store.append(app.db, old.session_id, "companion", "当てたあとの応答")
    stars_store.put(
        app.db,
        new_event.id,
        rating=stars_store.RATING_KEEP,
        prompt=old.messages,
        model="offline-stub",
        adapter="nano-v1",
    )

    built = dataset_module.build(app.db)
    assert built.pairs == [], "版をまたいだ対は作らない"
    assert built.cross_generation == 1, "捨てたことは数えて見せる"
