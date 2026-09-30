# 出品前チェッカー（unitypackage 検品） — 企画書 (concept)

作成日: 2026-09-30 / 状態: **推奨案で仮決定 → オーナー確認待ちの論点 3 つ（末尾）。回答が無ければ推奨案のまま /vrc-spec へ**
市場調査: `docs/market/unitypackage-inspector-2026-09.md`

## Step 1: コンセプト

| 項目 | 内容 |
|---|---|
| 商品種別 | 出品者向けツール（Windows 用 exe。zip / unitypackage をドラッグ＆ドロップすると検品結果を出す。Unity 不要） |
| 対象ユーザー | Booth に 3D 衣装・アバター・アクセサリ・ギミックを出品する人。特に「対応アバター別に unitypackage を何個も作る」衣装作者と、出品に慣れていない新規作者 |
| 提供体験 | 出品直前、Booth にアップロードする zip をツールに落とすと、数秒で「入れ忘れていそうなもの」「入れてはいけないもの（lilToon / Poiyomi / Modular Avatar / VRChat SDK の混入）」「購入者に別途導入してもらうもの」が日本語で出る。説明書に貼れる「導入に必要なもの・同梱物一覧」の下書きも同時にできる。空の Unity プロジェクトで読み込み直す確認作業を減らし、購入者からの「ピンクになった」「Missing が出た」という問い合わせと再アップロードを減らす |
| 販売形態 | **期間限定無料 → ¥500**（推奨。論点 1）。値上げ予定は最初から商品ページに書く |
| 価格根拠 | 出品者向け Unity ツールは ¥100〜¥1,000（書き出し補助 ¥500、BOOTH Package Manager ¥1,000）。中身確認ツールに「期間限定無料 → ¥300」の前例あり（prbl99）。出典は市場調査ノート |
| 参考作品 | Yan-K Smart Package（無料、Unity 内で依存追跡と参照切れ検出付きの書き出し）、unitypackage 簡単解凍ツール（無料、一覧と抽出のみ）、Unity Asset Store Validator（公式、Asset Store 規約用） |
| 差別化 | (1) **書き出した後の実物**を Unity 無しで検品する（Yan-K は書き出し前） (2) 他者アセットの混入を GUID とパスで判定し、各公式の「同梱しないで」を添えて案内 (3) マテリアルやプレハブが参照している外部 GUID から**前提ツールを自動推定**（lilToon が要る、MA が要る） (4) zip 全体（説明書・規約・複数パッケージ）をまとめて検品 (5) 説明書の下書きを出す |
| 対応環境 | **Windows 10/11 の PC 用ツール**。VRChat 本体・VR 機器は使わない。**Quest 単機では動作しない**（README と商品説明に明記） |
| AI 製リスク | 画像・3D を作らない。出力は文字と表のみ。サムネは実行画面のスクリーンショット＋文字組み |

### ユーザーの一日での位置

1. Unity で衣装を対応アバター別に書き出す（Export Package）
2. zip にまとめる（unitypackage × N、説明書、規約、テクスチャ元データ）
3. **zip を本ツールに落とす** → 赤（混入・危険）、黄（入れ忘れ候補・要確認）、緑を確認
4. 赤があれば Unity に戻って書き出し直す。黄は一覧を見て「Unity 標準のもの」「購入者に別途入れてもらうもの」を判断
5. 出力された「導入に必要なもの・同梱物」の下書きを説明書と Booth の商品説明に貼る
6. アップロード。問い合わせが来たら、レポートを見返して何を同梱したかをすぐ答えられる

## Step 2: 技術的実現可能性

### 技術要素と一次情報

