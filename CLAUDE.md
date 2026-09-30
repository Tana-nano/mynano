# mynano — VRChat向けツール/商品の制作ハーネス

Booth で販売する VRChat 向けソフトウェア（PC アプリ・Blender アドオン・出品者向けツール）を、
このリポジトリで企画→仕様→実装→出品まで一貫して作る。オーナーは実機デバッグをしない前提。

## 絶対ルール

1. **AI 生成のビジュアルを商品に入れない。** 3D モデル・テクスチャ・サムネ・説明画像を AI で生成しない。
   画像は UI スクリーンショットと文字組みだけで作る。プレースホルダの立方体・球などプリミティブは可。
2. **VRChat 仕様は記憶で書かない。** OSC アドレス、ログ形式、SDK の制限、OyasumiVR などの外部ツール仕様は
   公式ドキュメント/リポジトリを WebFetch/WebSearch で確認し、仕様書 (`products/<name>/docs/spec.md`) に出典 URL を残す。
   確認できなかった項目は「未確認」と明記する。
3. **この環境で検証できる形でしか作らない。** VRChat 実機・Unity・SteamVR が必要な検証は不可能。
   `shared/vrc_mock`（模擬 VRChat）と `shared/fixtures` で再現できる範囲を設計し、再現できない挙動は
   README の「既知の制限」に「未検証」と書く。「動いた」と言えるのはテストが通ったものだけ。
4. **他者アセットを dist に同梱しない。** シェーダー、VRChat SDK、Modular Avatar、他人のプレハブ/フォント/画像は
   同梱せず、導入手順で案内する。依存ライブラリは `product.toml` の `[deps]` に列挙し、ライセンスを確認する。
5. **対応環境を必ず明記する。** PC アプリは Quest 単機では動かない。README と商品説明に
   「PC VR / デスクトップ用（Quest 単機非対応）」を必ず書く。
6. **売れる根拠が書けない商品は着手しない。** `docs/market/` に競合・価格帯・差別化を出典付きで残してから
   `products/` を作る。
7. **モデル名・セッション URL などを成果物に書かない。** コード、README、商品説明に AI ツール名を残さない
   （コミットメッセージの Co-Authored-By は除く）。

## 作業フェーズとスキル

フェーズごとにスキルを使う。フェーズ外のルールは持ち込まない
（企画中はコードを書かない、実装中は確認待ちで止まらない）。

| フェーズ | スキル | 成果物 |
|---|---|---|
| 市場調査 | `/vrc-research` | `docs/market/<topic>.md` |
| 企画 | `/vrc-concept` | `products/<name>/docs/concept.md` |
| 仕様 | `/vrc-spec` | `products/<name>/docs/spec.md`, `test-plan.md` |
| 実装 | `/vrc-build` | `products/<name>/src`, `tests`（全テスト green） |
| 出品 | `/vrc-release` | `products/<name>/dist/*.zip`, `README.md`, `EULA.md`, `booth.md` |

## モデル切り替えの案内

オーナーはモデルを手動で切り替える。以下の場面に入る直前・出た直後に、
「ここから〇〇推奨（理由 1 行）」とメッセージの冒頭で知らせる。現在のモデルのままで良い場合は何も言わない。

| 場面 | 推奨 |
|---|---|
| 市場調査、アイデア出し、候補の比較・選定 | 上位モデル（Fable） |
| 仕様書の完成後レビュー（抜け・矛盾の検出）を 1 回 | 上位モデル（Fable） |
| 一次情報が薄い問題（未確認仕様の推測を含む設計、実機でしか分からない挙動の切り分け） | 上位モデル（Fable） |
| テスト 2 周以上直しても原因が特定できないとき | 上位モデル（Fable） |
| 仕様書・テスト計画の執筆、実装、テスト修正、出品物の作成 | 標準モデル（Opus / Sonnet） |
| 定型作業（README 更新、バージョン上げ、zip 生成） | 軽量モデル可（Sonnet） |

## 技術スタック（既定）

- 言語: Python 3.11。GUI は必要なら PySide6、まずは CLI + 設定ファイルで動く形を優先。
- OSC: `python-osc`。VRChat 受信 9000 / 送信 9001（既定値、設定で変更可）。
- テスト: `pytest`。`python -m pytest` がリポジトリ直下で全部通ること。
- Windows 実行ファイル: `.github/workflows/build-windows.yml` の `windows-latest` で PyInstaller ビルド。
  ローカル（Linux）では exe を作らない。
- 商品メタ: `products/<name>/product.toml`（`templates/product.toml` をコピー）。

## リポジトリ構成

```
CLAUDE.md
.claude/skills/vrc-*/        フェーズ別スキル
shared/vrc_mock/             模擬 VRChat（OSC 送受信・output_log 生成）
shared/fixtures/             実ログ断片・OSC サンプルなどのテストデータ
templates/                   README / EULA / product.toml の雛形
products/<name>/             商品ごとに独立（src, tests, docs, dist）
docs/market/                 市場調査ノート（出典付き）
scripts/                     package.py（zip 生成）, release_check.py（出品前検査）
```

## コマンド

```
python -m pytest                       # 全テスト
python scripts/package.py <name>       # products/<name>/dist/<name>-<version>.zip を生成
python scripts/release_check.py <name> # 出品前チェック
```

## 運用メモ（これまでの商品で分かったこと）

- **Windows ビルドの起動**: タグは push できないセッションがあるため、コミットメッセージに `[build:<name>]` を
  入れて作業ブランチに push するとビルドされる。成果物は Actions の artifact（`<name>-<version>-win64`）。
  `products/<name>/smoke.args` があれば、exe をその引数で 1 回実行し、終了コード 0 か 1 なら合格。
  `pyinstaller.args` で `--collect-submodules` などを追加できる。
- **Windows ビルドのログで日本語が「?」になる**のはランナーのコードページのせい。exe の不具合ではない。
- **UDP ポートの横取りに注意**: Windows では、他アプリが 0.0.0.0 で持つポートにも 127.0.0.1 で bind が
  成功してしまい、通信を奪うことがある。待ち受けは `SO_EXCLUSIVEADDRUSE` を付け、空き判定は 0.0.0.0 に
  排他 bind して確かめる（実装例: `products/vsui-log/src/vsui_log/oscio.py`）。実機での効果は未検証。
- **VRChat の OSC 受信ポートは 9000 とは限らない**: 空いていないと別のポートを使う。OSCQuery の
  HOST_INFO の `OSC_PORT` を優先して確認する（実装例: `products/osc-doctor`）。
- **ブロックされるサイト**: booth.pm と feedback.vrchat.com は直接取得できないことがある。検索結果の要約で
  代用した場合は、そのことを調査ノートに書く。
- **既存商品**: `vsui-log`（V睡ログ、有料）、`osc-doctor`（OSCドクター、無料・ショップの入口）。
  新商品の booth.md の「同じ作者のツール」に並べ、既存商品の booth.md にも追記して相互に紹介する。
- **並行セッション**: 別セッションで別商品を作るときは、`shared/`・`scripts/`・`.github/`・このファイルの
  変更は小さく分けて早めに master へ取り込み、衝突を避ける。商品フォルダの中は自由に変えてよい。

## 文体

- ユーザー向け文書（README、商品説明）は日本語。丁寧語、専門用語には一言説明を添える。
- コードのコメント・識別子は英語。
