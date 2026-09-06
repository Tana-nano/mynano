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
class Pair:
    """ORPO の1件。同じプロンプトに対する ⭐ と ✗ の対。

    `/again`（同じ messages で応答を出し直す）を通ると自然に貯まる。
    プロンプトが1バイトでも違えば対にしない。違うものを比べても、
    モデルが学ぶのは「応答の良し悪し」ではなく「プロンプトの差」になる。
    """

    prompt: list[dict[str, str]]
    chosen: str
    rejected: str

    def to_dict(self) -> dict:
        return {"prompt": self.prompt, "chosen": self.chosen, "rejected": self.rejected}


@dataclass
class Dataset:
    keep: list[Sample] = field(default_factory=list)
    avoid: list[Sample] = field(default_factory=list)
    pairs: list[Pair] = field(default_factory=list)
    skipped: int = 0  # プロンプトが残っていない ⭐（古い版で付いたものなど）

    def __str__(self) -> str:
        parts = [
            f"教師データ {len(self.keep)} 件",
            f"避けたい応答 {len(self.avoid)} 件",
            f"ORPO の対 {len(self.pairs)} 件",
        ]
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
    dataset.pairs = _pair_up(dataset.keep, dataset.avoid)
    return dataset


def _prompt_key(sample: Sample) -> str:
    """プロンプトの同一性。messages を丸ごと正規化して比べる。"""
    return json.dumps(sample.messages[:-1], ensure_ascii=False, sort_keys=True)


def _pair_up(keep: list[Sample], avoid: list[Sample]) -> list[Pair]:
    """同じプロンプトを共有する ⭐ と ✗ を対にする。

    `/again` で出し直すと、2つ目以降は前回と同じ messages で生成されるので、
    ここが噛み合う。⭐ も ✗ も付いていない普通の会話は当然どこにも入らない。
    """
    avoid_by_prompt: dict[str, list[Sample]] = {}
    for sample in avoid:
        avoid_by_prompt.setdefault(_prompt_key(sample), []).append(sample)

    pairs: list[Pair] = []
    for chosen in keep:
        for rejected in avoid_by_prompt.get(_prompt_key(chosen), []):
            if chosen.messages[-1]["content"] == rejected.messages[-1]["content"]:
                # 一字一句同じものを「良い/悪い」として並べても学習の材料にならない
                # （温度0で出し直すとこうなる）。対にせず捨てる。
                continue
            pairs.append(
                Pair(
                    prompt=chosen.messages[:-1],
                    chosen=chosen.messages[-1]["content"],
                    rejected=rejected.messages[-1]["content"],
                )
            )
    return pairs


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
    with (target / "orpo.jsonl").open("w", encoding="utf-8") as handle:
        for pair in dataset.pairs:
            handle.write(json.dumps(pair.to_dict(), ensure_ascii=False) + "\n")

    manifest = {
        "created": to_iso(now()),
        "persona": config.persona.name,
        "embedding": embedding_identity,
        "baseline": baseline_path(config).exists(),
        "counts": {
            "sft": len(dataset.keep),
            "avoid": len(dataset.avoid),
            "orpo_pairs": len(dataset.pairs),
            "skipped_no_prompt": dataset.skipped,
        },
        "format": (
            "1行 = {messages: [...], meta: {...}}。messages は生成時に実際に渡したものへ "
            "assistant の応答を足した形。system プロンプトには、そのとき想起していた記憶が "
            "そのまま入っている（組み直していない）。"
        ),
        "note": (
            "orpo.jsonl は {prompt, chosen, rejected}。プロンプトが完全に一致する "
            "⭐ と ✗ の対だけが入る（chat の /again で出し直すと貯まる）。"
            "avoid.jsonl のうち対にならなかったものは、同じプロンプトに対する悪い応答では"
            "ないので ORPO には使えない。数が足りなければ、同じ system+user を素の"
            "ベースモデル（憲章なし）に投げて rejected を生成して足すのが素直。"
        ),
    }
    (target / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return target, dataset
