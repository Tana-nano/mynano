"""実機の HTTP 経路。

これまで全テストは `OfflineLLM` + `HashEmbedder` で走っており、
`LlamaServerLLM` と `ServerEmbedder` は**一度も実行されていなかった**。
実機で初めて火が入る場所が一番危ないので、偽サーバーを立てて通しておく。

意味の質はここでは測れない（それは実機の e5 と実モデルの仕事）。
ここで押さえるのは配線だけ: URL の組み立て、SSE の解釈、JSON の拾い方、
エラーの出方、中断の効き方。
"""

from __future__ import annotations

import pytest

from fake_server import FakeServer
from nano.app import App
from nano.config import EmbedConfig
from nano.embed import ServerEmbedder, build_embedder
from nano.gate import CancelToken, Preempted
from nano.llm import LlamaServerLLM, LLMError


@pytest.fixture
def server():
    instance = FakeServer()
    yield instance
    instance.close()


@pytest.fixture
def llm(server):
    client = LlamaServerLLM(base_url=server.base_url, model="test-model")
    yield client
    client.close()


@pytest.fixture
def embedder(server):
    client = ServerEmbedder(base_url=server.base_url, model="test-embed", dim=8)
    yield client
    client.close()


# --- URL の組み立て --------------------------------------------------------


def test_base_url_keeps_the_v1_prefix(server, llm):
    """`http://host/v1` + `/chat/completions` が `/v1/chat/completions` になること。

    ここを取り違えると、実機で 404 が返るだけで理由が分からない。
    """
    llm.chat([{"role": "user", "content": "こんにちは"}])
    assert server.script.seen[0]["path"] == "/v1/chat/completions"


def test_trailing_slash_does_not_double_up(server):
    client = LlamaServerLLM(base_url=server.base_url + "/")
    try:
        client.chat([{"role": "user", "content": "x"}])
    finally:
        client.close()
    assert server.script.seen[0]["path"] == "/v1/chat/completions"


def test_api_key_becomes_a_bearer_header(server):
    client = LlamaServerLLM(base_url=server.base_url, api_key="secret")
    try:
        client.chat([{"role": "user", "content": "x"}])
    finally:
        client.close()
    assert server.script.seen[0]["headers"]["Authorization"] == "Bearer secret"


# --- SSE ------------------------------------------------------------------


def test_streams_tokens_as_they_arrive(server, llm):
    server.script.replies = ["こんばんは"]
    seen: list[str] = []
    answer = llm.chat([{"role": "user", "content": "やあ"}], on_token=seen.append)

    assert answer == "こんばんは"
    assert seen == list("こんばんは")  # 届いた順に1つずつ渡っている


def test_cancel_stops_the_stream(server, llm):
    """対話が割り込んだら、背景の生成は途中で切れること。"""
    server.script.replies = ["長い長い長い応答"]
    token = CancelToken()
    server.script.on_chunk = token.cancel  # 1文字流れた時点で中断が立つ

    with pytest.raises(Preempted):
        llm.chat([{"role": "user", "content": "考えて"}], cancel=token)


def test_http_error_is_reported_with_its_status(server, llm):
    server.script.replies = [503]
    with pytest.raises(LLMError) as caught:
        llm.chat([{"role": "user", "content": "x"}])
    assert "503" in str(caught.value)


def test_unreachable_server_says_where_it_tried():
    """llama-server を起動し忘れたときに、何が起きたか分かること。"""
    client = LlamaServerLLM(base_url="http://127.0.0.1:1/v1", timeout_s=2.0)
    try:
        with pytest.raises(LLMError) as caught:
            client.chat([{"role": "user", "content": "x"}])
    finally:
        client.close()
    assert "127.0.0.1:1" in str(caught.value)


# --- JSON の拾い方 ---------------------------------------------------------


@pytest.mark.parametrize(
    "reply",
    [
        '{"summary": "散歩の話", "salience": 0.7}',
        '```json\n{"summary": "散歩の話", "salience": 0.7}\n```',
        'はい、まとめました。\n{"summary": "散歩の話", "salience": 0.7}\nどうでしょう。',
    ],
    ids=["bare", "fenced", "chatty"],
)
def test_json_survives_how_local_models_actually_answer(server, llm, reply):
    """ローカルモデルは前後に喋る。素の JSON しか読めないと実機で死ぬ。"""
    server.script.replies = [reply]
    assert llm.chat_json([{"role": "user", "content": "要約して"}]) == {
        "summary": "散歩の話",
        "salience": 0.7,
    }


def test_json_is_repaired_once(server, llm):
    server.script.replies = ["すみません、うまく言えません", '{"summary": "二度目で出た"}']
    assert llm.chat_json([{"role": "user", "content": "要約して"}]) == {"summary": "二度目で出た"}
    assert len(server.script.seen) == 2  # 修復は1回だけ


