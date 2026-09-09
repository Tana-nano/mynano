"""nano dataset の出力を、学習に渡せる形に整える。標準ライブラリだけで動く。

    python train/prepare.py --soul soul --tokenizer Qwen/Qwen3-8B --max-seq-len 4096

やること:
1. `soul/export/train/{sft,orpo}.jsonl` を読む
2. 世代（どのモデル/アダプタが出した応答への ⭐ か）の内訳を出す
3. トークン長を測り、上限に収まらない行を**切らずに落とす**（落とした数を出す）
4. `train/work/` に書き出し、統計を `prepare.json` に残す

トークナイザは transformers があれば使う。無ければ `--dry` で内訳だけ見られる。
長さの判定はトークナイザ無しではできないので、無い状態で書き出しはしない
（文字数からの推定で通すと、実際には収まらない行が混ざって学習で落ちる）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from masking import fits, generation_of, split_prompt_and_answer  # noqa: E402


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16] if path.exists() else ""


def load_tokenizer(name: str | None):
    if not name:
        return None
    from transformers import AutoTokenizer  # 別 venv にしか無い。nano には入れない

    return AutoTokenizer.from_pretrained(name)


def encode_sft(tokenizer, messages: list[dict]):
    """chat template を通し、prompt 部分と全文の前置一致を確かめて境界を出す。"""
    prompt_ids = tokenizer.apply_chat_template(
        messages[:-1], add_generation_prompt=True, tokenize=True
    )
    full_ids = tokenizer.apply_chat_template(messages, tokenize=True)
    return split_prompt_and_answer(prompt_ids, full_ids)


def percentiles(values: list[int]) -> dict:
    if not values:
        return {}
    ordered = sorted(values)
    pick = lambda q: ordered[min(len(ordered) - 1, int(q * len(ordered)))]  # noqa: E731
    return {
        "n": len(ordered),
        "p50": pick(0.50),
        "p90": pick(0.90),
        "p99": pick(0.99),
        "max": ordered[-1],
        "mean": round(statistics.fmean(ordered), 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--soul", default="soul", help="魂ディレクトリ（nano dataset の出力元）")
    parser.add_argument("--tokenizer", default=None, help="HF のトークナイザ名かパス。ベースモデルと同じもの")
    parser.add_argument("--max-seq-len", type=int, default=4096, help="収まらない行は切らずに落とす")
    parser.add_argument(
        "--generation",
        action="append",
        default=None,
        help="この世代の ⭐ だけ使う（繰り返し可）。既定は全世代。内訳は必ず表示される",
    )
    parser.add_argument("--out", default="train/work")
    parser.add_argument("--dry", action="store_true", help="内訳と長さの統計だけ出して書き出さない")
    args = parser.parse_args(argv)

    source = Path(args.soul) / "export" / "train"
    sft = read_jsonl(source / "sft.jsonl")
    orpo = read_jsonl(source / "orpo.jsonl")
    if not sft and not orpo:
        print(f"{source} に教師データがありません。先に nano dataset を回してください。", file=sys.stderr)
        return 2

    # --- 世代の内訳。⭐ は人間の判断なので世代をまたいで材料にしてよいが、
    #     何がどれだけ入っているかは必ず見る（docs/finetune.md §7）。
    by_generation = Counter(generation_of(row.get("meta", {})) or "(不明)" for row in sft)
    print("SFT の世代内訳:")
    for name, count in by_generation.most_common():
        print(f"    {name}: {count} 件")
    if args.generation:
        keep = set(args.generation)
        sft = [row for row in sft if generation_of(row.get("meta", {})) in keep]
        orpo = [row for row in orpo if row.get("meta", {}).get("generation", "") in keep]
        print(f"--generation で絞った結果: SFT {len(sft)} 件 / ORPO {len(orpo)} 対")

    tokenizer = load_tokenizer(args.tokenizer)
    if tokenizer is None:
        print("\nトークナイザ未指定。長さの判定はできないので内訳だけ出して終わります（--tokenizer）。")
        return 0

    # --- 長さ。切らない。落とす。
    kept_sft, dropped_sft, lengths, no_answer = [], 0, [], 0
    for row in sft:
        encoded = encode_sft(tokenizer, row["messages"])
        lengths.append(len(encoded.input_ids))
        if encoded.answer_tokens == 0:
            no_answer += 1
            continue
        if not fits(encoded, args.max_seq_len):
            dropped_sft += 1
            continue
        kept_sft.append(row)

    kept_orpo, dropped_orpo = [], 0
    for row in orpo:
        prompt_ids = tokenizer.apply_chat_template(row["prompt"], add_generation_prompt=True, tokenize=True)
        longest = len(prompt_ids) + max(
            len(tokenizer(row["chosen"])["input_ids"]), len(tokenizer(row["rejected"])["input_ids"])
        )
        if longest > args.max_seq_len:
            dropped_orpo += 1
            continue
        kept_orpo.append(row)

    stats = {
        "source": str(source),
        "source_sha256": {"sft": sha256(source / "sft.jsonl"), "orpo": sha256(source / "orpo.jsonl")},
        "tokenizer": args.tokenizer,
        "max_seq_len": args.max_seq_len,
        "generations": dict(by_generation),
        "generation_filter": args.generation,
        "sft": {"kept": len(kept_sft), "dropped_too_long": dropped_sft, "dropped_no_answer": no_answer},
        "orpo": {"kept": len(kept_orpo), "dropped_too_long": dropped_orpo},
        "length_tokens": percentiles(lengths),
    }
    print("\n長さ（トークン）:", json.dumps(stats["length_tokens"], ensure_ascii=False))
    print(f"SFT: {len(kept_sft)} 件を使う / 長すぎて落とした {dropped_sft} 件 / 応答が無い {no_answer} 件")
    print(f"ORPO: {len(kept_orpo)} 対を使う / 長すぎて落とした {dropped_orpo} 対")
    if sft and dropped_sft / max(1, len(sft)) > 0.2:
        print("  ⚠ 2割以上を落としています。--max-seq-len を上げるか、想起の top_k を見直すこと")

    if args.dry:
        return 0
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for name, rows in (("sft.jsonl", kept_sft), ("orpo.jsonl", kept_orpo)):
        with (out / name).open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    (out / "prepare.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n→ {out}/ に書き出しました。次: python train/qlora.py --work {out} --base <ベースモデル>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
