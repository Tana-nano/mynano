"""記憶ベンチの回帰テスト。

重み・半減期・パイプラインをいじったときに、記憶の品質が落ちたことに
気づけるようにする。オフラインのスタブで測っているので、絶対値は
「本物の埋め込みならこうなる」という値ではない。見ているのは
**配線と忘却曲線の形が壊れていないこと**。実際の数字は
`python tests/bench/memory_bench.py --online` で測る。
"""

from __future__ import annotations

import time

import pytest

from bench.memory_bench import DAY, run


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    from nano.app import App
    from nano.config import Config, PathsConfig

    tmp = tmp_path_factory.mktemp("bench")
    app = App.build(Config(root=tmp, paths=PathsConfig(soul_dir="soul")), offline=True)
    try:
        yield run(app, base_ts=time.time() - 120 * DAY)
    finally:
        app.close()


def test_recalls_important_facts_immediately(report):
    assert report.recall_results[0].rate >= 0.75


def test_still_recalls_important_facts_after_three_months(report):
    """一度話しただけの生活の事実が、3か月後にも出てくること。"""
    assert report.recall_results[-1].at_days == 90
    assert report.recall_results[-1].rate >= 0.6


def test_recall_does_not_collapse_over_time(report):
    """時間経過で想起率が崖のように落ちないこと（忘却が効きすぎていない）。"""
    first, last = report.recall_results[0].rate, report.recall_results[-1].rate
    assert last >= first - 0.25


def test_trivia_actually_fades(report):
    """忘れていいことは忘れる。全部残るならそれは記憶ではなくログ。"""
    assert report.forgetting_rate >= 0.4


def test_important_memories_outlive_trivia(report):
    important_survival = report.facts_active / report.facts_total
    trivia_survival = report.trivia_active / report.trivia_total
    assert important_survival > trivia_survival