| # | 要素 | 方法 | 出典 | 状態 |
|---|---|---|---|---|
| 1 | unitypackage の読み取り | gzip 圧縮 tar。ルートに GUID 名ディレクトリ、各中に `pathname`（Assets/… のパス）、`asset.meta`、`asset`（フォルダは無し）、任意の `preview.png`。Python 標準の `tarfile` でメモリ上に読み、**ディスクへ展開しない** | https://github.com/m35/UnityPackageViewer , https://pkg.go.dev/github.com/r74tech/unitypackage | 形式は複数の独立実装で一致。確認済 |
| 2 | アセット間参照の抽出 | テキスト形式のアセット（.prefab .mat .controller .anim .asset .unity .overrideController .mask など）と `.meta` から `guid: <32桁hex>` を正規表現で集める。Unity YAML は独自タグ（`!u!`）があるので YAML パーサは使わない | https://pkg.go.dev/github.com/r74tech/unitypackage（`{fileID, guid, type}` 形式） | 確認済。**バイナリ保存のアセットは読めない**（下記） |
| 3 | 新規プロジェクトの既定がテキスト保存か | Unity の Asset Serialization Mode の既定は Force Text | https://github.com/JetBrains/resharper-unity/wiki/Asset-serialization-mode | 確認済（二次資料）。設定を変えた作者のバイナリ資産は「解析できないファイル」として一覧に出す |
| 4 | 他者アセットの GUID 辞書 | 公式リポジトリの `.meta` から GUID とパスを抽出して辞書化。**この環境で git clone できることを確認**（lilToon 2.3.4: 400、Modular Avatar: 954、Poiyomi: 1,214 個の GUID） | https://github.com/lilxyzw/lilToon , https://github.com/bdunderscore/modular-avatar , https://github.com/poiyomi/PoiyomiToonShader | 確認済。**過去バージョンで GUID が変わっていないかは未確認**（仕様で複数タグから抽出して確かめる） |
| 5 | VRChat SDK の検出 | パス（`Packages/com.vrchat.*`、`Assets/VRCSDK`）で判定。SDK の GUID 辞書は作らない | SDK は VCC 配布のみ・non-transferable（https://hello.vrchat.com/legal/sdk は egress ブロック、検索要約） | packages.vrchat.com が egress ブロックで SDK の中身を取れない。**SDK 部品への参照（PhysBone など）は「不明な外部参照」に分類される**。仕様で扱いを決める |
| 6 | 各公式の同梱ルール（案内文の根拠） | lilToon: 制作物と 1 つの unitypackage にまとめるのは非推奨。Poiyomi: `_PoiyomiShaders` を含めない。MA: 同梱は許可だが非推奨、公式配布元へ誘導 | 市場調査ノート「トレンド・公式アップデートの影響」 | Poiyomi・MA は原文確認済。lilToon は検索要約のみ（仕様で原文を再確認） |
| 7 | zip の読み取り | Python 標準の `zipfile`。UTF-8 フラグの無い日本語ファイル名は cp932 として読み直す | 日本語版 Windows は Shift-JIS でファイル名を保存する（https://github.com/saberzero1/unzip-jp-gui） | 方針のみ。**Booth 購入者の解凍環境で文字化けがどれだけ起きるかは未確認** |
| 8 | 安全性 | `pathname` の絶対パス・`..`・ドライブ名を異常として報告。展開しないのでツール自体は書き込まない | https://github.com/Cobertos/unitypackage_extractor/issues/14 | 確認済 |
| 9 | 危険物の検出 | `.cs` `.dll` `.exe` `.bat` `.ps1` などの有無、`InitializeOnLoad` などの文字列。衣装商品では「意図した同梱か」を確認させる | https://github.com/advisories/GHSA-xq92-f676-63w4 , 市場調査ノート | 確認済。マルウェア判定はしない（「スクリプトが入っています」と事実だけ示す） |

### 検品項目（案。詳細は /vrc-spec）

| 重さ | 項目 |
|---|---|
| 赤（出す前に直す） | 他者アセット本体の混入（lilToon / Poiyomi / MA / VRChat SDK）、`pathname` の異常、同じ zip 内の複数パッケージで同じ GUID に違う中身（インポート順で上書きされる） |
| 黄（確認する） | パッケージ外を参照している GUID（入れ忘れ候補。既知ツールに当たれば「前提ツール」として緑に回す）、スクリプト・DLL・実行ファイルの同梱、解析できないバイナリ資産、説明書・規約ファイルが zip に無い、Assets 直下にフォルダが散らばる、Windows のパス長上限に近い |
| 緑（情報） | 前提ツールの推定結果、同梱物の種類別件数、パッケージごとの差分 |

### この環境で検証できる範囲 / できない範囲

| 検証できる（合成データ・公開リポジトリ） | できない（README に未検証と書く） |
|---|---|
| `tarfile` で作った合成 unitypackage（正常 / 混入 / 参照切れ / 異常パス / GUID 衝突）で全判定 | **黄の「入れ忘れ候補」が本当に入れ忘れか**（Unity 標準・SDK・購入者の環境にある物の可能性。Unity で読み込まないと確定できない） |
| lilToon / MA / Poiyomi の実 `.meta` から作った GUID 辞書で、混入と前提ツール推定 | 実際の Booth 商品の unitypackage での誤検知率（Booth は egress ブロック、有料品は入手不可） |
| cp932 のファイル名を持つ zip の読み取り | 購入者の Unity で本当にピンクや Missing が出るか |
| Windows exe のビルドと起動（既存 CI） | VRChat SDK 部品への参照の判別（SDK を取得できない） |

