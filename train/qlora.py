"""QLoRA 本体。nano の外で、別の venv で回す。骨組み（実機で一度も回していない）。

    python train/qlora.py --base Qwen/Qwen3-8B --work train/work --name nano-v1 --mode orpo

設計は docs/finetune.md。ここで守っているのは次の3つだけで、あとは普通の QLoRA。

1. **loss は assistant の応答部分にだけかける。** プロンプト側には想起された記憶が
   本文のまま載っているので、そこに loss をかけると記憶が重みに入る（禁則10）。
   境界の計算は `masking.py`。学習前に、実際にマスクを外した部分を復号して目で見る。
2. **憲章も焼かない。** 1 の帰結。system プロンプトは丸ごと IGNORE。
3. **manifest を残す。** どのベースモデル・どのデータ・どの設定から作ったかを
   アダプタの隣に置く。ベースが変われば LoRA は無効なので、照合に要る。

ハイパーパラメータの既定値は**全部勘**（docs/finetune.md §6）。実機で1回回して詰める。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from masking import IGNORE, MaskError, split_prompt_and_answer  # noqa: E402

TARGET_MODULES = ("q_proj", "k_proj", "v_proj", "o_proj")  # MLP まで広げるのは記憶が入る方向


def read_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


# --- SFT: 自前でマスクする ---------------------------------------------------
#
# TRL の SFTTrainer にも completion-only の仕組みはあるが、版ごとに引数名も既定も変わる。
# ここだけは自分の目で確かめられる形にしておく（マスクの間違いは静かに通るため）。


def encode_sft(tokenizer, messages: list[dict]):
    prompt_ids = tokenizer.apply_chat_template(messages[:-1], add_generation_prompt=True, tokenize=True)
    full_ids = tokenizer.apply_chat_template(messages, tokenize=True)
    return split_prompt_and_answer(prompt_ids, full_ids)


def show_mask(tokenizer, encoded, answer_text: str) -> None:
    """マスクを外した部分を復号して見せる。⭐ の応答と同じ文になっていなければおかしい。"""
    unmasked = [token for token in encoded.labels if token != IGNORE]
    decoded = tokenizer.decode(unmasked, skip_special_tokens=True).strip()
    masked_head = tokenizer.decode(encoded.input_ids[: min(40, len(encoded.input_ids) - len(unmasked))])
    print("  ── loss をかけない側（先頭40トークン）:", repr(masked_head[:120]))
    print("  ── loss をかける側:", repr(decoded[:160]))
    if answer_text.strip()[:40] not in decoded:
        # テンプレートの末尾記号ぶんの差はあるが、応答の本文が入っていなければマスクが間違っている
        raise MaskError("復号した学習対象が ⭐ の応答と一致しません。マスク境界を疑うこと")


def build_sft_dataset(tokenizer, rows: list[dict], max_seq_len: int):
    from datasets import Dataset

    examples = []
    for index, row in enumerate(rows):
        encoded = encode_sft(tokenizer, row["messages"])
        if len(encoded.input_ids) > max_seq_len or encoded.answer_tokens == 0:
            # prepare.py で落としているはずだが、二重に守る（切らない。落とす）
            continue
        if index < 2:
            print(f"[mask check] sample {index}")
            show_mask(tokenizer, encoded, row["messages"][-1]["content"])
        examples.append({"input_ids": encoded.input_ids, "labels": encoded.labels})
    if not examples:
        raise SystemExit("学習できる行がありません")
    return Dataset.from_list(examples)


# --- ORPO: TRL に任せる（prompt 側は構造上 loss から外れる） ------------------


def build_orpo_dataset(tokenizer, rows: list[dict]):
    from datasets import Dataset

    examples = []
    for row in rows:
        prompt_text = tokenizer.apply_chat_template(row["prompt"], add_generation_prompt=True, tokenize=False)
        examples.append({"prompt": prompt_text, "chosen": row["chosen"], "rejected": row["rejected"]})
    if not examples:
        raise SystemExit("ORPO の対がありません（chat の /again で貯まる）。--mode sft を使うか対を貯めること")
    return Dataset.from_list(examples)


# --- 本体 ----------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", required=True, help="HF のベースモデル。配信中の GGUF と同じ系統であること")
    parser.add_argument("--work", default="train/work", help="prepare.py の出力")
    parser.add_argument("--name", default="nano-v1", help="アダプタの名前。config.toml の adapter に書く名札")
    parser.add_argument("--out", default=None, help="既定は soul/lora/<name>/")
    parser.add_argument("--soul", default="soul")
    parser.add_argument("--mode", choices=("sft", "orpo"), default="orpo")
    parser.add_argument("--rank", type=int, default=8)
    parser.add_argument("--alpha", type=int, default=16)
    parser.add_argument("--dropout", type=float, default=0.05)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--max-seq-len", type=int, default=4096)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=8)
    parser.add_argument("--orpo-beta", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)

    import torch
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    work = Path(args.work)
    out = Path(args.out) if args.out else Path(args.soul) / "lora" / args.name
    out.mkdir(parents=True, exist_ok=True)

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    quant = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
        bnb_4bit_compute_dtype=torch.bfloat16,
    )
    model = AutoModelForCausalLM.from_pretrained(args.base, quantization_config=quant, device_map="auto")
    model = prepare_model_for_kbit_training(model)
    model = get_peft_model(
        model,
        LoraConfig(
            r=args.rank,
            lora_alpha=args.alpha,
            lora_dropout=args.dropout,
            target_modules=list(TARGET_MODULES),
            task_type="CAUSAL_LM",
        ),
    )
    model.print_trainable_parameters()

    started = time.time()
    if args.mode == "sft":
        from transformers import DataCollatorForSeq2Seq, Trainer, TrainingArguments

        rows = read_jsonl(work / "sft.jsonl")
        dataset = build_sft_dataset(tokenizer, rows, args.max_seq_len)
        trainer = Trainer(
            model=model,
            train_dataset=dataset,
            # labels の詰め物も IGNORE にする。ここが pad_token だと詰め物を学習する
            data_collator=DataCollatorForSeq2Seq(tokenizer, label_pad_token_id=IGNORE, padding=True),
            args=TrainingArguments(
                output_dir=str(out / "checkpoints"),
                per_device_train_batch_size=args.batch,
                gradient_accumulation_steps=args.grad_accum,
                num_train_epochs=args.epochs,
                learning_rate=args.lr,
                lr_scheduler_type="cosine",
                warmup_ratio=0.05,
                logging_steps=5,
                save_strategy="no",
                bf16=True,
                gradient_checkpointing=True,
                seed=args.seed,
                report_to=[],
            ),
        )
    else:
        from trl import ORPOConfig, ORPOTrainer

        rows = read_jsonl(work / "orpo.jsonl")
        dataset = build_orpo_dataset(tokenizer, rows)
        trainer = ORPOTrainer(
            model=model,
            processing_class=tokenizer,
            train_dataset=dataset,
            args=ORPOConfig(
                output_dir=str(out / "checkpoints"),
                beta=args.orpo_beta,
                max_length=args.max_seq_len,
                max_prompt_length=args.max_seq_len - 256,
                per_device_train_batch_size=args.batch,
                gradient_accumulation_steps=args.grad_accum,
                num_train_epochs=args.epochs,
                learning_rate=args.lr,
                lr_scheduler_type="cosine",
                warmup_ratio=0.05,
                logging_steps=5,
                save_strategy="no",
                bf16=True,
                gradient_checkpointing=True,
                seed=args.seed,
                report_to=[],
            ),
        )

    trainer.train()
    model.save_pretrained(str(out / "adapter"))

    # --- manifest。ベースが違えばこの LoRA は無効。照合できるように残す。
    prepare_stats = json.loads((work / "prepare.json").read_text(encoding="utf-8")) if (work / "prepare.json").exists() else {}
    baseline_path = Path(args.soul) / "persona_baseline.json"
    baseline = json.loads(baseline_path.read_text(encoding="utf-8")) if baseline_path.exists() else {}
    manifest = {
        "name": args.name,
        "base": args.base,
        "mode": args.mode,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "minutes": round((time.time() - started) / 60, 1),
        "rows": len(rows),
        "hyper": {
            "rank": args.rank, "alpha": args.alpha, "dropout": args.dropout, "lr": args.lr,
            "epochs": args.epochs, "max_seq_len": args.max_seq_len, "orpo_beta": args.orpo_beta,
            "target_modules": list(TARGET_MODULES), "loss": "completion-only",
        },
        "data": {"work": str(work), "sha256": {p.name: sha256(p) for p in work.glob("*.jsonl")}, "prepare": prepare_stats},
        # 学習前の原点。ここに記録された条件（素のモデル・アダプタなし）と比べるのが M4-4
        "probe_baseline": baseline.get("conditions", {}),
        "next": [
            "convert_lora_to_gguf.py --base <HFのベース> adapter/ --outfile <name>.gguf",
            "llama-server -m base.gguf --lora-scaled <name>.gguf 0.7",
            "config.toml: [llm] adapter = \"<name>@0.7\"",
            "nano probe   （style は動いてよい。identity / value / memory が動いたら別人）",
            "nano leak    （想起なしで固有名詞を問う。答えたら記憶が入っている＝失格）",
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n→ {out}/adapter に保存。次にやること:")
    for step in manifest["next"]:
        print("   ", step)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
