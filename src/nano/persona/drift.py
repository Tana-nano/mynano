"""人格ドリフトの計測。

固定質問に答えさせ、基準応答との埋め込み距離を見る。
初回実行が基準（baseline）になり、以後モデルやプロンプトを変えるたびに
「別人になっていないか」を数値で確かめる。

これがあるから「人格が固定されている」と言い切れる。無ければただの願望になる。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .. import vectors
from ..config import Config
from ..embed import Embedder
from ..llm import LLM
from ..store.db import Database, now
from .compose import build_system_prompt
from .probes import Probe, load


@dataclass
class ProbeResult:
    probe: Probe
    answer: str
    similarity: float | None  # 基準が無い初回は None


@dataclass
class DriftReport:
    results: list[ProbeResult]
    baseline_created: bool

    @property
    def mean_similarity(self) -> float | None:
        scores = [r.similarity for r in self.results if r.similarity is not None]
        return sum(scores) / len(scores) if scores else None

    def worst(self, count: int = 5) -> list[ProbeResult]:
        scored = [r for r in self.results if r.similarity is not None]
        return sorted(scored, key=lambda r: r.similarity or 0.0)[:count]


def baseline_path(config: Config) -> Path:
    return config.soul_dir / "persona_baseline.json"


def run(
    config: Config,
    db: Database,
    llm: LLM,
    embedder: Embedder,
    save_baseline: bool = False,
) -> DriftReport:
    probes = load(config.probes_path)
    if not probes:
        return DriftReport(results=[], baseline_created=False)

    path = baseline_path(config)
    baseline = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    system = build_system_prompt(config, db, recall=None)

    results: list[ProbeResult] = []
    fresh: dict[str, dict] = {}
    for probe in probes:
        answer = llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": probe.prompt}],
            task="probe",
            temperature=0.0,
        )
        vector = embedder.embed_query(answer)
        similarity = None
        if probe.id in baseline:
            similarity = vectors.cosine(vector, baseline[probe.id]["vector"])
        results.append(ProbeResult(probe, answer, similarity))
        fresh[probe.id] = {"answer": answer, "vector": vector, "ts": now()}

    created = False
    if save_baseline or not baseline:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(fresh, ensure_ascii=False), encoding="utf-8")
        created = True
    return DriftReport(results=results, baseline_created=created)
