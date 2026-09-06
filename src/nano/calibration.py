"""キャリブレーション — そのモデルの「ものさし」を実測する。

コサイン類似度の絶対値は、埋め込みモデルごとに全く違う帯に分布する。
ハッシュ埋め込みでは無関係な文が ≈0.0 になるが、multilingual-e5 のような
対比学習で訓練されたモデルでは、無関係な文でも 0.7 前後に固まる。

つまり `link_min_similarity = 0.32` のような**絶対値のしきい値は移植できない**。
同じ数字が、あるモデルでは「ほぼ全部を通す」になり、別のモデルでは「ほぼ全部を弾く」になる。

そこで、しきい値を「平均から何σ離れているか」で指定できるようにする。
そのために必要な平均と標準偏差を、**ユーザー自身の記憶を使って**測るのがこのモジュール。
自分の記憶の分布こそが、自分にとって正しい基準になる。

モデルを差し替えたら測り直す。それだけで、しきい値の意味は保たれる。
"""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

from . import vectors
from .store import notes as notes_store
from .store.db import Database, now, to_iso

MAX_PAIRS = 2000
MIN_NOTES_FOR_SELF_MEASURE = 30

# 記憶が少ないうちに使う代用の文。話題がばらけるように選んである
# （実際の記憶と同じく、大半の組み合わせは無関係で、一部だけが近い）。
PROBE_SENTENCES = (
    "妹の名前はミオで、高校二年生になった",
    "ミオは吹奏楽部でトランペットを担当している",
    "ミオの部活は来月コンクールに出るらしい",
    "妹は昔からよく食べるほうだった",
    "飼っている猫の名前はクロで、今年で十二歳",
    "クロは黒猫ではなくキジトラの柄をしている",
    "クロは最近あまり動かなくなってきた",
    "猫の通院で午前休を取ることにした",
    "父は札幌に住んでいて、年に二回だけ会う",
    "母の誕生日は三月八日である",
    "実家に帰るのは正月と盆の二回だけ",
    "職場は代々木にあり、家から電車で二十五分かかる",
    "今日は在宅勤務にして一度も外に出なかった",
    "会議が三つ続いて午後がまるごと潰れた",
    "来月の十二日に引っ越しをする予定がある",
    "内見は今週末に行くことにした",
    "中野と高円寺と阿佐ヶ谷で迷っている",
    "好きな作家は伊坂幸太郎で、特にラッシュライフが好き",
    "本は紙で読みたい派だが場所を取るのが悩み",
    "図書館の返却期限を三日過ぎてしまった",
    "コーヒーは苦手で、飲むのはいつも紅茶",
    "今日の昼は冷やし中華にした",
    "自炊は週に二回できれば良いほう",
    "冷蔵庫の中の消費期限を見落としがちだ",
    "学生のときは弓道をやっていた",
    "運動はここ数年ほとんどしていない",
    "駅の階段で息が切れるようになった",
    "いちばん苦手なのは電話をかけること",
    "人の多い場所にいると急に疲れる",
    "夜のほうが集中できるので朝が弱い",
    "来週の金曜に歯医者の予約を入れた",
    "健康診断の結果はまだ開封していない",
    "今日は雨だったので散歩に行けなかった",
    "梅雨に入ってから洗濯物が乾かない",
    "夏の夕方の匂いが子供の頃を思い出させる",
    "音楽は作業中に歌詞のないものだけ流す",
    "映画館では前から三列目に座ることが多い",
    "写真を撮るのは好きだが見返すことはない",
    "手帳は買っても三月で書かなくなる",
    "眠れない夜は本を読むより天井を見ている",
)


