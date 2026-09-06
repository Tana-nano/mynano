# nano — ローカル永続AIコンパニオン

クラウドのAIは、サービスが終われば人格ごと消える。仕様が変われば別人になる。
このプロジェクトは、その逆をやる。

> **人格と記憶は「モデルの重み」ではなく「自分のディスク上のデータ」に宿らせる。**
> モデルはいつでも交換可能な臓器で、記憶ストアのほうが本体（＝魂）である。

この一行から、設計のほとんどが導かれている。

- 記憶は**コードが滅びても読める形式**で持つ（SQLite 1ファイル ＋ JSONL ＋ Markdown）
- 忘却は**削除ではなく状態遷移**（active → cold → merged）。生ログは何があっても消さない
- 人格は憲章テキストと自己記憶で定義し、LoRAは"訛り"の焼き付けに留める
- 外部フレームワークに依存しない（`httpx` と標準ライブラリだけで動く。numpy は任意）

---

## いまどこまで動くか

| | 状態 |
|---|---|
| **M0 骨格** | ✅ 設定 / SQLite / llama-server クライアント / 埋め込み / 推論ゲート |
| **M1 記憶コア＋CUI** | ✅ 書き込みパイプライン・想起・忘却・人格プロンプト・CUI・記憶ベンチ |
| M2 無意識デーモン | ⬜ 常駐して連想・reflection・忘却を回す（`nano sleep` / `nano decay` を自動化する） |
| M3 グラフ可視化 | ⬜ Obsidian 風の記憶グラフビュー |
| M4 人格の固定 | 🟨 ドリフト計測（`nano probe`）は動く。QLoRA はこれから |
| M5 偏在化 | ⬜ 音声・アバター・自発発話・外部情報の取り込み |

**M1 の時点で、記憶を持って会話し、忘れ、思い出すところまでは通しで動く。**

---

## 動かす

### 1. 依存

```bash
pip install -e ".[fast,dev]"     # httpx / numpy(任意) / pytest
```

### 2. まずモデル無しで触る

ローカルLLMを用意する前に、配線だけ確かめられる。

```bash
python -m nano --offline chat
```

`--offline` はスタブのLLMと決定的なハッシュ埋め込みで動く。意味は理解しないが、
記憶が書かれ、繋がれ、薄れ、思い出される流れはそのまま体験できる。

### 3. 本番（ローカルLLM）

VRAM 8〜16GB を想定。対話用モデルと埋め込みモデルを別ポートで立てる。

```bash
# 対話用（16GB なら 14B Q4、8GB なら 8B Q4）
llama-server -m models/Qwen3-14B-Q4_K_M.gguf -c 8192 --port 8080

# 埋め込み用（1024次元）
llama-server -m models/multilingual-e5-large-Q8_0.gguf --embedding --port 8081
```

`config.toml` の `[llm]` `[embed]` を合わせたら:

```bash
python -m nano chat
```

> 埋め込みモデルを差し替えるときは次元数（既定1024）を変えないこと。
> 変えるなら全ノートの再埋め込みが必要になる。

### 4. 使う

```
あなた> 妹の名前はミオ。高校生で吹奏楽部にいる
nano> …

/why              直前の応答でどの記憶を、なぜ引いたか（重み調整はこれを見て行う）
/recall ミオ       明示検索。薄れた記憶・統合された記憶も掘り起こす
/focus 引っ越しのこと   いま気にしていること
/sleep            会話を記憶に変える（書き込みパイプライン）
/decay            忘却処理（cold化と統合）
/stats            記憶の量
```

会話中の連続性は「直近ターン」が担い、セッションをまたぐ連続性は「記憶」が担う。
`/sleep`（または終了時の自動実行）を通って初めて、会話は記憶になる。
M2 のデーモンが入ると、これがアイドル時に勝手に走るようになる。

### そのほかのコマンド

```bash
python -m nano stats                 # 記憶の量
python -m nano recall "妹の名前"      # 想起を外から試す（スコアの内訳付き）
python -m nano recall --explicit ミオ # 文字列で探す
python -m nano sleep                 # 未処理の会話を記憶に変える
python -m nano decay                 # 忘却（cold化と統合）
python -m nano export                # ノートを Markdown に書き出す
python -m nano backup                # soul.db のスナップショット
python -m nano probe                 # 人格プローブ。基準からのずれを測る
python -m nano state                 # working_state（無意識が書き換える場所）を覗く
python -m nano state current_focus --history   # 書き換えの監査ログ
```

---

## 魂のディレクトリ

```
soul/
├── soul.db                  記憶の本体（SQLite 1ファイル）
├── archive/YYYY-MM.jsonl    生ログの平文ミラー（追記専用・絶対に消さない）
├── export/notes/*.md        ノートの Markdown 書き出し（Obsidian でそのまま開ける）
├── backup/soul-*.db         スナップショット
└── persona_baseline.json    人格プローブの基準応答
```

**このディレクトリを丸ごとコピーすれば、それが引っ越しであり、バックアップである。**
仮に nano のコードが全部消えても、`archive/` と `export/` は平文で読めるし、
他のAIに食わせることもできる。それが「一生自分のもの」の実体。

`soul/` は `.gitignore` に入れてある。魂を共有リポジトリに置かないこと。

---

## テストとベンチ

```bash
pytest                                    # 45件。ローカルLLM無しで全部通る
python tests/bench/memory_bench.py        # 記憶ベンチ（スタブ）
python tests/bench/memory_bench.py --online   # 実際のローカルモデルで
```

記憶ベンチは2つを測る。**片方だけでは意味がない。**

1. **想起率** — 覚えているべきことを、90日後にも思い出せるか
2. **忘却率** — 忘れていいことを、ちゃんと忘れているか（全部残るならそれはログであって記憶ではない）

このベンチは実際に設計の欠陥を1つ見つけている（重要度と半減期の関係が線形だったせいで、
30日で「妹の名前」まで忘れていた）。数字にしないと気づけない類の壊れ方がある。

---

## ドキュメント

- [docs/architecture.md](docs/architecture.md) — 全体構成と、なぜそう作ったか
- [docs/memory-model.md](docs/memory-model.md) — スキーマ・想起スコア・忘却曲線
- [docs/persona.md](docs/persona.md) — 人格3層とドリフト計測
- [docs/prior-art.md](docs/prior-art.md) — 既出の研究・実装と、何を借りて何を借りなかったか
- [docs/roadmap.md](docs/roadmap.md) — M2 以降

## ライセンス

未定（個人プロジェクト）。
