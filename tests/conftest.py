"""テスト用の足場。

すべてのテストは offline スタブ（OfflineLLM + HashEmbedder）で動く。
ローカルLLMサーバーが無い環境でも回帰を検出できることを優先している。
"""

from __future__ import annotations

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
