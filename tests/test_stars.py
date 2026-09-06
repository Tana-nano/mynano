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

from nano.persona import dataset as dataset_module
from nano.persona.drift import baseline_path
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
        dataset_module.export(app.config, app.db)

    baseline_path(app.config).write_text("{}", encoding="utf-8")
    target, built = dataset_module.export(app.config, app.db)

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
