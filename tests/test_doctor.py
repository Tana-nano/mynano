"""実機に載せる前の点検。

詰まりどころを1回ずつエラーで踏ませない、というだけの道具。
ただし「何も直さない」ことと「同一性が食い違っていても診られる」ことは
性質として守りたいので、そこを押さえる。
"""

from __future__ import annotations

import pytest

from fake_server import FakeServer
from nano import doctor
from nano.persona.drift import baseline_path
from nano.store import identity as identity_store
from nano.store.db import Database


@pytest.fixture
def server():
    instance = FakeServer()
    yield instance
    instance.close()


@pytest.fixture
def wired(config, server):
    """実機と同じ形（実クライアント）で、繋がる状態にした config。"""
    config.llm.base_url = server.base_url
    config.embed.base_url = server.base_url
    config.embed.dim = 8
    config.ensure_dirs()
    return config


def _by_title(report) -> dict[str, doctor.Finding]:
    return {finding.title: finding for finding in report.findings}


def test_a_healthy_setup_passes(wired):
    baseline_path(wired).write_text("{}", encoding="utf-8")
    report = doctor.run(wired)
    found = _by_title(report)
    assert found["対話モデル"].status == doctor.OK
    assert found["埋め込みモデル"].status == doctor.OK
    assert found["人格ベースライン"].status == doctor.OK
    # キャリブレーションだけは未測定なので落ちる（実機の初回はここから始まる）
    assert found["キャリブレーション"].status == doctor.FAIL
    assert report.failed == 1


def test_unreachable_servers_are_reported_with_a_remedy(config):
    config.llm.base_url = "http://127.0.0.1:1/v1"
    config.embed.base_url = "http://127.0.0.1:1/v1"
    config.llm.timeout_s = 2.0
    config.embed.timeout_s = 2.0

    found = _by_title(doctor.run(config))
    assert found["対話モデル"].status == doctor.FAIL
    assert "llama-server" in found["対話モデル"].remedy
    assert found["埋め込みモデル"].status == doctor.FAIL


def test_dim_mismatch_points_at_the_config(wired, server):
    wired.embed.dim = 1024  # サーバーは8次元を返す
    found = _by_title(doctor.run(wired))
    assert found["埋め込みモデル"].status == doctor.FAIL
    assert "dim" in found["埋め込みモデル"].remedy


def test_it_still_runs_when_the_embedding_identity_disagrees(wired):
    """App.build は止まる状況。止まるからこそ、点検は通らないと困る。"""
    db = Database(wired.db_path)
    identity_store.record(db, "べつのモデル@8")
    db.close()

    found = _by_title(doctor.run(wired))
    assert found["埋め込み同一性"].status == doctor.FAIL
    assert "nano reembed" in found["埋め込み同一性"].remedy


def test_it_does_not_repair_anything(wired):
    """点検の副作用で魂に触らない。一番壊れてほしくないものなので。"""
    db = Database(wired.db_path)
    identity_store.record(db, "べつのモデル@8")
    db.close()

    doctor.run(wired)

    db = Database(wired.db_path)
    try:
        assert identity_store.recorded(db) == "べつのモデル@8"  # 直っていない
    finally:
        db.close()
    assert not (wired.soul_dir / "calibration.json").exists()
    assert not baseline_path(wired).exists()


def test_dense_links_are_flagged(wired):
    from nano.store import graph as graph_store
    from nano.store import notes as notes_store

    db = Database(wired.db_path)
    notes = [notes_store.insert(db, f"記憶{index}") for index in range(4)]
    for source in notes:
        for target in notes:
            for relation in ("similar", "elaborates", "causes", "contradicts"):
                graph_store.add(db, source.id, target.id, relation, symmetric=True)
    db.close()

    found = _by_title(doctor.run(wired))
    assert found["リンク密度"].status == doctor.FAIL
    assert "link_max_per_note" in found["リンク密度"].remedy


def test_offline_is_refused(capsys):
    from nano.cli.main import main

    assert main(["--offline", "doctor"]) == 2
    assert "--offline" in capsys.readouterr().err
