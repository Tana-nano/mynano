"""アプリケーション組み立て。

各層（記憶ストア / LLM / 埋め込み / 推論ゲート）を1つに束ねる。
CUI も、将来のデーモンも UI も、すべてここを入口にする。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable

from . import calibration as calibration_module
from .config import Config, load_config
from .embed import Embedder, HashEmbedder, build_embedder
from .gate import PRIORITY_CHAT, SharedInferenceGate
from .llm import LLM, LlamaServerLLM
from .memory import decay as decay_module
from .memory import pipeline as pipeline_module
from .memory.retrieve import Recall, recall
from .offline import OfflineLLM
from .persona.compose import build_messages
from .store import archive, events as events_store, identity as identity_store
from .store import notes as notes_store, stars as stars_store, state as state_store
from .store.db import Database
from .store.notes import VectorIndex


# 直近の往復をいくつ覚えておくか。⭐ は「その場で付ける」ものなので深い履歴は要らない。
MAX_EXCHANGES = 64


@dataclass
class Exchange:
    """1往復ぶんの「本当に起きたこと」。

    ⭐ を付けるときに要るのは応答だけではなく、それを生んだプロンプトそのもの。
    あとから組み直すと想起される記憶が変わっていて、別のプロンプトになってしまう。
    だから生成したその場で、渡した messages を丸ごと抱えておく。
    """

    session_id: str
    user_event_id: int
    companion_event_id: int
    user_text: str
    answer: str
    messages: list[dict[str, str]]


@dataclass
class App:
    config: Config
    db: Database
    llm: LLM
    embedder: Embedder
    index: VectorIndex
    gate: SharedInferenceGate
    # そのモデルのものさし。未測定なら None で、設定の絶対値にそのまま落ちる。
    calibration: object | None = None
    # このプロセスが生んだ往復。⭐ の対象はここからしか取らない（後述の star()）。
    exchanges: list[Exchange] = field(default_factory=list)

    @classmethod
    def create(
        cls,
        config_path: str | None = None,
        offline: bool = False,
        holder: str = "",
        allow_new_embedder: bool = False,
    ) -> "App":
        return cls.build(
            load_config(config_path),
            offline=offline,
            holder=holder,
            allow_new_embedder=allow_new_embedder,
        )

    @classmethod
    def build(
        cls,
        config: Config,
        offline: bool = False,
        holder: str = "",
        allow_new_embedder: bool = False,
    ) -> "App":
        """Config を直接渡して組み立てる（テストや複数の魂を切り替えるとき用）。

        allow_new_embedder は `nano reembed` 専用の抜け道。
        それ以外の経路では、埋め込みモデルが変わっていたら起動を止める。
        """
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

        # 別のモデルで作ったベクトルと混ぜない。混ざると想起が静かに壊れる。
        if not allow_new_embedder:
            try:
                identity_store.check(db, embedder.identity)
            except identity_store.EmbeddingMismatch:
                db.close()
                raise

        index = VectorIndex(db)
        index.load()
        # ゲートはプロセスをまたぐ。対話とデーモンが別プロセスでも譲り合えるように。
        gate = SharedInferenceGate(
            config.db_path,
            holder=f"{holder or 'nano'}:{os.getpid()}",
            ttl_s=config.unconscious.lease_ttl_seconds,
        )
        return cls(
            config=config,
            db=db,
            llm=llm,
            embedder=embedder,
            index=index,
            gate=gate,
            calibration=calibration_module.load(config, embedder.identity),
        )

    def close(self) -> None:
        for component in (self.llm, self.embedder, self.gate):
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
        self.exchanges.append(
            Exchange(
                session_id=session_id,
                user_event_id=user_event.id,
                companion_event_id=companion_event.id,
                user_text=user_text,
                answer=answer,
                messages=messages,
            )
        )
        del self.exchanges[:-MAX_EXCHANGES]
        return answer, memories

    # --- ⭐（M4: 人格の固定の材料集め） ---
    def star(
        self,
        back: int = 1,
        rating: int = stars_store.RATING_KEEP,
        reason: str = "",
    ) -> Exchange:
        """直近から back 番目の応答に印を付ける。

        この会話の中の応答にしか付けられない。過去ログを遡って付けられるようにすると、
        そのとき渡したプロンプトが復元できないまま教師データに混ざる。
        「モデルが見ていない材料から答えを出す」訓練になるので、構造的に塞いでおく。
        """
        exchange = self._exchange(back)
        star = stars_store.put(
            self.db,
            exchange.companion_event_id,
            rating=rating,
            prompt=exchange.messages,
            reason=reason,
        )
        archive.mirror_star(
            self.config.archive_dir,
            action="star" if rating > 0 else "avoid",
            event_id=exchange.companion_event_id,
            session_id=exchange.session_id,
            user_text=exchange.user_text,
            answer=exchange.answer,
            rating=star.rating,
            reason=reason,
            prompt=exchange.messages,
            ts=star.updated_at,
        )
        return exchange

    def unstar(self, back: int = 1) -> Exchange | None:
        exchange = self._exchange(back)
        if not stars_store.remove(self.db, exchange.companion_event_id):
            return None
        archive.mirror_star(
            self.config.archive_dir,
            action="unstar",
            event_id=exchange.companion_event_id,
            session_id=exchange.session_id,
            user_text=exchange.user_text,
            answer=exchange.answer,
        )
        return exchange

    def _exchange(self, back: int) -> Exchange:
        if back < 1 or back > len(self.exchanges):
            raise IndexError(
                f"この会話にはまだ {len(self.exchanges)} 往復しかありません。"
                "⭐ はいま話している応答にだけ付けられます。"
            )
        return self.exchanges[-back]

    # --- 無意識（M1 では手動起動。M2 でデーモンが同じ関数を叩く） ---
    def ingest(self) -> pipeline_module.IngestReport:
        return pipeline_module.ingest_pending(
            self.db, self.llm, self.embedder, self.index, self.config, calibration=self.calibration
        )

    def reload_calibration(self) -> None:
        self.calibration = calibration_module.load(self.config, self.embedder.identity)

    def run_decay(self, at: float | None = None) -> decay_module.DecayReport:
        return decay_module.run(
            self.db,
            self.llm,
            self.embedder,
            self.config.decay,
            self.index,
            companion_name=self.config.persona.name,
            at=at,
            calibration=self.calibration,
        )

    # --- 観測 ---
    def stats(self) -> dict:
        db = self.db
        star_counts = stars_store.counts(db)
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
            # 密度の一次指標。実測では、しきい値より上限のほうがここを支配する。
            # 10本を超えていたらリンクが緩すぎる（グラフが何も語らなくなる）。
            "links_per_note": round(
                (db.scalar("SELECT COUNT(*) FROM links WHERE relation != 'temporal_next'") or 0)
                / max(1, db.scalar("SELECT COUNT(*) FROM notes") or 1),
                1,
            ),
            "entities": db.scalar("SELECT COUNT(*) FROM entities") or 0,
            # M4 の燃料。⭐ が貯まるまで QLoRA は始められない。
            "starred": star_counts["keep"],
            "avoided": star_counts["avoid"],
            "vectors": len(self.index),
            "embedding": identity_store.recorded(db) or self.embedder.identity,
            "db_bytes": self.config.db_path.stat().st_size if self.config.db_path.exists() else 0,
        }
