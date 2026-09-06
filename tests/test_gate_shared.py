"""プロセス間の推論ゲートのテスト。

M1 で作った「対話が来たら背景の思考を中断させる」性質は、
デーモンが別プロセスになった瞬間にプロセス境界で失われる。
それを SQLite のリースで繋ぎ直したのが SharedInferenceGate。
ここが壊れると、話しかけても背景処理が終わるまで返事が来なくなる。
"""

from __future__ import annotations

import threading
import time

import pytest

from nano.gate import PRIORITY_BACKGROUND, PRIORITY_CHAT, Preempted, SharedInferenceGate
from nano.store.db import Database


@pytest.fixture
def gates(tmp_path):
    """別プロセス相当。それぞれ独立した接続を持つ2つのゲート。"""
    path = tmp_path / "soul.db"
    db = Database(path)
    daemon = SharedInferenceGate(path, holder="daemon", ttl_s=2.0, heartbeat_s=0.05)
    chat = SharedInferenceGate(path, holder="chat", ttl_s=2.0, heartbeat_s=0.05)
    yield daemon, chat
    daemon.close()
    chat.close()
    db.close()


def test_chat_preempts_the_daemon_across_processes(gates):
    daemon_gate, chat_gate = gates
    events: list[str] = []

    def background():
        try:
            with daemon_gate.acquire(PRIORITY_BACKGROUND) as cancel:
                for _ in range(400):
                    time.sleep(0.01)
                    cancel.raise_if_cancelled()
                events.append("background-finished")
        except Preempted:
            events.append("background-preempted")

    worker = threading.Thread(target=background)
    worker.start()
    time.sleep(0.2)  # 背景がリースを持っている状態にする

    started = time.monotonic()
    with chat_gate.acquire(PRIORITY_CHAT):
        events.append("chat-ran")
    waited = time.monotonic() - started

    worker.join(timeout=5)
    assert events == ["background-preempted", "chat-ran"]
    assert waited < 1.5, "対話が背景処理の完了を待たされている"


def test_lease_is_exclusive(gates):
    daemon_gate, chat_gate = gates
    with daemon_gate.acquire(PRIORITY_BACKGROUND):
        row = daemon_gate._conn.execute("SELECT holder FROM model_lease WHERE id=1").fetchone()
        assert row["holder"] == "daemon"
    row = daemon_gate._conn.execute("SELECT holder FROM model_lease WHERE id=1").fetchone()
    assert row["holder"] == "", "解放されていない"


def test_crashed_holder_lease_expires(gates, tmp_path):
    """保持者のプロセスが死んでも、期限切れでモデルは戻ってくる。"""
    daemon_gate, chat_gate = gates
    # 死んだプロセスがリースを握ったまま消えた状態を作る
    daemon_gate._conn.execute(
        "UPDATE model_lease SET holder='ghost', priority=10, expires_at=? WHERE id=1",
        (time.time() - 1.0,),
    )
    started = time.monotonic()
    with chat_gate.acquire(PRIORITY_CHAT):
        pass
    assert time.monotonic() - started < 1.0


def test_background_waits_for_chat(gates):
    """優先度が逆のときは、背景側がおとなしく待つこと。"""
    daemon_gate, chat_gate = gates
    order: list[str] = []

    def background():
        with daemon_gate.acquire(PRIORITY_BACKGROUND):
            order.append("background")

    with chat_gate.acquire(PRIORITY_CHAT):
        worker = threading.Thread(target=background)
        worker.start()
        time.sleep(0.3)
        order.append("chat")
    worker.join(timeout=5)

    assert order == ["chat", "background"]
