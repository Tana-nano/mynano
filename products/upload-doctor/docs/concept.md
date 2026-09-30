# アップロードドクター for VRChat — 企画書 (concept)

作成日: 2026-09-30 / 状態: **全論点決定 → /vrc-spec へ**
市場調査: `docs/market/system-tool-candidates-2-2026-09.md`（候補 B）

## Step 1: コンセプト

| 項目 | 内容 |
|---|---|
| 商品種別 | PC アプリ（Windows、ダブルクリックで動く CLI。OSCドクターと同じ作り）。読み取り専用で、プロジェクトを書き換えない |
| 対象ユーザー | ① 市販アバターを自分で導入して上げたい改変初心者 ② 商品ページに「困ったらこれを」と書きたいアバター/衣装の出品者 |
| 提供体験 | Unity が赤いエラーだらけ、または VRChat SDK のメニューが出ない、アップロードが通らない。そこでプロジェクトのフォルダと `Editor.log` を指定して実行すると、「Unity のバージョンが違う」「古い SDK が二重に入っている」など**原因の候補が日本語で順位付きで出る**。サポートに貼れるレポート txt（ユーザー名・パスはマスク）も同時にできる |
| 販売形態 | **無料＋ブースト任意（仮置き）**。ショップの入口 2 号。出品者が商品ページに紹介してくれる導線を狙う |
| 参考作品 | VRChat SDK の Build Control Panel（Unity 内で検証。**Unity が開けない/コンパイルエラー/パネルが出ないときは使えない**）、ConsoleLogSaver（エラーの保存・共有のみ、原因は教えない）、note・ぶいなび等の解説記事（読むのに時間がかかる） |
| 差別化 | (1) **Unity が壊れていても動く**（静的解析なので、SDK パネルが出ない状況で使える）(2) 原因の候補を順位付きで日本語提示 (3) 貼れるレポート。出品者のサポート往復が 1 回減る (4) ルール表はデータファイルで、SDK の変更に追随して更新できる |
| 対応環境 | PC（Unity を動かす Windows）で使う。VR / デスクトップの区別なし。**Quest 単機 ×**（Unity は PC）。**Quest 向けアバターのビルド検証は対象外** |
| AI 製リスク | 画像なし。出力は文字のみ。サムネは実行画面のスクリーンショット＋文字組み |

### ユーザーの一日での位置

1. 市販アバターを Unity に入れた → 赤いエラー、または「Build & Publish」が出ない/失敗 → X や検索で「アップロードできない」を調べる
2. 記事が多く、どれが自分の原因か分からない → 本ツールに辿り着く（またはアバターの商品ページで紹介されている）
3. ダブルクリック → プロジェクトのフォルダを指定 → 原因の候補が並ぶ → 上から順に直す
4. 直らなければレポート txt を出品者/詳しい友人に貼る（「Unity のバージョンは？SDK は？」の往復が要らない）
5. レポート末尾の一行でショップの他ツール（OSCドクター、V睡ログ）を知る

## Step 2: 技術的実現可能性

### 診断項目と一次情報

出典の `creator-docs` は VRChat 公式ドキュメントの元リポジトリ（GitHub）。creators.vrchat.com 本体は egress ブロックのため、この原文を読んだ。

