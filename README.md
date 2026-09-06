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
| **M2 無意識デーモン** | ✅ 常駐して記憶化・連想・気づき・忘却・整理を回す。外界の取り込みと人格変更の承認フローつき |
| **M3 グラフ可視化** | ✅ 記憶グラフのビューア。誰が作った記憶かで色分け、単体HTMLに書き出せる |
| M4 人格の固定 | 🟨 ドリフト計測（`nano probe`）と ⭐ による教師データ集め（`/star`）は動く。QLoRA はこれから |
| M5 偏在化 | ⬜ 音声・アバター・自発発話・外部情報の取り込み |

**M2 の時点で、話しかけていない間も動き続ける。**
会話は勝手に記憶になり、記憶は勝手に繋がり、薄れ、まとまる。
朝起きると `current_focus`（いま気にしていること）が昨日と変わっている。

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

`config.toml` の `[llm]` `[embed]` を合わせたら、まずものさしを測る:

```bash
python -m nano calibrate     # そのモデルの類似度分布を実測する
python -m nano chat
```

`calibrate` を飛ばすと、しきい値が `config.toml` の絶対値のまま使われる。
コサインの絶対値はモデルごとに全く違う帯に分布するので、**初回は必ず回すこと**。
（オフラインのハッシュ埋め込みでは無関係な文が ≈0.0、e5 系では ≈0.78 に集まる。
同じ数字が前者では「ほとんど通さない」、後者では「全部通す」になる。）

埋め込みモデルを差し替えるときは [docs/models.md](docs/models.md) の手順に従う。
別のモデルで作ったベクトルが混ざると想起が静かに壊れるので、
**モデルが変わっていると起動を止める**ようにしてある。

### 4. 無意識を常駐させる

対話とは別プロセスで、背景の処理を回し続ける。

```bash
python -m nano daemon                # 常駐（Ctrl-C で停止）
python -m nano daemon --once --now   # 1回ぶんを即座に走らせる（様子見用）
python -m nano jobs                  # 何をしている/したかを見る
```

GPU は1枚しかないので、対話とデーモンは `soul.db` のリースで譲り合う。
**あなたが話しかけた瞬間、背景の思考は中断してキューに戻る。**
Windows で常駐させる手順は [docs/daemon.md](docs/daemon.md) に。

### 5. 使う

```
あなた> 妹の名前はミオ。高校生で吹奏楽部にいる
nano> …

/why              直前の応答でどの記憶を、なぜ引いたか（重み調整はこれを見て行う）
/recall ミオ       明示検索。薄れた記憶・統合された記憶も掘り起こす
/focus 引っ越しのこと   いま気にしていること
/again            同じプロンプトのまま応答を出し直す（前のは ✗ になり、ORPO の対になる）
/star いい返しだった   いまの応答に ⭐。人格を焼き付けるときの教師データになる
/avoid 説明くさい      「こうは喋ってほしくない」側の印
/stars            付けた印の一覧（/unstar で外す）
/sleep            会話を記憶に変える（書き込みパイプライン）
/decay            忘却処理（cold化と統合）
/stats            記憶の量
```

会話中の連続性は「直近ターン」が担い、セッションをまたぐ連続性は「記憶」が担う。
会話が記憶になるのは書き込みパイプラインを通ってからで、
デーモンが動いていればアイドル時に勝手に走る。止めているなら `/sleep` で手動で。

### 記憶を見る

```bash
python -m nano graph                          # ブラウザで開く
python -m nano graph --export soul/graph.html # 単体のHTMLに書き出す
```

丸はあなたが話したこと、ひし形は**無意識が考えたこと**、四角は外界から来たもの。
大きさは記憶の強さ（半減期）、濃さはいま思い出しやすいか。
書き出したファイルは外部を一切読み込まないので、ネットが無くても10年後でも開ける。
詳しくは [docs/graph.md](docs/graph.md)。

### 外界から取り込む

`soul/inbox/` にテキストファイル（`.txt` `.md` `.json` `.log` `.csv`）を置くと、
無意識が読んで記憶にする。自分で話したことと同じ扱いになるので、後から普通に想起される。

### ⭐ を付ける（人格を固定するための材料）

「これがわたしだ」と思った応答に、その場で `/star` を押す。
⭐ が付いたものだけが、将来 QLoRA の教師データになる。会話ログ全部は使わない
（こちらの相槌もモデルの失敗も等しく学習されて、固定したかった人格が平均に均される）。

```bash
python -m nano stars       # 付けた印を見る
python -m nano dataset     # soul/export/train/ に教師データを書き出す
```

