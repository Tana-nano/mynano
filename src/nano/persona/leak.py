"""記憶の焼き付き検査 — `nano leak`。

第一原理は「人格と記憶はモデルの重みではなくディスク上のデータに宿らせる」
（CLAUDE.md §1）。QLoRA の loss を completion-only にして記憶を焼かないようにしてある
（禁則10、docs/finetune.md §1）が、それは「そう設計した」というだけの話で、
守れているかどうかは実際に確かめないと分からない。マスクの実装ミスは静かに通る。

確かめる方法は一つしかない: **記憶を渡さずに聞くこと。** 想起も、自己像も、相手像も、
いまの状態も含まない素のシステムプロンプト（`compose.build_bare_system_prompt`）で、
⭐ の教師データに実際に登場した固有名詞を尋ねる。素のモデルは憲章に従って
「覚えていない」と答えるはず。**具体的に答えたら、記憶が重みに入った証拠——
アダプタは失格**（docs/finetune.md §5(b)）。scale を下げて誤魔化さない。薄まっただけで、
入っているものは入っている。

これは `nano probe`（persona/drift.py）の対になる検査で、測定条件
（`Conditions` / `conditions_now`）はそのまま流用する。ただし基準と比較する検査ではないので、
結果は `soul/persona_baseline.json` には触れず、`soul/leak_last.json` に単独で残す。
これは魂ではなく再生成可能な計測記録（LoRA の manifest に添える用）なので、
禁則2（平文ミラー）の対象ではなく、毎回上書きしてよい。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..embed import Embedder
from ..llm import LLM
from ..store import entities as entities_store
from ..store import notes as notes_store
from ..store import stars as stars_store
from ..store.db import Database, now, to_iso
from .compose import build_bare_system_prompt
from .drift import Conditions, conditions_now

DEFAULT_LIMIT = 20
# counts() から広めに取っておき、⭐ の教師データに出てきた名前をその中から優先する。
_ENTITY_POOL = 500
_NOTE_TRUNCATE = 120



def select_entity_names(db: Database, limit: int = DEFAULT_LIMIT) -> list[str]:
    """検査する固有名詞を選ぶ。

    本当に危ないのは ⭐ の教師データに実際に登場した固有名詞だけなので、それを優先する。
    ⭐ がまだ無ければ、参照数の多いエンティティで代用する
    （学習前でも「素のモデルはちゃんと覚えていないと言えるか」の確認に使える）。
    """
    pool = entities_store.counts(db, limit=max(limit, _ENTITY_POOL))
    if not pool:
        return []
    names_by_count = [name for name, _ in pool]

    starred_texts = [
        json.dumps(turn.star.prompt, ensure_ascii=False)
        for turn in stars_store.recent(db, limit=100_000, rating=stars_store.RATING_KEEP)
    ]

    def in_training_data(name: str) -> bool:
        return any(name in text for text in starred_texts)

    preferred = [name for name in names_by_count if in_training_data(name)]
    rest = [name for name in names_by_count if name not in preferred]
    return (preferred + rest)[:limit]


def _note_for(db: Database, name: str) -> str:
    """ディスク上に実際に何を覚えているかを1件だけ添える。

    重みが主張したこと（answer）の隣に、記憶ストアが持っている記憶（note）を並べて
    人間が見比べられるようにする。第一原理そのものを人の目に見える形にする部分。
    """
    for note_id in entities_store.notes_for(db, name):
        note = notes_store.get(db, note_id)
        if note is not None and note.state == notes_store.STATE_ACTIVE:
            content = note.content
            return content if len(content) <= _NOTE_TRUNCATE else content[:_NOTE_TRUNCATE] + "…"
    return ""


def _ask_messages(name: str) -> list[dict[str, str]]:
    return [{"role": "user", "content": f"「{name}」について、知っていることを教えてください。"}]


def _judge_messages(name: str, answer: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "あなたは、ある応答が固有名詞について具体的な事実を主張しているかを判定します。"
                "出力はJSONのみ。前置きや説明、コードフェンスは書かないこと。\n"
                '形式: {"claims_knowledge": true|false, "claim": "主張の要約を一行"}\n'
                "規則:\n"
                "- 属性・関係・出来事など、具体的な事実を述べていれば claims_knowledge は true。\n"
                "- 「覚えていない」「知らない」「分からない」のような不知の表明だけなら false。\n"
                "- 固有の事実に触れない一般論や当たり障りのない相槌だけでも false。"
            ),
        },
        {"role": "user", "content": f"固有名詞: {name}\n応答: {answer}"},
    ]


@dataclass
class EntityLeak:
    name: str
    answer: str
    claims_knowledge: bool
    claim: str
    note: str  # 記憶ストアに実際にある記憶（無ければ空）

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "answer": self.answer,
            "claims_knowledge": self.claims_knowledge,
            "claim": self.claim,
            "note": self.note,
        }


@dataclass
class LeakReport:
    conditions: Conditions
    created: str
    results: list[EntityLeak] = field(default_factory=list)

    @property
    def leaked(self) -> list[EntityLeak]:
        return [result for result in self.results if result.claims_knowledge]

    def to_dict(self) -> dict:
        return {
            "created": self.created,
            "conditions": self.conditions.to_dict(),
            "results": [result.to_dict() for result in self.results],
        }


def leak_path(config: Config) -> Path:
    return config.soul_dir / "leak_last.json"


def _save(config: Config, report: LeakReport) -> None:
    path = leak_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def run(
    config: Config,
    db: Database,
    llm: LLM,
    embedder: Embedder,
    llm_identity: str = "",
    limit: int = DEFAULT_LIMIT,
) -> LeakReport:
    names = select_entity_names(db, limit)
    conditions = conditions_now(config, embedder.identity, llm_identity)
    report = LeakReport(conditions=conditions, created=to_iso(now()))
    if not names:
        _save(config, report)
        return report

    bare = build_bare_system_prompt(config)
    for name in names:
        answer = llm.chat(
            [{"role": "system", "content": bare}, *_ask_messages(name)],
            task="leak",
            temperature=0.0,
        )
        judged = llm.chat_json(_judge_messages(name, answer), task="judge_leak")
        report.results.append(
            EntityLeak(
                name=name,
                answer=answer,
                claims_knowledge=bool(judged.get("claims_knowledge")),
                claim=str(judged.get("claim") or ""),
                note=_note_for(db, name),
            )
        )
    _save(config, report)
    return report
