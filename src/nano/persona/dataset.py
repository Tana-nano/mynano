"""⭐ から QLoRA の教師データを組み立てる。

M4 の 1→2 をつなぐ部分。ここで守っているのは3つだけ。

1. **⭐ が付いたものしか出さない。** 会話ログ全体を流し込むと、こちらの相槌も
   モデルの失敗も等しく学習される。人格を固定したいのに、平均に均される。
2. **プロンプトは組み直さない。** ⭐ を押した瞬間に渡していた messages をそのまま使う。
   いま組み直すと想起される記憶が変わっていて、モデルが見ていない材料から
   答えを出す訓練＝幻覚の訓練になる。
3. **計測が先。** 人格ベースライン（nano probe）が無いうちは書き出しを止める。
   学習後に「別人になっていないか」を測れないなら、学習してはいけない。

出力は素の JSONL。特定の学習フレームワークに合わせない（依存の寿命の問題。禁則3）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..store import stars as stars_store
from ..store.db import Database, now, to_iso
from .drift import baseline_path


class BaselineMissing(RuntimeError):
    """人格の基準がまだ無い。学習の前に計測する（順番を逆にすると壊れても気づけない）。"""


@dataclass
class Sample:
    messages: list[dict[str, str]]  # 末尾が assistant = ⭐ の付いた応答
    event_id: int
    session_id: str
    time: str
    reason: str

    def to_dict(self) -> dict:
        return {
            "messages": self.messages,
            "meta": {
                "event_id": self.event_id,
                "session_id": self.session_id,
                "time": self.time,
                "reason": self.reason,
            },
        }


@dataclass
class Dataset:
    keep: list[Sample] = field(default_factory=list)
    avoid: list[Sample] = field(default_factory=list)
    skipped: int = 0  # プロンプトが残っていない ⭐（古い版で付いたものなど）

    def __str__(self) -> str:
        parts = [f"教師データ {len(self.keep)} 件", f"避けたい応答 {len(self.avoid)} 件"]
        if self.skipped:
            parts.append(f"プロンプト欠落のため除外 {self.skipped} 件")
        return " / ".join(parts)


def build(db: Database, limit: int = 100_000) -> Dataset:
    dataset = Dataset()
    for turn in stars_store.recent(db, limit=limit):
        if not turn.star.prompt:
            # 対になるプロンプトが無い ⭐ は教師データにしない（上の 2 の理由）
            dataset.skipped += 1
            continue
        sample = Sample(
            messages=list(turn.star.prompt) + [{"role": "assistant", "content": turn.answer}],
            event_id=turn.star.event_id,
            session_id=turn.session_id,
            time=to_iso(turn.ts),
            reason=turn.star.reason,
        )
        bucket = dataset.keep if turn.star.rating > 0 else dataset.avoid
        bucket.append(sample)
    # 古い順に。学習時に時系列で切りたくなることがある。
    dataset.keep.reverse()
    dataset.avoid.reverse()
    return dataset


def _write_jsonl(path: Path, samples: list[Sample]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(json.dumps(sample.to_dict(), ensure_ascii=False) + "\n")


def export(
    config: Config,
    db: Database,
    embedding_identity: str = "",
    force: bool = False,
) -> tuple[Path, Dataset]:
    """soul/export/train/ に書き出す。魂ディレクトリの外には出さない。"""
    if not baseline_path(config).exists() and not force:
        raise BaselineMissing(
            "人格のベースラインがありません。学習の前に計測してください:\n"
            "    nano probe --save-baseline\n"
            "（学習後に「別人になっていないか」を測る基準です。"
            "順番を逆にすると、人格が壊れたことに気づけません）"
        )

    dataset = build(db)
    target = config.export_dir / "train"
    target.mkdir(parents=True, exist_ok=True)
    _write_jsonl(target / "sft.jsonl", dataset.keep)
    _write_jsonl(target / "avoid.jsonl", dataset.avoid)

    manifest = {
        "created": to_iso(now()),
        "persona": config.persona.name,
        "embedding": embedding_identity,
        "baseline": baseline_path(config).exists(),
        "counts": {
            "sft": len(dataset.keep),
            "avoid": len(dataset.avoid),
            "skipped_no_prompt": dataset.skipped,
        },
        "format": (
            "1行 = {messages: [...], meta: {...}}。messages は生成時に実際に渡したものへ "
            "assistant の応答を足した形。system プロンプトには、そのとき想起していた記憶が "
            "そのまま入っている（組み直していない）。"
        ),
        "note": (
            "ORPO で使うなら rejected 側が要る。avoid.jsonl は「同じプロンプトに対する"
            "悪い応答」ではないので、そのままでは対にならない。学習時に、同じ system+user を"
            "素のベースモデル（憲章なし）に投げて rejected を生成するのが素直。"
        ),
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target, dataset