def test_json_gives_up_loudly(server, llm):
    server.script.replies = ["だめでした", "やはりだめでした"]
    with pytest.raises(LLMError) as caught:
        llm.chat_json([{"role": "user", "content": "要約して"}], task="summarize_episode")
    assert "summarize_episode" in str(caught.value)


# --- 埋め込み --------------------------------------------------------------


def test_prefixes_are_applied(server, embedder):
    embedder.embed_query("妹の名前")
    embedder.embed_documents(["妹の名前はミオ"])
    assert server.script.seen[0]["payload"]["input"] == ["query: 妹の名前"]
    assert server.script.seen[1]["payload"]["input"] == ["passage: 妹の名前はミオ"]


def test_results_are_reordered_by_index(server, embedder):
    """サーバーが返す順は index 順とは限らない。並べ替えを飛ばすと記憶が入れ替わる。"""
    texts = ["ひとつめ", "ふたつめ", "みっつめ"]
    got = embedder.embed_documents(texts)
    one_by_one = [embedder.embed_documents([text])[0] for text in texts]
    assert got == one_by_one


def test_batches_are_split_and_kept_in_order(server, embedder):
    embedder.batch_size = 2
    texts = [f"文{index}" for index in range(5)]
    got = embedder.embed_documents(texts)

    assert len(got) == 5
    assert len(server.script.seen) == 3  # 2 + 2 + 1
    assert got == [embedder.embed_documents([text])[0] for text in texts]


def test_dim_mismatch_is_refused(server):
    """次元が違うベクトルを黙って混ぜない（想起が静かに壊れる）。"""
    client = ServerEmbedder(base_url=server.base_url, dim=1024)
    server.script.embedding_dim = 8
    try:
        with pytest.raises(RuntimeError) as caught:
            client.embed_query("x")
    finally:
        client.close()
    assert "1024" in str(caught.value) and "8" in str(caught.value)


def test_vectors_come_back_normalized(server, embedder):
    vector = embedder.embed_query("正規化されているか")
    length = sum(value * value for value in vector) ** 0.5
    assert length == pytest.approx(1.0, abs=1e-6)


def test_build_embedder_falls_back_to_hash_without_a_url():
    assert build_embedder(EmbedConfig(base_url="")).identity.startswith("hash@")


# --- 通し ------------------------------------------------------------------


def test_a_full_turn_over_http(config, server):
    """オフラインスタブを一切通さず、App を実クライアントで組み立てて1往復する。"""
    config.llm.base_url = server.base_url
    config.embed.base_url = server.base_url
    config.embed.dim = 8
    server.script.replies = ["おかえり"]

    app = App.build(config, offline=False)
    try:
        answer, _ = app.say("ただいま", "s1")
        assert answer == "おかえり"
        assert app.embedder.identity == "multilingual-e5-large@8"

        # 生ログも平文ミラーも、オフラインのときと同じように書かれていること
        assert app.db.scalar("SELECT COUNT(*) FROM events") == 2
        mirrored = list(config.archive_dir.glob("*.jsonl"))
        assert mirrored and "おかえり" in mirrored[0].read_text(encoding="utf-8")
    finally:
        app.close()


def test_ingest_over_http(config, server):
    """書き込みパイプラインを実クライアントで通す（JSON を返すのはサーバー側）。"""
    config.llm.base_url = server.base_url
    config.embed.base_url = server.base_url
    config.embed.dim = 8
    server.script.replies = [
        "うん",
        '{"summary": "帰宅の挨拶", "salience": 0.6, "mood": "穏やか"}',
        '{"notes": [{"content": "ユーザーは帰宅時に挨拶する", "importance": 0.5}], "entities": []}',
    ]

    app = App.build(config, offline=False)
    try:
        app.say("ただいま", "s1")
        report = app.ingest()
        assert report.episodes == 1
        assert report.notes == 1
        assert app.db.scalar("SELECT content FROM notes") == "ユーザーは帰宅時に挨拶する"
    finally:
        app.close()


# --- 環境要因 --------------------------------------------------------------


def test_proxy_environment_is_ignored(server, monkeypatch):
    """HTTP_PROXY があっても、自分のマシンの llama-server には直接繋ぐこと。

    通してしまうと、プロキシ側の失敗が「llama-server に繋がらない」という
    嘘のエラーになって出る。会社支給のマシンでは十分あり得る設定なので塞いでおく。
    """
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9/")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)

    client = LlamaServerLLM(base_url=server.base_url, timeout_s=3.0)
    embedder = ServerEmbedder(base_url=server.base_url, dim=8, timeout_s=3.0)
    try:
        assert client.chat([{"role": "user", "content": "x"}])
        assert len(embedder.embed_query("x")) == 8
    finally:
        client.close()
        embedder.close()
