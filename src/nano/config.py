"""設定の読み込み。tomllib は標準ライブラリなので依存を増やさない。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any


@dataclass
class PathsConfig:
    soul_dir: str = "soul"


@dataclass
class LLMConfig:
    base_url: str = "http://localhost:8080/v1"
    model: str = "local"
    api_key: str = ""
    timeout_s: float = 300.0
    temperature: float = 0.8
    max_tokens: int = 1024
    background_temperature: float = 0.3
    background_max_tokens: int = 768


@dataclass
class EmbedConfig:
    base_url: str = "http://localhost:8081/v1"
    model: str = "multilingual-e5-large"
    dim: int = 1024
    query_prefix: str = "query: "
    passage_prefix: str = "passage: "
    timeout_s: float = 120.0


@dataclass
class RetrievalConfig:
    w_sim: float = 1.0
    w_imp: float = 0.35
    w_rec: float = 0.45
    w_con: float = 0.15
    candidates: int = 30
    top_k: int = 8
    graph_hops: int = 1
    graph_fanout: int = 2
    mmr_lambda: float = 0.7
    recent_turns: int = 12


@dataclass
class DecayConfig:
    base_half_life_days: float = 2.0
    max_half_life_days: float = 3650.0
    recall_gain: float = 0.8
    # 半減期 = base * (1 + span * importance^2)。重要度を二乗で効かせるのは、
    # 「妹の名前」と「今日の昼食」の寿命が桁で違うべきだから。
    importance_span: float = 200.0
    cold_threshold: float = 0.05
    consolidate_similarity: float = 0.82
    consolidate_min_cluster: int = 3


@dataclass
class PipelineConfig:
    segment_gap_minutes: float = 45.0
    segment_drift: float = 0.55
    link_top_k: int = 8
    link_min_similarity: float = 0.32
    link_judge_budget: int = 6
    max_notes_per_episode: int = 12
    min_segment_events: int = 6
    max_segment_events: int = 24


@dataclass
class UnconsciousConfig:
    enabled: bool = True
    tick_seconds: float = 20.0
    # 最後の発話からこれだけ経ったら「アイドル」。連想や忘却はアイドル時にだけ動く。
    idle_seconds: float = 90.0
    write_delay_seconds: float = 30.0
    associate_interval_minutes: float = 15.0
    reflect_interval_minutes: float = 30.0
    # 前回の reflection 以降に積み上がった重要度がこれを超えたら発火（Generative Agents 方式）
    reflect_importance_threshold: float = 3.0
    decay_interval_hours: float = 24.0
    curate_interval_hours: float = 168.0
    ingest_interval_minutes: float = 10.0
    inbox_dir: str = "inbox"
    lease_ttl_seconds: float = 10.0
    stale_job_seconds: float = 600.0
    max_job_attempts: int = 3
    job_retry_seconds: float = 300.0
    associate_sample: int = 3


@dataclass
class PersonaConfig:
    name: str = "nano"
    constitution_path: str = "persona/constitution.md"
    probes_path: str = "persona/probes.yaml"


@dataclass
class Config:
    root: Path = field(default_factory=Path.cwd)
    paths: PathsConfig = field(default_factory=PathsConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    embed: EmbedConfig = field(default_factory=EmbedConfig)
    retrieval: RetrievalConfig = field(default_factory=RetrievalConfig)
    decay: DecayConfig = field(default_factory=DecayConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    unconscious: UnconsciousConfig = field(default_factory=UnconsciousConfig)
    persona: PersonaConfig = field(default_factory=PersonaConfig)

    # --- 派生パス。魂ディレクトリ配下は「これ一式で全て」になるよう閉じている ---
    @property
    def soul_dir(self) -> Path:
        return self._resolve(self.paths.soul_dir)

    @property
    def db_path(self) -> Path:
        return self.soul_dir / "soul.db"

    @property
    def archive_dir(self) -> Path:
        """生ログの JSONL ミラー。コードが滅びてもこれだけは読める。"""
        return self.soul_dir / "archive"

    @property
    def export_dir(self) -> Path:
        """ノートの Markdown 書き出し先。他のAIに食わせるための可搬形式。"""
        return self.soul_dir / "export"

    @property
    def backup_dir(self) -> Path:
        return self.soul_dir / "backup"

    @property
    def inbox_dir(self) -> Path:
        """外界からの取り込み口。ここに置いたファイルを無意識が記憶にする。"""
        return self.soul_dir / self.unconscious.inbox_dir

    @property
    def constitution_path(self) -> Path:
        return self._resolve(self.persona.constitution_path)

    @property
    def probes_path(self) -> Path:
        return self._resolve(self.persona.probes_path)

    def _resolve(self, value: str) -> Path:
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.root / path

    def ensure_dirs(self) -> None:
        for directory in (
            self.soul_dir,
            self.archive_dir,
            self.export_dir,
            self.backup_dir,
            self.inbox_dir,
            self.inbox_dir / "processed",
        ):
            directory.mkdir(parents=True, exist_ok=True)


def _build(cls: type, data: dict[str, Any]) -> Any:
    """未知キーは無視する。設定ファイルが未来の版で増えても古いコードが動くように。"""
    known = {f.name for f in fields(cls) if is_dataclass(cls)}
    return cls(**{k: v for k, v in data.items() if k in known})


def load_config(path: str | Path | None = None) -> Config:
    """config.toml を読む。見つからなければ既定値。"""
    if path is None:
        candidate = Path.cwd() / "config.toml"
        path = candidate if candidate.exists() else None
    if path is None:
        return Config()

    path = Path(path)
    with path.open("rb") as handle:
        raw = tomllib.load(handle)

    return Config(
        root=path.parent.resolve(),
        paths=_build(PathsConfig, raw.get("paths", {})),
        llm=_build(LLMConfig, raw.get("llm", {})),
        embed=_build(EmbedConfig, raw.get("embed", {})),
        retrieval=_build(RetrievalConfig, raw.get("retrieval", {})),
        decay=_build(DecayConfig, raw.get("decay", {})),
        pipeline=_build(PipelineConfig, raw.get("pipeline", {})),
        unconscious=_build(UnconsciousConfig, raw.get("unconscious", {})),
        persona=_build(PersonaConfig, raw.get("persona", {})),
    )
