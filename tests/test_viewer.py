"""記憶グラフのテスト。

見ているのは3つ:
  - 統合された記憶が畳まれ、それでもグラフが繋がったままであること
  - 書き出した HTML が本当に単体で完結していること（外部読み込みゼロ）
  - 記憶の本文が HTML/JS を壊さないこと
"""

from __future__ import annotations

import json
import re
import threading
import urllib.request
from http.server import HTTPServer

import pytest

from nano.store import graph as graph_store
from nano.store import notes as notes_store
from nano.viewer import data as graph_data
from nano.viewer import page as graph_page
from nano.viewer import server as graph_server

from conftest import converse

CONVERSATION = [
    "妹の名前はミオ。高校生で吹奏楽部にいる",
    "猫のクロは12歳。最近あまり動かない",
    "好きな作家は伊坂幸太郎",
]


def add_note(app, content, **kwargs):
    note = notes_store.insert(app.db, content, **kwargs)
    vector = app.embedder.embed_documents([content])[0]
    notes_store.set_vector(app.db, note.id, vector)
    app.index.add(note.id, vector)
    return note


# --- データ ---
def test_build_returns_nodes_and_edges(app):
    converse(app, CONVERSATION)
    app.ingest()
    payload = graph_data.build(app.db, app.config.decay)

    assert payload.nodes
    assert payload.stats["shown"] == len(payload.nodes)
    for node in payload.nodes:
        assert {"id", "content", "origin", "halfLife", "retrievability", "state"} <= set(node)
        assert 0.0 <= node["retrievability"] <= 1.0


def test_origin_separates_who_made_the_memory(app):
    """色を割り当てる唯一の軸。ここが崩れると可視化の意味が無くなる。"""
    spoken = add_note(app, "妹の名前はミオ")
    thought = add_note(app, "ユーザーは家族の話をよくする", kind=notes_store.KIND_REFLECTION)

    payload = graph_data.build(app.db, app.config.decay)
    origins = {node["id"]: node["origin"] for node in payload.nodes}
    assert origins[spoken.id] == graph_data.ORIGIN_SELF
    assert origins[thought.id] == graph_data.ORIGIN_UNCONSCIOUS


def test_world_origin_comes_from_ingested_files(app):
    from nano.unconscious.jobs import ingest

    (app.config.inbox_dir / "memo.md").write_text("引っ越し先は中野が第一候補", encoding="utf-8")
    ingest.run(app, None)
    app.ingest()

    payload = graph_data.build(app.db, app.config.decay)
    assert any(node["origin"] == graph_data.ORIGIN_WORLD for node in payload.nodes)


def test_merged_notes_are_folded_into_their_parent(app):
    parent = add_note(app, "散歩に行った日々のまとまり")
    children = [add_note(app, f"散歩に行った記録その{i}") for i in range(3)]
    for child in children:
        notes_store.set_state(app.db, child.id, notes_store.STATE_MERGED, merged_into=parent.id)

    payload = graph_data.build(app.db, app.config.decay)
    shown = {node["id"] for node in payload.nodes}
    assert parent.id in shown
    assert not shown & {child.id for child in children}, "統合済みの記憶が別の点として残っている"

    node = next(n for n in payload.nodes if n["id"] == parent.id)
    assert sorted(node["mergedChildren"]) == sorted(child.id for child in children)


def test_links_to_merged_notes_are_redirected_to_the_parent(app):
    """畳んだせいでグラフが千切れないこと。"""
    parent = add_note(app, "まとまった記憶")
    child = add_note(app, "吸収された記憶")
    other = add_note(app, "関係のある別の記憶")
    notes_store.set_state(app.db, child.id, notes_store.STATE_MERGED, merged_into=parent.id)
    graph_store.add(app.db, child.id, other.id, "similar", 0.8, symmetric=True)

    payload = graph_data.build(app.db, app.config.decay)
    pairs = {(edge["source"], edge["target"]) for edge in payload.edges}
    assert (parent.id, other.id) in pairs or (other.id, parent.id) in pairs


def test_mutual_links_are_drawn_once(app):
    first = add_note(app, "妹の名前はミオ")
    second = add_note(app, "ミオはトランペットを吹く")
    graph_store.add(app.db, first.id, second.id, "similar", 0.8, symmetric=True)

    payload = graph_data.build(app.db, app.config.decay)
    assert len(payload.edges) == 1


def test_merged_from_links_are_not_drawn(app):
    parent = add_note(app, "まとまった記憶")
    child = add_note(app, "吸収された記憶")
    notes_store.set_state(app.db, child.id, notes_store.STATE_MERGED, merged_into=parent.id)
    graph_store.add(app.db, parent.id, child.id, "merged_from", 1.0)

    payload = graph_data.build(app.db, app.config.decay)
    assert payload.edges == [], "統合の履歴は線ではなくノード側で表す"


