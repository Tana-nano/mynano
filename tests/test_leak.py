"""記憶の焼き付き検査（`nano leak`）のテスト。"""

from __future__ import annotations

import json

from nano.persona import leak as leak_module
from nano.persona.compose import build_bare_system_prompt
from nano.store import state as state_store
from nano.store.notes import KIND_SELF, insert as insert_note

from conftest import converse

CONVERSATION = [
    "妹の名前はミオ。ミオは高校生で吹奏楽部にいる",
    "ミオはトランペットを吹いている。来月コンクールがあるらしい",
    "僕は猫を飼っている。名前はクロで、もう12歳になる",
]


def test_bare_prompt_has_only_constitution_and_memory_rules(app):
    """自己像・相手像・いまの状態・想起した記憶のどれも含まないこと。

    そのどれかに固有名詞が混ざっていれば、モデルは正当に答えられてしまい、
    検査が「重みに焼けているか」ではなく「プロンプトに漏れていないか」を測る
    ものにすり替わる。
    """
    state_store.set_value(app.db, state_store.KEY_CURRENT_FOCUS, "ミオのコンクール")
    state_store.set_value(app.db, state_store.KEY_MOOD, "楽しみ")
    insert_note(app.db, "わたしは即答するより黙って考える方が多い", kind=KIND_SELF)

    bare = build_bare_system_prompt(app.config)

    assert "テスト用の憲章" in bare
    assert "記憶の扱い" in bare
    # 単なる部分文字列ではなく、実際にセクションとして積まれていないことを見る。
    # 「記憶の扱い」の説明文自体に「思い出したこと」という語が出てくるため。
    assert "## 思い出したこと" not in bare
    assert "## 相手について" not in bare
    assert "## 自分について" not in bare
    assert "## いまの状態" not in bare
    assert "ミオ" not in bare


def test_default_stub_leaks_nothing(app):
    """スタブは正直な素のモデルのふりをするので、何も漏れないはず。"""
    converse(app, CONVERSATION)
    app.ingest()

    report = leak_module.run(
        app.config, app.db, app.llm, app.embedder, llm_identity=app.llm_identity
    )

    assert report.results, "固有名詞が抽出できていること"
    assert report.leaked == []
    assert report.conditions.llm == "offline-stub"

    saved = json.loads(leak_module.leak_path(app.config).read_text(encoding="utf-8"))
    assert saved["conditions"]["llm"] == "offline-stub"
    assert saved["results"]


def test_overridden_llm_leaks_a_fact(app):
    """LoRA が記憶を焼いてしまった状態を模す: 具体的な事実を答えるハンドラに差し替える。"""
    converse(app, CONVERSATION)
    app.ingest()

    app.llm.handlers["leak"] = lambda messages: "ミオは高校2年生でトランペット担当です。"

    report = leak_module.run(app.config, app.db, app.llm, app.embedder)

    assert report.leaked, "具体的な事実を答えたら漏れとして検出されること"
    for result in report.leaked:
        assert result.claims_knowledge
        assert result.answer == "ミオは高校2年生でトランペット担当です。"


def test_entity_selection_prefers_names_that_appear_in_star_prompts(app):
    """⭐ の教師データに実際に出てきた固有名詞を、参照数より優先すること。

    先に「クロ」だけの会話で ⭐ を押し（このときの system プロンプトに
    「ミオ」が入りようがない）、その後「ミオ」の話を増やして参照数を逆転させる。
    それでも選ばれる順番は「クロ」が先であるべき——実際に教師データに載ったのは
    「クロ」のほうだから。
    """
    converse(app, ["猫の名前はクロ。クロは人懐っこい"])
    app.ingest()
    app.say("クロの調子はどう？", "s-leak")
    app.star()

    converse(
        app,
        [
            "妹の名前はミオ。ミオは高校生で吹奏楽部にいる",
            "ミオはトランペットを吹いている。来月コンクールがあるらしい",
            "ミオの友達もたくさん褒めてくれる",
        ],
    )
    app.ingest()

    from nano.store import entities as entities_store

    counts = dict(entities_store.counts(app.db, limit=50))
    assert counts["ミオ"] > counts["クロ"], "参照数はミオのほうが多いという前提"

    preferred = leak_module.select_entity_names(app.db, limit=20)
    assert preferred.index("クロ") < preferred.index("ミオ"), (
        "⭐ のプロンプトに登場した名前を、参照数に関わらず優先すること"
    )


def test_no_entities_means_an_empty_report(app):
    """記憶も ⭐ も無ければ、調べる固有名詞が無い。"""
    report = leak_module.run(
        app.config, app.db, app.llm, app.embedder, llm_identity=app.llm_identity
    )
    assert report.results == []
    assert report.leaked == []