| # | 診断 | 方法 | 出典 | 状態 |
|---|---|---|---|---|
| 1 | Unity のバージョンが推奨と違う | `ProjectSettings/ProjectVersion.txt` の `m_EditorVersion` を推奨版と比較。**推奨版はルール表に持つ** | https://raw.githubusercontent.com/vrchat-community/creator-docs/main/Docs/docs/sdk/upgrade/current-unity-version.md — 「推奨は 2022.3.22f1」「Unity Hub のセキュリティ警告に従ってアップグレードするとアップロードに失敗する」 | 確認済（調査日時点。**推奨版は変わりうる**ので表で管理し、READMEに確認日を書く） |
| 2 | SDK パネルが出ない原因の切り分け | コンパイルエラー（Editor.log の `error CS####`）の有無と発生元（`Assets/` の第三者スクリプトか `Packages/` か）を集計 | https://raw.githubusercontent.com/vrchat-community/creator-docs/main/Docs/docs/sdk/sdk-troubleshooting.md — 原因は「推奨版でない」「第三者スクリプト/コンポーネントのコンパイルエラー」 | 確認済（原因分類）。**Editor.log の実サンプル未入手**（下記） |
| 3 | VPM パッケージの不整合 | `Packages/vpm-manifest.json` の `dependencies` / `locked` と `Packages/` 内の実フォルダを突き合わせ、欠落・バージョン差・`LegacyPackages` の残りを検出 | https://vcc.docs.vrchat.com/vpm/resolver/ （リゾルバは manifest と Packages を比較し欠落を復元、LegacyPackages を削除する。**egress ブロック、検索要約**） | JSON の形は要約で確認。**実物未確認** |
| 4 | 旧 SDK の二重導入 | `Assets/VRCSDK` と `Packages/com.vrchat.*` の同居、`Scripting Define Symbols`（`UDON`, `VRC_SDK_VRCSDK3`, `VRC_SDK_VRCSDK2`）の食い違い | sdk-troubleshooting.md 「SDK Version Conflicts」 | 確認済（記載どおり）。`ProjectSettings.asset` のテキスト形式（Force Text）前提で**未検証** |
| 5 | パッケージの依存漏れ | `Packages/*/package.json` の `vpmDependencies` が `locked` で満たされているか | https://github.com/vrchat-community/vpm-package-template （VPM パッケージの形。`vpmDependencies` の項目名は要約で確認） | **未確認**（実 package.json で確認する） |
| 6 | 定番の環境要因 | プロジェクトのパスや Windows ユーザー名に日本語（マルチバイト）、Dynamic Bone の残り（`Assets/DynamicBone*`）、SDK 3.9.0 未満での新規アップロード不可 | 検索要約のみ: https://koshishirai.com/en/unity-vrchat-avatar-upload-solution/ ほか | **未確認**（一次情報なし。ルール表で「情報源: 解説記事」と明示し、断定しない表現にする） |
| 7 | Editor.log のエラー分類 | 行パターン: `Assets/…(行,列): error CS####:`、`Failed to build avatar`、`Avatar validation failed` 等を規則表で分類 | 例: https://ask.vrchat.com/t/avatar-validation-failed/25422 ほか公開フォーラムの断片 | 断片のみ。**規則表は公開質問の文言から作る = 網羅的でない**と README に書く |
| 8 | 同期パラメータ容量（v0.2 候補） | Expression Parameters アセット（YAML）を読み、bool=1 / int=8 / float=8 bit の合計が 256 bit を超えていないか | https://raw.githubusercontent.com/vrchat-community/creator-docs/main/Docs/docs/avatars/animator-parameters/index.md — 「最大 256 bit」「Int 8 / Float 8 / Bool 1」 | 上限と単価は確認済。**アバターから該当アセットを辿る方法（GUID 解決）は未検証**のため v0.1 では入れない |
| 9 | アバターのサイズ上限 | ビルド成果物ではなくソース側からは測れない | https://raw.githubusercontent.com/vrchat-community/creator-docs/main/Docs/docs/avatars/avatar-size-limits.md — SDK 自身がビルド時に検出して止める | **対象外**（SDK パネルの役目） |

### この環境で検証できる範囲 / できない範囲

| 検証できる（フィクスチャ） | できない（README に未検証と書く） |
|---|---|
| 偽の Unity プロジェクト（`ProjectVersion.txt`, `vpm-manifest.json`, `Packages/`, `ProjectSettings.asset` の一部）を tmp に作って各診断の判定 | 実 Unity が出す `Editor.log` の完全な形式と、SDK 各版のエラー文言 |
| 公開質問から起こしたエラー文言での `Editor.log` 分類、レポート生成、マスク処理 | 実プロジェクトでの誤検知率（市販アバターは構成が多様） |
| 推奨 Unity 版・SDK 版の比較ロジック | SDK / 推奨 Unity 版の将来の変更（ルール表の更新が必要） |
| 出力の日本語文言、レポートの貼りやすさ | 「直った」ことの確認（診断のみで修正しない） |

**AI 製の画像・3D は不要**。テストは全部テキストとフォルダ構造。

### 外部依存