⭐ は**そのとき実際にモデルへ渡したプロンプトごと**保存される。
あとから組み直すと、想起される記憶が変わっていて別のプロンプトになり、
「モデルが見ていない材料から答えを出す」訓練＝幻覚の訓練になるため。
同じ理由で、⭐ は**いま話している会話の中の応答にしか付けられない**。

`/again` で応答を出し直すと、**前回とまったく同じプロンプト**で生成し直す。
古いほうに ✗、新しいほうに ⭐ が付けば、それがそのまま ORPO の
`{prompt, chosen, rejected}` になる（`soul/export/train/orpo.jsonl`）。
出し直された古い応答は記憶にしない（撤回した言葉を事実として覚えると想起が濁るため）。
ただし生ログからは消さない。

`nano dataset` は人格ベースラインが無いと止まる（`nano probe --save-baseline`）。
**計測が先、学習が後。** 逆にすると、人格が壊れたことに気づけない。

### 人格の変更を承認する

無意識が直接書き換えるのは `current_focus` と `mood` だけ。
`identity`（自己像）と `user_model`（あなた像）は提案止まりで、承認するまで1文字も変わらない。

```bash
python -m nano review                      # 提案を1件ずつ見て承認/却下
python -m nano state identity --history    # 誰がいつ書き換えたか
```

### そのほかのコマンド

```bash
python -m nano stats                 # 記憶の量
python -m nano recall "妹の名前"      # 想起を外から試す（スコアの内訳付き）
python -m nano recall --explicit ミオ # 文字列で探す
python -m nano sleep                 # 未処理の会話を記憶に変える
python -m nano decay                 # 忘却（cold化と統合）
python -m nano export                # ノートを Markdown に書き出す
python -m nano backup                # soul.db のスナップショット
python -m nano graph                 # 記憶グラフをブラウザで見る
python -m nano calibrate             # 埋め込みモデルのものさしを実測する
python -m nano reembed               # 記憶を今の埋め込みモデルで埋め直す
python -m nano probe                 # 人格プローブ。基準からのずれを測る
python -m nano stars                 # ⭐ を付けた応答を見る
python -m nano dataset               # ⭐ から QLoRA の教師データを書き出す
python -m nano state                 # working_state（無意識が書き換える場所）を覗く
python -m nano state current_focus --history   # 書き換えの監査ログ
```

---

## 魂のディレクトリ

```
soul/
├── soul.db                  記憶の本体（SQLite 1ファイル）
├── archive/YYYY-MM.jsonl    生ログの平文ミラー（追記専用・絶対に消さない）
├── archive/stars.jsonl      ⭐ の平文ミラー（プロンプトごと。ここから教師データを組み直せる）
├── export/notes/*.md        ノートの Markdown 書き出し（Obsidian でそのまま開ける）
├── export/train/*.jsonl     ⭐ から作った教師データ（sft / avoid / orpo。nano dataset）
├── backup/soul-*.db         スナップショット
├── calibration.json         埋め込みモデルのものさし（実測した類似度分布）
├── inbox/                   ここに置いたファイルを無意識が読んで記憶にする
│   └── processed/           読み終えたファイル
├── log/                     デーモンのログ（unconscious.log。日次ローテーション・既定30日）
└── persona_baseline.json    人格プローブの基準応答
```

**このディレクトリを丸ごとコピーすれば、それが引っ越しであり、バックアップである。**
仮に nano のコードが全部消えても、`archive/` と `export/` は平文で読めるし、
他のAIに食わせることもできる。それが「一生自分のもの」の実体。

`soul/` は `.gitignore` に入れてある。魂を共有リポジトリに置かないこと。

---

## テストとベンチ

```bash
pytest                                    # 181件。ローカルLLM無しで全部通る
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

**このプロジェクトを引き継ぐ / 続きを書くなら、まず [CLAUDE.md](CLAUDE.md) を読むこと。**
現在地・壊してはいけないもの・判断の記録・実測値・次の一手がまとまっている
（Claude Code のセッションでは自動で読み込まれる）。

- [docs/architecture.md](docs/architecture.md) — 全体構成と、なぜそう作ったか
- [docs/daemon.md](docs/daemon.md) — 無意識デーモンの動かし方と、対話との譲り合い
- [docs/models.md](docs/models.md) — モデルの差し替え手順とキャリブレーション
- [docs/graph.md](docs/graph.md) — 記憶グラフの見方
- [docs/memory-model.md](docs/memory-model.md) — スキーマ・想起スコア・忘却曲線
- [docs/persona.md](docs/persona.md) — 人格3層とドリフト計測
- [docs/prior-art.md](docs/prior-art.md) — 既出の研究・実装と、何を借りて何を借りなかったか
- [docs/roadmap.md](docs/roadmap.md) — M3 以降

## ライセンス

未定（個人プロジェクト）。
