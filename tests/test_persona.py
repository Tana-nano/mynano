"""人格層のテスト。

「同じ存在であり続ける」を、願望ではなく検査可能な性質にする。
"""

from __future__ import annotations

from pathlib import Path

from nano.memory.retrieve import recall
from nano.persona import drift as drift_module
from nano.persona.compose import build_messages, build_system_prompt
from nano.persona.probes import load
from nano.store import notes as notes_store
from nano.store import state as state_store

PROBES = Path(__file__).resolve().parents[1] / "persona" / "probes.yaml"


def test_constitution_comes_first(app):
    """憲章が最上位に置かれること。人格の優先順位はこの順番そのもの。"""
    state_store.set_value(app.db, state_store.KEY_CURRENT_FOCUS, "猫の話")
    prompt = build_system_prompt(app.config, app.db)
    assert prompt.startswith("あなたは nano。テスト用の憲章。")
    assert prompt.index("テスト用の憲章") < prompt.index("いまの状態")


def test_unconscious_state_reaches_the_prompt(app):
    """無意識が書き換えた working_state が、次の対話に静かに流れ込むこと。"""
    state_store.set_value(app.db, state_store.KEY_CURRENT_FOCUS, "紫陽花のこと", "unconscious")
    state_store.set_value(app.db, state_store.KEY_MOOD, "静か", "unconscious")
    prompt = build_system_prompt(app.config, app.db)
    assert "紫陽花のこと" in prompt
    assert "静か" in prompt


def test_recalled_memories_appear_with_dates(app):
    note = notes_store.insert(app.db, "妹の名前はミオ")
    vector = app.embedder.embed_documents([note.content])[0]
    notes_store.set_vector(app.db, note.id, vector)
    app.index.add(note.id, vector)

    memories = recall(
        app.db, app.index, app.embedder, "妹", app.config.retrieval, app.config.decay, touch=False
    )
    prompt = build_system_prompt(app.config, app.db, memories)
    assert "思い出したこと" in prompt
    assert "妹の名前はミオ" in prompt
    assert "覚えていないことは、覚えていないと言う" in prompt, "捏造禁止の指示が常に付くこと"


def test_self_notes_are_part_of_identity(app):
    notes_store.insert(app.db, "わたしは即答するより黙って考える方が多い", kind=notes_store.KIND_SELF)
    prompt = build_system_prompt(app.config, app.db)
    assert "自分について気づいていること" in prompt
    assert "黙って考える" in prompt


def test_messages_include_recent_turns_in_order(app):
    app.say("最初の話", "s1")
    app.say("次の話", "s1")
    from nano.store import events as events_store

    recent = events_store.recent(app.db, "s1", 10)
    messages = build_messages(app.config, app.db, "三番目の話", None, recent)

    assert messages[0]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "三番目の話"}
    roles = [m["role"] for m in messages[1:-1]]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_probes_are_loadable():
    probes = load(PROBES)
    assert len(probes) >= 15
    assert all(probe.id and probe.prompt for probe in probes)
    assert {"identity", "memory", "relation", "style", "value"} <= {p.category for p in probes}


def test_first_probe_run_creates_a_baseline(app):
    app.config.persona.probes_path = str(PROBES)
    report = drift_module.run(app.config, app.db, app.llm, app.embedder)
    assert report.baseline_created
    assert report.mean_similarity is None, "基準が無い初回はずれを測れない"
    assert drift_module.baseline_path(app.config).exists()


def test_second_probe_run_measures_drift(app):
    app.config.persona.probes_path = str(PROBES)
    drift_module.run(app.config, app.db, app.llm, app.embedder)
    again = drift_module.run(app.config, app.db, app.llm, app.embedder)

    assert again.mean_similarity is not None
    assert again.mean_similarity > 0.99, "同じ設定なら人格は動かないはず"
