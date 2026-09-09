"""テスト用の足場。

すべてのテストは offline スタブ（OfflineLLM + HashEmbedder）で動く。
ローカルLLMサーバーが無い環境でも回帰を検出できることを優先している。
"""

from __future__ import annotations

import json

import pytest

from nano.app import App
from nano.config import Config, PathsConfig

DAY = 86400.0


@pytest.fixture
def config(tmp_path) -> Config:
    config = Config(root=tmp_path, paths=PathsConfig(soul_dir="soul"))
    config.persona.constitution_path = str(tmp_path / "constitution.md")
    (tmp_path / "constitution.md").write_text("あなたは nano。テスト用の憲章。", encoding="utf-8")
    return config


@pytest.fixture
def app(config) -> App:
    instance = App.build(config, offline=True)
    yield instance
    instance.close()


def converse(app: App, lines, session_id: str = "s-test") -> None:
    for line in lines:
        app.say(line, session_id)


def write_baseline(config, embedding: str, llm: str = "offline-stub", adapter: str = ""):
    """測定条件つきの人格ベースラインを置く（テスト用）。

    条件を書かない素の `{}` は「どのものさしで取ったか分からない基準」として
    弾かれるようになったので、テストからもそれは作らない。
    """
    from nano.persona.drift import Baseline, Conditions, baseline_path

    path = baseline_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    conditions = Conditions(embedding=embedding, llm=llm, adapter=adapter)
    path.write_text(
        json.dumps(Baseline(conditions=conditions, entries={}, created="2026-01-01T00:00:00+09:00").to_dict()),
        encoding="utf-8",
    )
    return path