- 標準ライブラリのみ（json / re / pathlib / argparse）。exe 化は OSCドクターと同じ CI（PyInstaller、windows-latest）。同梱する他者アセットなし。
- 前提: 利用者が Unity プロジェクトフォルダを指定できること。Unity 自体や VRChat SDK は同梱しない。

### 失敗しやすい点

- **誤検知**: 「日本語パスが原因」など解説記事ベースの規則は断定しない。「可能性」の順位付けと、根拠（どのファイルのどの行）を必ず併記
- **ルール表の陳腐化**: 推奨 Unity 版や SDK の仕様は変わる → ルール表を別ファイル（JSON）にして、日付と出典を持たせる。古ければ「表の確認日が 90 日前です」と表示
- **プライバシー**: レポートに Windows ユーザー名・`usr_…` の ID・ディレクトリ名が入る → 既定でマスク。ネットワーク通信なし（README に明記）
- **巨大プロジェクト**: `Library/` や大量のアセットを走査すると遅い → 見るのは決まったファイルだけ（`ProjectSettings/`, `Packages/`, `Assets/` 直下の名前一覧）。`Library/` は読まない
- Defender SmartScreen → README に定型説明（OSCドクターと同じ）
- **無料なので問い合わせが増える** → レポート txt で一次切り分けを利用者側で済ませる。README に「できないこと」を先頭に書く

## Step 3: Go / No-Go

**条件付き Go**。差別化は「Unity が壊れていても動く」「貼れるレポート」と言え、Unity 内の SDK 検証（パネルが出ない状況では使えない）と競合しない。無料なので価格根拠は不要で、認知と出品者チャネルの獲得が目的。検証は偽プロジェクトで全部できる。
条件は 2 つ。① 実 Editor.log を 1 本でも入手できるなら v0.1 の分類規則を実物で確認する（無ければ「未検証」と明記して出す）。② 規則表を「原因の候補」として表示し、断定しない。

**No-Go に倒す場合の理由**: 規則が公開質問の断片頼みで、誤検知が多いと信用を損なうため。その場合の代替案は、OSCドクターの拡張（「落ちる」診断）に絞って出さないこと。

## オーナー決定（2026-09-30）

| 論点 | 決定 |
|---|---|
| 1 販売形態 | **A: 無料＋ブースト任意** |
| 2 v0.1 の範囲 | **A: 診断 #1〜#7 とレポート。修正機能なし。#8 パラメータ容量は v0.2** |
| 3 実物の Editor.log | **B: 貼らない。公開質問の文言で規則を作り、「実 Editor.log 未検証」と明記して出す** |

## 論点の記録（決定前の提案）

### 論点 1: 販売形態
- **提案**: 無料＋ブースト任意
- **理由**: 入口 2 号として認知と出品者チャネル（商品ページへの紹介）を取るのが目的。解説記事が無料で大量にあるため、有料にすると比較に負ける
- **選択肢**: A) 無料＋ブースト / B) ¥500 / C) 無料版（診断）＋有料版（出品者向け: 「動作確認環境」の記載文を自動生成する等）
- **確認**: どれにしますか？（推奨 A。C は後から足せる）

### 論点 2: v0.1 の範囲
- **提案**: 診断 #1〜#7（プロジェクト構成 + Editor.log 分類）とレポート。修正機能なし。#8（パラメータ容量）は v0.2
- **理由**: #8 は上限と単価は確認済みだが、アバターから該当アセットを辿る方法が未検証で、誤動作すると信用を損なう。読み取り専用にすれば「壊される」不安がない
- **選択肢**: A) 提案どおり / B) #8 も v0.1 に入れる（未検証の注記付き） / C) Editor.log 分類だけに絞る
- **確認**: どれにしますか？（推奨 A）

### 論点 3: 実物の Editor.log
- **提案**: 手元の Unity で失敗した `Editor.log` があれば 1 本貼ってほしい（ユーザー名部分は伏せて OK）。無ければ公開質問の文言で作り、未検証と明記して出す
- **理由**: 規則の正しさを実物で確かめられる唯一の機会。オーナーが実機デバッグをしない前提は変えず、ファイルを貼るだけ
- **選択肢**: A) 貼る / B) 無い、または貼らない（未検証で進める）
- **確認**: どちらですか？（貼れない場合も進めます）
