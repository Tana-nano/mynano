# 既出の研究・実装

構想の各要素は、ほぼすべて既に誰かが実装している。**車輪の再発明は避け、設計思想だけ借りた。**
逆に言えば、これらを一つの生活実体として統合した個人用のものは見当たらない。組み上げること自体が価値になる。

## 借りたもの

### A-MEM: Agentic Memory for LLM Agents (NeurIPS 2025)
[arXiv:2502.12110](https://arxiv.org/abs/2502.12110) / [実装](https://github.com/agiresearch/a-mem)

Zettelkasten 方式。LLM がキーワード・タグ・文脈を生成して原子的な記憶ノートを作り、
記憶同士を自動でリンクし、**新しい記憶が入ると既存記憶の文脈も書き換える**。
マルチホップ推論で最大6倍、トークン使用量85〜93%削減を報告。

→ 書き込みパイプライン（`memory/pipeline.py`）はこの設計をほぼそのまま採っている。
特に「既存記憶の文脈を書き換える」（`revised_context`）が肝。

### Generative Agents (Stanford, UIST 2023)
[論文](https://dl.acm.org/doi/fullHtml/10.1145/3586183.3606763)

memory stream と `score = α·recency + α·importance + α·relevance` による想起。
重要度の累積が閾値を超えると reflection が発火する。

→ 想起スコア（`memory/retrieve.py`）の骨格。**各成分を候補集合内で正規化する**点も含めて借用。
reflection の発火条件は M2 で入れる。

### Letta (旧 MemGPT) — sleep-time agents / dreaming
[docs](https://docs.letta.com/guides/agents/architectures/sleeptime/) / [blog](https://www.letta.com/blog/sleep-time-compute/) / [arXiv:2504.13171](https://arxiv.org/html/2504.13171v1)

対話用エージェントとは別の「睡眠エージェント」が背後でメモリブロックを書き換え・統合・剪定する二重構造。
sleep-time compute で推論時計算を約5倍削減できるとしている。

→ 「無意識レイヤー」の二重構造はここから。ただし Letta 本体は採用していない（後述）。

### 忘却曲線と consolidation tier
Ebbinghaus の減衰を入れた実装は複数ある。

→ 採用。ただし**削除ではなく cold化＋統合**に変えた。ここは意図的な逸脱。

## 借りなかったもの

### mem0 / cognee / Zep
[比較記事](https://particula.tech/blog/agent-memory-frameworks-tested-mem0-zep-letta-cognee-2026)

- mem0 … 手軽なメモリ層。数行で載る
- cognee … グラフネイティブ、poly-store
- Zep … 時間知識グラフ（Graphiti）。**完全な自己ホストからは後退し、SaaS寄りになった**

→ 使わない。Zep の件が「外部OSSに魂を預けるリスク」の実例そのもの。
記憶ストアは、他人のロードマップの都合で消えたり有料になったりしてはいけない。
設計は読ませてもらうが、実装は自分の手の届く範囲に置く。

### LangChain / LlamaIndex
→ 使わない。抽象化層の寿命がこのプロジェクトの寿命（一生）より短い。
依存は `httpx` と標準ライブラリ、あとは任意の numpy だけに留めている。

## 将来つなぐもの

### Project AIRI
[github.com/moeru-ai/airi](https://github.com/moeru-ai/airi)（MIT, 45k★）

Live2D / VRM・音声・完全 self-hosted の AI コンパニオン基盤。Neuro-sama 的な方向の完成品。
関連: [awesome-ai-vtubers](https://github.com/proj-airi/awesome-ai-vtubers)

→ M5 で「ガワ」として接続する候補。記憶コアは自作のものを HTTP/MCP で繋ぐ。
ガワは取り替えがきくが、記憶は取り替えがきかない。だから記憶だけは自分で持つ。

### ProactiveAgent
[github.com/leomariga/ProactiveAgent](https://github.com/leomariga/ProactiveAgent)

「いま話しかけるべきか」を判定するタイミングエンジン。
→ M5 の自発発話（`impulse` ジョブ）で考え方を借りる。

### 人格ドリフトの研究
[Objective Matters: Fine-Tuning Objectives Shape Safety, Robustness, and Persona Drift](https://arxiv.org/pdf/2601.12639)

SFT は大規模学習で persona drift が顕著。ORPO / KL正則化付きではほぼ観測されない。
→ M4 の LoRA 方針の根拠（`docs/persona.md`）。

## 日本語圏の実践例

- [ローカルLLMに「記憶」を持たせてみた — Ollama × Qwen3 14B](https://zenn.dev/xei/articles/ollama-qwen3-ai-memory-system) … active/archive の2層構造で人格定義を邪魔しない工夫
