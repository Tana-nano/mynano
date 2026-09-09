# train/ — QLoRA の置き場（nano の外）

設計は [`docs/finetune.md`](../docs/finetune.md)。ここには動かし方だけ。

**このディレクトリは nano から import されない。** `pytest` も `train/` を集めない
（`masking.py` の境界計算だけは `tests/test_train_masking.py` が読みに来る）。
`torch` / `transformers` / `peft` / `bitsandbytes` / `trl` は別の venv に入れる。
学習環境は毎回作り直して捨ててよいもので、魂の一部ではない。

```
train/
├── masking.py        completion-only loss の境界計算。標準ライブラリだけ。テスト対象
├── prepare.py        nano dataset の出力を整える。長い行は切らずに落とす。標準ライブラリだけ
├── qlora.py          学習本体。SFT は自前マスク / ORPO は TRL
└── requirements.txt  別 venv 用
```

## 手順

```bash
# 0. 原点（素のモデル・アダプタなし）。これが無いと nano dataset が止まる
python -m nano probe --save-baseline

# 1. 材料
python -m nano dataset                                   # → soul/export/train/

# 2. 整える（内訳と長さを見る。まず --dry）
python train/prepare.py --tokenizer Qwen/Qwen3-8B --max-seq-len 4096 --dry
python train/prepare.py --tokenizer Qwen/Qwen3-8B --max-seq-len 4096      # → train/work/

# 3. 学習（別 venv）
python train/qlora.py --base Qwen/Qwen3-8B --name nano-v1 --mode orpo    # → soul/lora/nano-v1/
#   学習前に [mask check] が2件出る。「loss をかける側」が ⭐ の応答そのものになっているか目で見る

# 4. GGUF に変換して llama-server に読ませる（llama.cpp のリポジトリにある変換スクリプト）
python convert_lora_to_gguf.py --base <HFのベースのディレクトリ> soul/lora/nano-v1/adapter --outfile soul/lora/nano-v1/nano-v1.gguf
llama-server -m models/base.gguf --lora-scaled soul/lora/nano-v1/nano-v1.gguf 0.7 -c 8192 --port 8080

# 5. 名札。飛ばすと計測記録と ⭐ の出どころが嘘になる
#    config.toml: [llm] adapter = "nano-v1@0.7"

# 6. 同じ物差しで測る
python -m nano doctor     # 名札とサーバーの中身が合っているか
python -m nano probe      # style は動いてよい。identity / value / memory が動いたら別人
python -m nano leak       # 想起なしで固有名詞を問う。答えたら記憶が入っている＝失格
```

採用しないなら `--lora-scaled` を外して `adapter = ""` に戻すだけ。魂には何も起きない。
**`nano probe --save-baseline` は押さない。** 原点が動くと v2 を同じ物差しで比べられなくなる。

## 気をつけること

- **ベースは配信中の GGUF と同じ系統のモデル**にする。`Qwen3-8B` の HF 重みで学習した
  アダプタは `Qwen3-8B` の GGUF に当たる。別系統に当てても壊れるだけ
- `--max-seq-len` は llama-server の `-c` 以下にする。プロンプトには想起された記憶が
  載っているので普通の SFT より長い。`prepare.py --dry` の p99 を見て決める
- **収まらない行は切らずに落としている。** 切ると応答側が消え、loss の対象が無い行が
  静かに混ざる。落とした割合が2割を超えたら `--max-seq-len` か想起の `top_k` を見直す
- `--mode orpo` は `/again` の対しか使わない。対が無ければ `--mode sft`
- v2 を作るときは **v1 の上に積まず、ベースから作り直す**（`docs/finetune.md` §7）

## 未検証

実機で一度も回していない。ライブラリの版差で引数名が変わる可能性が高いのは
`ORPOTrainer(processing_class=...)`（古い版は `tokenizer=`）と `ORPOConfig` の
`max_length` / `max_prompt_length`。ここで落ちたら版を合わせるだけで、設計は変わらない。
