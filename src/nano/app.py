"""アプリケーション組み立て。

各層（記憶ストア / LLM / 埋め込み / 推論ゲート）を1つに束ねる。
CUI も、将来のデーモンも UI も、すべてここを入口にする。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .config import Config, load_config
from .embed import Embedder, HashEmbedder, build_embedder
from .gate import PRIORITY_CHAT, InferenceGate
from .llm import LLM, LlamaServerLLM
from .memory import decay as decay_module
from .memory import pipeline as pipeline_module
from .memory.retrieve import Recall, recall
from .offline import OfflineLLM
from .persona.compose import build_messages
from .store import archive, events as events_store, notes as notes_store, state as state_store
from .store.db import Database
from .store.notes import VectorIndex


@dataclass
class App:
    config: Config
    db: Database
    llm: LLM
    embedder: Embedder
    index: VectorIndex
    gate: InferenceGate

    @classmethod
    def create(cls, config_path: str | None = None, offline: bool = False) -> "App":
        return cls.build(load_config(config_path), offline=offline)

    @classmethod
    def build(cls, config: Config, offline: bool = False) -> "App":
        """Config を直接渡して組み立てる（テストや複数の魂を切り替えるとき用）。"""
        config.ensure_dirs()
        db = Database(config.db_path)
        if offline:
            llm: LLM = OfflineLLM(max_notes=config.pipeline.max_notes_per_episode)
            embedder: Embedder = HashEmbedder(dim=config.embed.dim)
        else:
            llm = LlamaServerLLM(
                base_url=config.llm.base_url,
                model=config.llm.model,
                api_key=config.llm.api_key,
                timeout_s=config.llm.timeout_s,
                temperature=config.llm.temperature,
                max_tokens=config.llm.max_tokens,
            )
            embedder = build_embedder(config.embed)
        index = VectorIndex(db)
        index.load()
        return cls(config=config, db=db, llm=llm, embedder=embedder, index=index, gate=InferenceGate())

    def close(self) -> None:
        for component in (self.llm, self.embedder):
            closer = getattr(component, "close", None)
            if callable(closer):
                closer()
        self.db.close()

    # --- 意識 ---
    def say(
        self,
        user_text: str,
        session_id: str,
        on_token: Callable[[str], None] | None = None,
    ) -> tuple[str, Recall]:
        """1往復。想起 → 生成 → 生ログ記録までを行う。"""
        recent = events_store.recent(self.db, session_id, self.config.retrieval.recent_turns)
        user_event = events_store.append(self.db, session_id, events_store.ROLE_USER, user_text)
        archive.mirror_event(self.config.archive_dir, user_event)

        focus = state_store.get(self.db, state_store.KEY_CURRENT_FOCUS)
        query = f"{user_text}\n{focus}".strip()
        memories = recall(
            self.db,
            self.index,
            self.embedder,
            query,
            self.config.retrieval,
            self.config.decay,
        )

        messages = build_messages(self.config, self.db, user_text, memories, recent)
        # 対話は最優先。背景ジョブが動いていれば、この acquire がそれを中断させる。
        with self.gate.acquire(PRIORITY_CHAT) as cancel:
            answer = self.llm.chat(messages, task="reply", cancel=cancel, on_token=on_token)

        companion_event = events_store.append(
            self.db, session_id, events_store.ROLE_COMPANION, answer
        )
        archive.mirror_event(self.config.archive_dir, companion_event)
        state_store.set_value(
            self.db, state_store.KEY_THREAD, user_text[:200], updated_by="conscious"
        )
        return answer, memories

    # --- 無意識（M1 では手動起動。M2 でデーモンが同じ関数を叩く） ---
    def ingest(self) -> pipeline_module.IngestReport:
        return pipeline_module.ingest_pending(
            self.db, self.llm, self.embedder, self.index, self.config
        )

    def run_decay(self, at: float | None = None) -> decay_module.DecayReport:
        return decay_module.run(
            self.db,
            self.llm,
            self.embedder,
            self.config.decay,
            self.index,
            companion_name=self.config.persona.name,
            at=at,
        )

    # --- 観測 ---
    def stats(self) -> dict:
        db = self.db
        by_state = {
            row["state"]: row["n"]
            for row in db.query("SELECT state, COUNT(*) AS n FROM notes GROUP BY state")
        }
        return {
            "events": db.scalar("SELECT COUNT(*) FROM events") or 0,
            "pending_events": db.scalar("SELECT COUNT(*) FROM events WHERE episode_id IS NULL") or 0,
            "episodes": db.scalar("SELECT COUNT(*) FROM episodes") or 0,
            "notes_active": by_state.get(notes_store.STATE_ACTIVE, 0),
            "notes_cold": by_state.get(notes_store.STATE_COLD, 0),
            "notes_merged": by_state.get(notes_store.STATE_MERGED, 0),
            "links": db.scalar("SELECT COUNT(*) FROM links") or 0,
            "entities": db.scalar("SELECT COUNT(*) FROM entities") or 0,
            "vectors": len(self.index),
            "db_bytes": self.config.db_path.stat().st_size if self.config.db_path.exists() else 0,
        }
