"""人格ドリフトの計測。

固定質問に答えさせ、基準応答との埋め込み距離を見る。
初回実行が基準（baseline）になり、以後モデルやプロンプトを変えるたびに
「別人になっていないか」を数値で確かめる。

これがあるから「人格が固定されている」と言い切れる。無ければただの願望になる。

## 基準には「どのものさしで測ったか」を必ず添える

応答を埋め込んだベクトルどうしを比べるので、**埋め込みモデルが違えば数字は無意味**になる。
にもかかわらず次元さえ合っていればコサインは「それらしい数字」を返す
（`HashEmbedder` も `ServerEmbedder` も既定 1024 次元なので、実際に衝突する）。
記憶ストア側は `store/identity.py` と `calibration.py` がこれを塞いでいるが、
人格の基準にだけ同じ防御が無かった。ここで揃える（禁則6）。

測定条件のうち、**埋め込み空間だけが「比較の可否」を決める**。
LLM・LoRA アダプタ・憲章の変更は比較を壊さない。それどころか、
それらを取り替えたときのずれを見ることこそが `nano probe` の用途なので、
止めずに「何が変わった上での数字か」を添えて出す。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

from .. import vectors
from ..config import Config
from ..embed import Embedder
from ..llm import LLM
from ..store.db import Database, now, to_iso
from .compose import build_system_prompt, load_constitution
from .probes import Probe, load

# 1 = 測定条件を記録していなかった頃の形式（素の {probe_id: {...}} の辞書）
BASELINE_VERSION = 2


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


@dataclass
class Conditions:
    """基準を取ったときの測定条件。

    これが無い基準は「何と比べているのか分からない数字」しか出せない。
    """

    embedding: str = ""  # 埋め込み空間の同一性。ここだけが比較の可否を決める
    llm: str = ""  # 対話モデル
    adapter: str = ""  # LoRA アダプタの名札（人間が config に書く。§docs/finetune.md）
    constitution: str = ""  # 憲章のハッシュ
    probes: str = ""  # プローブ集合のハッシュ

    def to_dict(self) -> dict:
        return {
            "embedding": self.embedding,
            "llm": self.llm,
            "adapter": self.adapter,
            "constitution": self.constitution,
            "probes": self.probes,
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> "Conditions":
        data = data or {}
        return cls(
            embedding=data.get("embedding", ""),
            llm=data.get("llm", ""),
            adapter=data.get("adapter", ""),
            constitution=data.get("constitution", ""),
            probes=data.get("probes", ""),
        )

    def changes_from(self, other: "Conditions") -> list[str]:
        """前回の測定条件との差分を、人間が読める形で並べる。

        比較を止めはしない。「何を変えた上でのずれか」が分からないと、
        出てきた数字をどう解釈すればいいか決められないので、必ず添えて出す。
        """
        labels = [
            ("llm", "対話モデル"),
            ("adapter", "LoRA アダプタ"),
            ("constitution", "憲章"),
            ("probes", "プローブ"),
        ]
        changes = []
        for key, label in labels:
            before = getattr(other, key)
            after = getattr(self, key)
            if before == after:
                continue
            changes.append(f"{label}: {before or '（なし）'} → {after or '（なし）'}")
        return changes


def conditions_now(config: Config, embedding_identity: str, llm_identity: str) -> Conditions:
    probes = load(config.probes_path)
    return Conditions(
        embedding=embedding_identity,
        llm=llm_identity,
        adapter=config.llm.adapter,
        constitution=_digest(load_constitution(config)),
        probes=_digest("\n".join(f"{p.id}:{p.prompt}" for p in probes)),
    )


@dataclass
class Baseline:
    conditions: Conditions
    entries: dict[str, dict]  # probe_id -> {answer, vector, ts}
    version: int = BASELINE_VERSION
    created: str = ""

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "created": self.created,
            "conditions": self.conditions.to_dict(),
            "entries": self.entries,
        }


def baseline_path(config: Config) -> Path:
    return config.soul_dir / "persona_baseline.json"


def load_baseline(config: Config) -> Baseline | None:
    path = baseline_path(config)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if "entries" not in data:
        # 版1: 測定条件を記録していない。条件不明として読み、比較は断る。
        return Baseline(conditions=Conditions(), entries=data, version=1, created="")
    return Baseline(
        conditions=Conditions.from_dict(data.get("conditions")),
        entries=data.get("entries", {}),
        version=int(data.get("version", BASELINE_VERSION)),
        created=data.get("created", ""),
    )


def comparability(baseline: Baseline | None, current: Conditions) -> str:
    """比較できない理由を返す。比較できるなら空文字。

    止めるのは埋め込み空間の食い違いだけ。ここを黙って通すと、
    別々の空間のベクトルを cos にかけた数字が「人格のずれ」として表示され、
    それを見て学習の可否を決めることになる。
    """
    if baseline is None:
        return "基準がまだありません"
    if baseline.version < BASELINE_VERSION or not baseline.conditions.embedding:
        return (
            "この基準には測定条件が記録されていません（古い形式）。\n"
            "  どの埋め込みモデルで取ったか分からないので、いまの応答と比べても意味がありません。\n"
            "  取り直してください:  nano probe --save-baseline"
        )
    if current.embedding and baseline.conditions.embedding != current.embedding:
        # 呼び出し側が空を渡したときは埋め込みの照合を飛ばす（calibration.load と同じ約束）。
        # 実際の経路（nano probe / nano dataset）は必ず名乗るので、歯止めは効いたままになる。
        return (
            f"基準と埋め込みモデルが違います。\n"
            f"  基準を取ったとき: {baseline.conditions.embedding}\n"
            f"  いま:             {current.embedding}\n"
            f"  応答を埋め込んだベクトルどうしを比べているので、空間が違えば数字は無意味です。\n"
            f"  いまのモデルで取り直してください:  nano probe --save-baseline"
        )
    return ""


def usable_baseline(config: Config, embedding_identity: str) -> str:
    """「いまの構成で比較に使える基準があるか」。無ければ理由を返す。

    `nano dataset` の歯止めがここを見る。ファイルの有無だけを見ていた頃は、
    `--offline` で取ったハッシュ埋め込みの基準でも歯止めを通り抜けていた。
    """
    baseline = load_baseline(config)
    current = Conditions(embedding=embedding_identity)
    return comparability(baseline, current)


@dataclass
class ProbeResult:
    probe: Probe
    answer: str
    similarity: float | None  # 基準が無い / 比較できないときは None


@dataclass
class DriftReport:
    results: list[ProbeResult]
    baseline_created: bool
    conditions: Conditions = field(default_factory=Conditions)
    baseline_conditions: Conditions | None = None
    incomparable: str = ""  # 比較できなかった理由（できたなら空文字）
    changes: list[str] = field(default_factory=list)  # 測定条件の差分
    missing_probes: int = 0  # 基準に無かった質問（プローブを増やした場合）

    @property
    def mean_similarity(self) -> float | None:
        scores = [r.similarity for r in self.results if r.similarity is not None]
        return sum(scores) / len(scores) if scores else None

    def worst(self, count: int = 5) -> list[ProbeResult]:
        scored = [r for r in self.results if r.similarity is not None]
        return sorted(scored, key=lambda r: r.similarity or 0.0)[:count]


def run(
    config: Config,
    db: Database,
    llm: LLM,
    embedder: Embedder,
    save_baseline: bool = False,
    llm_identity: str = "",
) -> DriftReport:
    probes = load(config.probes_path)
    if not probes:
        return DriftReport(results=[], baseline_created=False)

    current = conditions_now(config, embedder.identity, llm_identity)
    baseline = load_baseline(config)
    incomparable = comparability(baseline, current)
    entries = baseline.entries if (baseline and not incomparable) else {}

    system = build_system_prompt(config, db, recall=None)

    results: list[ProbeResult] = []
    fresh: dict[str, dict] = {}
    missing = 0
    for probe in probes:
        answer = llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": probe.prompt}],
            task="probe",
            temperature=0.0,
        )
        vector = embedder.embed_query(answer)
        similarity = None
        if probe.id in entries:
            similarity = vectors.cosine(vector, entries[probe.id]["vector"])
        elif entries:
            # 基準を取ったあとで増やした質問。比較対象が無いだけで、異常ではない。
            missing += 1
        results.append(ProbeResult(probe, answer, similarity))
        fresh[probe.id] = {"answer": answer, "vector": vector, "ts": now()}

    created = False
    # 比較できない基準は、放っておくと次回も同じ理由で比較できない。
    # ただし黙って上書きはしない（人間が --save-baseline を押したときだけ）。
    if save_baseline or baseline is None:
        path = baseline_path(config)
        path.parent.mkdir(parents=True, exist_ok=True)
        written = Baseline(conditions=current, entries=fresh, created=to_iso(now()))
        path.write_text(json.dumps(written.to_dict(), ensure_ascii=False), encoding="utf-8")
        created = True

    return DriftReport(
        results=results,
        baseline_created=created,
        conditions=current,
        baseline_conditions=baseline.conditions if baseline else None,
        incomparable=incomparable if baseline is not None else "",
        changes=current.changes_from(baseline.conditions) if (baseline and not incomparable) else [],
        missing_probes=missing,
    )
