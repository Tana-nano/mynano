"""キャリブレーションのテスト。

コサインの絶対値はモデルごとに違う帯に分布する。だからしきい値は
「平均から何σ離れているか」で持つ。ここが効いていないと、
モデルを差し替えた瞬間にリンクが全通しになるか、全弾きになる。
"""

from __future__ import annotations

import pytest

from nano import calibration as calibration_module
from nano.embed import HashEmbedder
from nano.memory import pipeline
from nano.store import events as events_store
from nano.store import notes as notes_store

from conftest import converse

CONVERSATION = [
    "妹の名前はミオ。高校生で吹奏楽部にいる",
    "ミオはトランペットを吹いていて来月コンクールがある",
    "猫のクロは12歳。最近あまり動かない",
    "好きな作家は伊坂幸太郎",
]


# --- 分布 ---
def test_distribution_statistics():
    dist = calibration_module.Distribution.of([0.0, 0.5, 1.0])
    assert dist.mean == pytest.approx(0.5)
    assert dist.n == 3
    assert dist.p50 == pytest.approx(0.5)


def test_threshold_is_monotonic_in_sigma():
    dist = calibration_module.Distribution.of([0.1, 0.2, 0.3, 0.4, 0.5])
    assert dist.threshold(0.0) < dist.threshold(1.0) < dist.threshold(2.0)


def test_empty_distribution_does_not_explode():
    assert calibration_module.Distribution.of([]).n == 0


# --- 測定 ---
def test_measure_uses_bundled_probes_when_memories_are_few(app):
    measured = calibration_module.measure(app, seed=0)
    assert measured.source == "probes"
    assert measured.similarity.n > 100
    assert measured.identity == "hash@1024"


def test_measure_uses_your_own_memories_once_there_are_enough(app):
    for index in range(calibration_module.MIN_NOTES_FOR_SELF_MEASURE + 5):
        notes_store.insert(app.db, f"これは{index}番目の記憶についての文である")
    measured = calibration_module.measure(app, seed=0)
    assert measured.source == "notes", "自分の記憶があるならそちらの分布を使うこと"


def test_measure_records_the_drift_between_turns(app):
    converse(app, CONVERSATION * 3)
    measured = calibration_module.measure(app, seed=0)
    assert measured.has_drift
    assert 0.0 <= measured.drift.mean <= 2.0


def test_save_and_load_round_trip(app):
    measured = calibration_module.measure(app, seed=0)
    calibration_module.save(app.config, measured)

    loaded = calibration_module.load(app.config, "hash@1024")
    assert loaded is not None
    assert loaded.identity == measured.identity
    assert loaded.similarity.mean == pytest.approx(measured.similarity.mean)


def test_calibration_from_another_model_is_ignored(app):
    """別のモデルで測った分布は、そのモデルのものさしでしかない。"""
    calibration_module.save(app.config, calibration_module.measure(app, seed=0))
    assert calibration_module.load(app.config, "multilingual-e5-large@1024") is None


def test_missing_calibration_is_simply_absent(app):
    assert calibration_module.load(app.config, "hash@1024") is None


# --- しきい値としての効き方 ---
def test_thresholds_stay_within_cosine_range(app):
    measured = calibration_module.measure(app, seed=0)
    assert -1.0 <= measured.similarity_threshold(99.0) <= 1.0
    assert 0.0 <= measured.drift_threshold(99.0) <= 2.0


def test_pipeline_falls_back_to_absolute_values_without_calibration(app):
    """未測定なら、いまの絶対値のまま。既存の挙動を変えない。"""
    assert app.calibration is None
    converse(app, CONVERSATION)
    report = app.ingest()
    assert report.notes > 0


def test_calibrated_sigma_actually_drives_link_formation(app):
    """σ を動かすとリンクの張られ方が変わること。

    しきい値が本当にキャリブレーション由来かどうかは、σ を極端に振って
    結果が変わるかで確かめられる。設定値を読んでいるだけでは確かめたことにならない。
    """
    measured = calibration_module.measure(app, seed=0)
    calibration_module.save(app.config, measured)
    app.reload_calibration()
    assert app.calibration is not None

    # 全部弾くσ（平均から遠すぎる位置）
    app.config.pipeline.link_min_sigma = 99.0
    converse(app, CONVERSATION)
    app.ingest()
    strict_links = app.db.scalar("SELECT COUNT(*) FROM links WHERE created_by != 'pipeline'")

    # 全部通すσ
    app.config.pipeline.link_min_sigma = -99.0
    converse(app, ["引っ越し先は中野が第一候補", "内見は今週末に行く", "職場までは20分かかる"])
    app.ingest()
    loose_links = app.db.scalar("SELECT COUNT(*) FROM links WHERE created_by != 'pipeline'")

    assert strict_links == 0, "σ を上げても足切りが効いていない"
    assert loose_links > 0, "σ を下げても足切りが緩まない"


def test_segmentation_threshold_comes_from_the_measured_drift(app):
    """ドリフトのしきい値も同じく、σ を振れば分割のされ方が変わること。"""
    converse(app, CONVERSATION * 3)
    measured = calibration_module.measure(app, seed=0)
    assert measured.has_drift

    events = events_store.pending(app.db)
    app.config.pipeline.segment_drift_sigma = -99.0  # 何でも切れ目とみなす
    eager = pipeline.segment(events, app.embedder, app.config, measured)
    app.config.pipeline.segment_drift_sigma = 99.0  # 決して切らない
    reluctant = pipeline.segment(events, app.embedder, app.config, measured)

    assert len(eager) > len(reluctant), "σ がセグメント分割に効いていない"
    # どちらの設定でも、生ログを1件も落とさないこと
    for segments in (eager, reluctant):
        assert sum(len(chunk) for chunk in segments) == len(events)


def test_recommendations_compare_absolute_and_effective(app):
    measured = calibration_module.measure(app, seed=0)
    rows = calibration_module.recommendations(measured, app.config)
    assert rows
    for label, absolute, effective in rows:
        assert isinstance(label, str) and label
        assert isinstance(absolute, (int, float))
        assert isinstance(effective, (int, float))


def test_hash_embedder_sits_in_a_different_band_than_trained_models(app):
    """絶対しきい値が移植できないことの実測。

    ハッシュ埋め込みでは無関係な文どうしが ≈0 に集まる。対比学習で訓練された
    モデル（multilingual-e5 など）では、無関係な文でも 0.7 前後に固まる。
    同じ 0.32 という数字が、前者では「ほとんど通さない」、後者では
    「全部通す」になる。だからしきい値は分布に対する相対位置で持つ。
    """
    measured = calibration_module.measure(app, seed=0)
    assert abs(measured.similarity.mean) < 0.2, "ハッシュ埋め込みは 0 付近に集まるはず"
    assert measured.similarity.std < 0.3