@dataclass
class Distribution:
    mean: float = 0.0
    std: float = 0.0
    p50: float = 0.0
    p90: float = 0.0
    p99: float = 0.0
    n: int = 0

    @classmethod
    def of(cls, values: Sequence[float]) -> "Distribution":
        if not values:
            return cls()
        ordered = sorted(values)
        count = len(ordered)
        mean = sum(ordered) / count
        variance = sum((value - mean) ** 2 for value in ordered) / count
        return cls(
            mean=mean,
            std=math.sqrt(variance),
            p50=_percentile(ordered, 0.50),
            p90=_percentile(ordered, 0.90),
            p99=_percentile(ordered, 0.99),
            n=count,
        )

    def threshold(self, sigma: float) -> float:
        """平均から sigma 標準偏差だけ離れた位置。"""
        return self.mean + sigma * self.std

    def to_dict(self) -> dict:
        return {
            "mean": self.mean, "std": self.std,
            "p50": self.p50, "p90": self.p90, "p99": self.p99, "n": self.n,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Distribution":
        return cls(**{key: data.get(key, 0) for key in ("mean", "std", "p50", "p90", "p99", "n")})


def _percentile(ordered: Sequence[float], fraction: float) -> float:
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
    return ordered[index]


@dataclass
class Calibration:
    identity: str
    measured_at: float
    source: str  # "notes"（自分の記憶） | "probes"（同梱の代用文）
    similarity: Distribution = field(default_factory=Distribution)
    drift: Distribution = field(default_factory=Distribution)
    importance_mean: float = 0.5

    def similarity_threshold(self, sigma: float) -> float:
        return max(-1.0, min(1.0, self.similarity.threshold(sigma)))

    def drift_threshold(self, sigma: float) -> float:
        return max(0.0, min(2.0, self.drift.threshold(sigma)))

    @property
    def has_drift(self) -> bool:
        return self.drift.n >= 10

    def to_dict(self) -> dict:
        return {
            "identity": self.identity,
            "measured_at": self.measured_at,
            "source": self.source,
            "similarity": self.similarity.to_dict(),
            "drift": self.drift.to_dict(),
            "importance_mean": self.importance_mean,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Calibration":
        return cls(
            identity=data.get("identity", ""),
            measured_at=data.get("measured_at", 0.0),
            source=data.get("source", ""),
            similarity=Distribution.from_dict(data.get("similarity", {})),
            drift=Distribution.from_dict(data.get("drift", {})),
            importance_mean=data.get("importance_mean", 0.5),
        )

    def describe(self) -> str:
        lines = [
            f"埋め込み空間: {self.identity}",
            f"測定日時: {to_iso(self.measured_at)}（{self.source}、{self.similarity.n} ペア）",
            "",
            "記憶どうしの類似度:",
            f"  平均 {self.similarity.mean:+.3f} / 標準偏差 {self.similarity.std:.3f}",
            f"  中央値 {self.similarity.p50:+.3f} / 上位10% {self.similarity.p90:+.3f}"
            f" / 上位1% {self.similarity.p99:+.3f}",
        ]
        if self.has_drift:
            lines += [
                "",
                "隣り合うターンのドリフト（話題の変わり具合）:",
                f"  平均 {self.drift.mean:.3f} / 標準偏差 {self.drift.std:.3f}"
                f"（{self.drift.n} ペア）",
            ]
        lines += ["", f"重要度の平均: {self.importance_mean:.3f}"]
        return "\n".join(lines)


def path(config) -> Path:
    return config.soul_dir / "calibration.json"


def save(config, calibration: Calibration) -> Path:
    target = path(config)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(calibration.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return target


def load(config, identity: str = "") -> Calibration | None:
    """保存済みの測定値を読む。

    別のモデルで測った分布は使えない（そのモデルのものさしでしかない）ので、
    identity が食い違うときは「未測定」として扱う。
    """
    target = path(config)
    if not target.exists():
        return None
    try:
        calibration = Calibration.from_dict(json.loads(target.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, TypeError):
        return None
    if identity and calibration.identity != identity:
        return None
    if calibration.similarity.n < 2:
        return None
    return calibration


def measure(app, max_pairs: int = MAX_PAIRS, seed: int | None = None) -> Calibration:
    """このモデルのものさしを実測する。"""
    rng = random.Random(seed)
    texts, source = _sample_texts(app.db)
    embeddings = app.embedder.embed_documents(texts)

    similarities: list[float] = []
    count = len(embeddings)
    total_pairs = count * (count - 1) // 2
    if total_pairs <= max_pairs:
        for left in range(count):
            for right in range(left + 1, count):
                similarities.append(vectors.cosine(embeddings[left], embeddings[right]))
    else:
        for _ in range(max_pairs):
            left, right = rng.sample(range(count), 2)
            similarities.append(vectors.cosine(embeddings[left], embeddings[right]))

    return Calibration(
        identity=app.embedder.identity,
        measured_at=now(),
        source=source,
        similarity=Distribution.of(similarities),
        drift=_measure_drift(app),
        importance_mean=app.db.scalar("SELECT COALESCE(AVG(importance), 0.5) FROM notes") or 0.5,
    )


def _sample_texts(db: Database) -> tuple[list[str], str]:
    stored = notes_store.iter_notes(
        db, states=(notes_store.STATE_ACTIVE, notes_store.STATE_COLD, notes_store.STATE_MERGED)
    )
    if len(stored) >= MIN_NOTES_FOR_SELF_MEASURE:
        return [note.content for note in stored], "notes"
    return list(PROBE_SENTENCES), "probes"


def _measure_drift(app) -> Distribution:
    """隣り合う発話がどれくらい離れるか。話題の切れ目の判定に使う。"""
    rows = app.db.query(
        "SELECT session_id, content FROM events ORDER BY session_id, ts, id LIMIT 400"
    )
    if len(rows) < 11:
        return Distribution()

    embeddings = app.embedder.embed_documents([row["content"] for row in rows])
    drifts: list[float] = []
    for index in range(1, len(rows)):
        if rows[index]["session_id"] != rows[index - 1]["session_id"]:
            continue
        drifts.append(1.0 - vectors.cosine(embeddings[index], embeddings[index - 1]))
    return Distribution.of(drifts)


def recommendations(calibration: Calibration, config) -> list[tuple[str, float, float]]:
    """いまの設定と、測定に基づく実効値を並べる。

    設定ファイルを勝手に書き換えることはしない。数字を見せて、判断は人間に渡す。
    """
    rows = [
        (
            "pipeline.link_min_similarity（σ換算後の実効値）",
            config.pipeline.link_min_similarity,
            calibration.similarity_threshold(config.pipeline.link_min_sigma),
        ),
        (
            "decay.consolidate_similarity（σ換算後の実効値）",
            config.decay.consolidate_similarity,
            calibration.similarity_threshold(config.decay.consolidate_sigma),
        ),
    ]
    if calibration.has_drift:
        rows.append(
            (
                "pipeline.segment_drift（σ換算後の実効値）",
                config.pipeline.segment_drift,
                calibration.drift_threshold(config.pipeline.segment_drift_sigma),
            )
        )
    rows.append(
        (
            "unconscious.reflect_importance_threshold（ノート6件相当）",
            config.unconscious.reflect_importance_threshold,
            round(calibration.importance_mean * 6, 2),
        )
    )
    return rows