def test_cold_memories_are_kept_and_marked(app):
    """薄れている記憶が見えることに意味がある。消してはいけない。"""
    faded = add_note(app, "薄れた記憶")
    notes_store.set_state(app.db, faded.id, notes_store.STATE_COLD)

    payload = graph_data.build(app.db, app.config.decay)
    node = next(n for n in payload.nodes if n["id"] == faded.id)
    assert node["state"] == notes_store.STATE_COLD


def test_limit_keeps_the_memories_that_matter(app):
    add_note(app, "とても大事な記憶", importance=0.95, half_life_days=300.0)
    for index in range(12):
        add_note(app, f"どうでもいい記憶その{index}", importance=0.05, half_life_days=1.0)

    payload = graph_data.build(app.db, app.config.decay, limit=3)
    assert len(payload.nodes) == 3
    assert any("とても大事な記憶" == node["content"] for node in payload.nodes)


def test_note_detail_includes_lineage_and_episode(app):
    converse(app, CONVERSATION)
    app.ingest()
    note = notes_store.iter_notes(app.db)[0]

    detail = graph_data.note_detail(app.db, note.id, app.config.decay)
    assert detail["content"] == note.content
    assert "lineage" in detail
    assert detail["episodeSummary"]


def test_note_detail_for_a_missing_note(app):
    assert graph_data.note_detail(app.db, 999_999, app.config.decay) is None


# --- HTML ---
def test_exported_page_loads_nothing_from_the_network(app):
    """CDN を使えば楽だが、ネットが無いと魂が見えなくなる。"""
    converse(app, CONVERSATION)
    app.ingest()
    html = graph_page.render("test", payload=graph_data.build(app.db, app.config.decay).to_dict())

    assert not re.search(r'(?:src|href)\s*=\s*["\']https?://', html)
    assert "@import" not in html
    assert "cdn." not in html


def test_exported_page_embeds_the_data(app):
    converse(app, CONVERSATION)
    app.ingest()
    payload = graph_data.build(app.db, app.config.decay)
    html = graph_page.render("nano の記憶", payload=payload.to_dict())

    assert "const RAW = null" not in html
    assert payload.nodes[0]["content"] in html
    assert "__NANO_DATA__" not in html and "__NANO_API__" not in html


def test_live_page_defers_to_the_api(app):
    html = graph_page.render("nano", api_base="/api")
    assert "const RAW = null" in html
    assert 'const API = "/api"' in html


def test_a_memory_cannot_break_out_of_the_script_tag(app):
    """記憶の本文は何が書かれるか分からない。ページを壊させない。"""
    add_note(app, '</script><script>window.__owned = 1</script>')
    html = graph_page.render("nano", payload=graph_data.build(app.db, app.config.decay).to_dict())

    body = html.split("const RAW = ", 1)[1]
    assert "</script><script>" not in body.split(";\nconst API", 1)[0]
    assert "<\\/script>" in html


def test_title_is_escaped(app):
    html = graph_page.render('<img src=x onerror="alert(1)">')
    assert "<img src=x" not in html
    assert "&lt;img" in html


# --- サーバー ---
@pytest.fixture
def live(app):
    """サーバーはメインスレッドで1件だけ処理する。

    soul.db の接続はメインスレッド専用なので、リクエスト側を別スレッドに出す。
    """
    converse(app, CONVERSATION)
    app.ingest()
    server = HTTPServer(("127.0.0.1", 0), graph_server.make_handler(app, 100))
    yield server, f"http://127.0.0.1:{server.server_port}"
    server.server_close()


def fetch(server, url):
    result = {}

    def call():
        try:
            with urllib.request.urlopen(url, timeout=5) as response:
                result["status"] = response.status
                result["body"] = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            result["status"] = error.code
            result["body"] = ""

    client = threading.Thread(target=call)
    client.start()
    server.handle_request()
    client.join(timeout=5)
    return result


def test_server_serves_the_page(live):
    server, base = live
    result = fetch(server, base + "/")
    assert result["status"] == 200
    assert "nano" in result["body"]
    assert 'const API = "/api"' in result["body"]


def test_server_serves_the_graph(live):
    server, base = live
    result = fetch(server, base + "/api/graph")
    payload = json.loads(result["body"])
    assert result["status"] == 200
    assert payload["nodes"]


def test_server_serves_one_note(live, app):
    server, base = live
    note = notes_store.iter_notes(app.db)[0]
    result = fetch(server, f"{base}/api/note/{note.id}")
    assert json.loads(result["body"])["content"] == note.content


def test_server_reports_a_missing_note(live):
    server, base = live
    assert fetch(server, base + "/api/note/999999")["status"] == 404


def test_server_rejects_a_bad_note_id(live):
    server, base = live
    assert fetch(server, base + "/api/note/abc")["status"] == 400
