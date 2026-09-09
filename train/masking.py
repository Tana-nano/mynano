"""completion-only loss のための境界計算。torch も transformers も要らない部分。

禁則10: 記憶を重みに焼かない。⭐ の system プロンプトには想起された記憶が本文のまま
入っているので、プロンプト側のトークンには loss をかけない。

ここを別ファイルにしてあるのは、**マスクの間違いは静かに通る**から。
学習は普通に走り、loss も下がり、あとで「妹の名前」を重みが覚えている。
だからこの境界計算だけは nano のテスト（オフライン）で検査できるようにしてある。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

IGNORE = -100  # HF の Trainer が loss から外すラベル値


class MaskError(ValueError):
    """プロンプトと全文のトークン列が前置一致しない。トークナイザの境界の問題。"""


@dataclass
class Encoded:
    input_ids: list[int]
    labels: list[int]

    @property
    def answer_tokens(self) -> int:
        return sum(1 for label in self.labels if label != IGNORE)


def split_prompt_and_answer(prompt_ids: Sequence[int], full_ids: Sequence[int]) -> Encoded:
    """prompt_ids が full_ids の前置になっていることを確かめ、前置部分を IGNORE で潰す。

    prompt_ids = chat_template(messages[:-1], add_generation_prompt=True)
    full_ids   = chat_template(messages)
    のつもりで呼ぶ。前置一致しないなら、テンプレートかトークナイザの境界が
    こちらの想定と違うということなので、黙って続けずに止める。
    """
    prompt_ids = list(prompt_ids)
    full_ids = list(full_ids)
    cut = len(prompt_ids)
    if cut == 0:
        raise MaskError("prompt が空です")
    if cut >= len(full_ids):
        raise MaskError(f"prompt ({cut}) が全文 ({len(full_ids)}) 以上の長さです。応答が空か切れています")
    if full_ids[:cut] != prompt_ids:
        # どこで食い違ったかを出す。だいたいは末尾の数トークン（generation prompt の扱い）。
        first_bad = next(i for i in range(cut) if full_ids[i] != prompt_ids[i])
        raise MaskError(
            f"prompt と全文が {first_bad} トークン目で食い違っています "
            f"(prompt={prompt_ids[max(0, first_bad - 3):first_bad + 3]}, "
            f"full={full_ids[max(0, first_bad - 3):first_bad + 3]})"
        )
    labels = [IGNORE] * cut + full_ids[cut:]
    return Encoded(input_ids=full_ids, labels=labels)


def fits(encoded: Encoded, max_seq_len: int) -> bool:
    """長さ上限に収まるか。**収まらないものは切らずに行ごと落とす**。

    末尾で切ると assistant 側が消えて、loss の対象が無いサンプルが混ざる。
    completion-only なので、それは「静かに学習していない行」になる。
    """
    return len(encoded.input_ids) <= max_seq_len


def generation_of(meta: dict) -> str:
    """dataset.py の Sample.generation と同じ規則。model+adapter。"""
    model = str(meta.get("model", "") or "")
    adapter = str(meta.get("adapter", "") or "")
    return f"{model}+{adapter}" if adapter else model
