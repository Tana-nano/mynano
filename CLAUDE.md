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

## 文体

- ユーザー向け文書（README、商品説明）は日本語。丁寧語、専門用語には一言説明を添える。
- コードのコメント・識別子は英語。