### 外部依存

- 実行時の依存ライブラリは**なし**（`tarfile` `zipfile` `gzip` `re` は Python 標準）。exe は既存の Windows ビルドの仕組みで作る。
- GUID 辞書はツールに同梱するデータファイル。中身は GUID とパスだけで、他者のコード・シェーダーは含まない。出典リポジトリとライセンス（いずれも MIT）を THIRD_PARTY.md に書く。

### 失敗しやすい点

- **誤検知で信用を失う**: 「入れ忘れ」と断定せず「パッケージの外を参照しています。Unity 標準や前提ツールならそのままで大丈夫です」と書く。既知 GUID（Unity 組み込み、lilToon、MA、Poiyomi）を増やすほど黄が減る。
- **辞書の陳腐化**: lilToon や MA が新しいファイルを足すと GUID が増える。辞書は更新スクリプトで作り直せるようにし、バージョンアップで配る。
- **大きな zip**: 衣装の zip は数百 MB になり得る。展開せず、1 ファイルずつストリームで読む。
- **Defender SmartScreen の警告**: 既存商品と同じ定型説明を README に書く。
- **サポートの重さ**: 「この黄色は何？」に答えなくて済むよう、各項目に「なぜ問題か」「どうすればよいか」を 1〜2 行で必ず付ける。

## Step 3: Go / No-Go

**Go（条件付き）**。

- 差別化: 書き出し後の実物を Unity 無しで検品する道具が無い。他者アセット混入と前提ツール推定は、書き出し補助にも中身確認ツールにも無い。
- 価格根拠: 出品者向けツールの相場が ¥100〜¥1,000。期間限定無料の前例もある。
- 検証可能性: 依存ゼロ、ネットワーク不要、合成データと公開リポジトリの実 GUID で全判定をテストできる。
- 条件: 黄の「入れ忘れ候補」の精度は実商品で確かめられない。**期間限定無料の間に利用者の報告で誤検知を洗い出し、既知 GUID を増やしてから有料化する**。これはオーナーの「問題なければ有料化」の方針と一致する。

## 論点（オーナー確認待ち。回答が無ければ推奨で進める）

### 論点 1: 無料配布のやり方
- **提案**: A) 期間限定無料（例: 2 週間）→ ¥500。商品ページに最初から「○月○日まで無料、以降 ¥500」と書く
- **理由**: Booth のダウンロード商品に「先着○個まで」の在庫数を付けられるかは確認できなかった（booth.pm が egress ブロック。管理画面で確認が必要）。期間限定無料なら確実にでき、同種ツールに前例がある
- **選択肢**: A) 期間限定無料 → ¥500 / B) 先着 N 個無料 → ¥500（在庫設定ができる場合） / C) 最初から ¥500、発売記念で値上げ予告 / D) 無料版（基本チェックのみ）＋有料版 ¥500
- **確認**: どれにしますか？（推奨 A）

### 論点 2: 商品名
- **提案**: 「出品前チェッカー（unitypackage 検品）」（ディレクトリ `upkg-precheck`）
- **理由**: 出品者が検索しそうな「出品前」「unitypackage」「検品」が入る。Booth の名前は商標の懸念があるので商品名に入れず、説明文で「BOOTH 出品前に」と書く
- **選択肢**: A) 出品前チェッカー（unitypackage 検品） / B) パッケージ検品 for VRChat アセット / C) 別案
- **確認**: どれにしますか？

### 論点 3: 最初の版に入れる範囲
- **提案**: 検品（上の赤・黄・緑すべて）＋説明書の下書き出力まで。GUI は作らず、exe にドラッグ＆ドロップ → 結果をコンソールに表示し、zip の隣にレポート（txt と、説明書に貼れる md）を保存
- **理由**: 既存商品と同じ「CLI で動く形を優先」の方針。ドラッグ＆ドロップなら CLI でも使える。GUI は利用者の反応を見て足す
- **選択肢**: A) 提案どおり / B) 検品のみ（下書きは次の版） / C) 最初から GUI（PySide6）
- **確認**: どれにしますか？（推奨 A）
