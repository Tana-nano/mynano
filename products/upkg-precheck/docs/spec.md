# 出品前チェッカー（unitypackage 検品） 仕様  v0.1

作成日: 2026-09-30 / 企画: `docs/concept.md` / 市場調査: `docs/market/unitypackage-inspector-2026-09.md`

## 概要

Booth に出品する zip（または unitypackage 単体）を exe にドラッグ＆ドロップすると、Unity を使わずに中身を読み、
「出す前に直すもの（赤）」「確認するもの（黄）」「情報（緑）」を日本語で表示する Windows 用ツール。
他者アセット（lilToon / Poiyomi / Modular Avatar / NDMF / VRCFury / VRChat SDK）の混入を識別番号（GUID）とパスで見つけ、
各配布元の同梱ルールを添えて案内する。パッケージの外を参照しているものを集めて「前提ツール」と「入れ忘れ候補」に分ける。
結果はレポート（txt）と、説明書に貼れる「導入に必要なもの・同梱物」の下書き（md）に保存する。
ファイルをディスクへ展開しない。ネットワークに接続しない。入力ファイルを変更しない。

## 対応環境 / 前提ソフト

| 環境 | 対応 |
|---|---|
| Windows 10 / 11（64bit） | ○（exe） |
| Unity・VRChat | 不要（使わない） |
| Meta Quest 単機 | × 動作しない（Windows PC 用ツール） |

- 管理者権限は不要。
- 開発・テストは Python 3.11（標準ライブラリのみ）。Mac / Linux でも `python -m upkg_precheck` で動くが、配布は Windows exe のみ。

## 入力

### コマンドライン引数

- 1 個以上のパス。種類は拡張子で判定する（大文字小文字を無視）。
  - `.zip`: 中のファイルをすべて調べる。zip の中の zip は 1 段だけ開く（`--zip-depth`、既定 2 = 外側＋中 1 段）。
  - `.unitypackage`: 単体で調べる。
  - フォルダ: 直下と下位の `.zip` / `.unitypackage` をすべて調べる（1 回の実行に含める）。
  - それ以外: 「対応していない形式です」と表示して飛ばす（エラーにしない）。
- 1 回の実行に渡したすべての unitypackage を「1 つの商品」として横断比較する（対応アバター別パッケージの比較用）。

### unitypackage の形式

gzip 圧縮の tar。出典: https://github.com/m35/UnityPackageViewer , https://pkg.go.dev/github.com/r74tech/unitypackage

```
<guid>/pathname     1 行目がインポート先のパス（Assets/... または Packages/...）。2 行目以降は無視する
<guid>/asset.meta   .meta（YAML）。フォルダも持つ
<guid>/asset        中身。フォルダには無い
<guid>/preview.png  任意。読まない
```

- `<guid>` は 32 桁の 16 進（小文字に正規化して扱う）。
- tar は**ストリームモード（`r|gz`）で先頭から 1 回だけ読む**。メンバーはメモリ上で処理し、ディスクへ書かない。
  同じ GUID のメンバーは順不同で来るため、GUID ごとに集めて最後に組み立てる。
- `asset` は全体を読んで SHA-256 を計算する。テキスト解析の対象（下記）だけ、先頭 `--max-text-mb`（既定 64 MB）までメモリに保持する。
  超えたものは「大きすぎて参照を調べていない」と黄で出す。

### 参照の抽出

Unity はアセット間の参照を `{fileID: <数>, guid: <32桁>, type: <数>}` の形で YAML に書く。
出典: https://pkg.go.dev/github.com/r74tech/unitypackage , https://blog.unity.com/engine-platform/understanding-unitys-serialization-language-yaml

- 対象:
  - `asset.meta`（すべて。FBX の材質割り当てなどが入る）
  - `asset` のうち、先頭が `%YAML` で始まるもの（テキスト形式で保存された Unity アセット）
  - `.asmdef` / `.asmref`（JSON 内の `"GUID:<32桁>"`）
- 正規表現（1 行内で完結する前提。Unity の出力はこの形）:
  `(?:(\w+):\s*)?\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-fA-F]{32}),\s*type:\s*(\d+)\}`
  - 1 番目のキー名（`m_Shader`、`m_Script` など）は種類の推定に使う。無い（リストの要素）こともある。
  - `.meta` 先頭の自分自身の `guid: xxx` は波括弧が無いので拾わない。
  - GUID が全部 0 のものは「参照なし」なので捨てる。
- 拡張子が Unity のシリアライズ形式（`.prefab .mat .asset .controller .overrideController .anim .mask .unity .physicMaterial .playable .signal .lighting .renderTexture .flare .guiskin .fontsettings .spriteatlas .terrainlayer .brush .cubemap`）なのに `%YAML` で始まらないものは
  「バイナリ形式のため参照を調べられない」として黄（Unity の Asset Serialization Mode を Force Text にすれば調べられる。新規プロジェクトの既定は Force Text。出典: https://github.com/JetBrains/resharper-unity/wiki/Asset-serialization-mode）。

### 参照先の分類

参照された GUID ごとに、次の順で 1 つに分類する。

| 分類 | 条件 | 重さ |
|---|---|---|
| 内部 | 同じ実行で読んだいずれかの unitypackage に含まれる | —（数えるだけ） |
| Unity 組み込み | 先頭 16 桁がすべて 0（`0000000000000000e000000000000000` = unity default resources、`...f000...` = unity_builtin_extra。出典: https://github.com/AssetRipper/AssetRipper/issues/1271） | —（数えるだけ） |
| 既知の前提ツール | 既知アセット辞書（下記）に載っている | 緑（「購入者に別途導入してもらうもの」） |
| DLL 内の部品 | キーが `m_Script` で `fileID` が `11500000` 以外（DLL 内のクラスは fileID が型名のハッシュになる。出典: https://forum.unity.com/threads/yaml-fileid-hash-function-for-dll-scripts.252075/）。VRChat SDK の部品（PhysBone など）が主にここに入る想定 | 緑（「DLL の部品を使っています。VRChat SDK なら購入者の環境にあるので問題ありません」） |
| 見つからないスクリプト | キーが `m_Script` で `fileID` が `11500000` | 黄（「Missing (Script) の原因になります」） |
| 見つからないシェーダー | キーが `m_Shader` | 黄（「ピンク表示の原因になります」） |
| 見つからないその他 | 上のどれでもない | 黄（入れ忘れ候補。種類は fileID から推定: `2100000` マテリアル、`2800000` テクスチャ、`4300000` メッシュ、`7400000` アニメーション、`9100000` アニメーターコントローラー。その他は「アセット」） |

- 見つからない参照は GUID ごとにまとめ、参照しているファイル（pathname）を最大 `--max-referrers`（既定 5）件まで示す。
- 黄の文面は断定しない: 「パッケージの外を参照しています。Unity の標準パッケージや購入者の環境にあるものなら問題ありません。入れ忘れでないか確認してください。」

### 既知アセット辞書

ツールに同梱するデータ `src/upkg_precheck/data/known_assets.json`。中身は GUID・パス・配布元の情報だけで、他者のコードやシェーダーは含まない。

| id | 名前 | 取得元（git） | 使うタグ | パス接頭辞（GUID に無い版の検出用） | 同梱ルール |
|---|---|---|---|---|---|
| liltoon | lilToon | https://github.com/lilxyzw/lilToon | 各 `x.y.0` と最新 | `Assets/lilToon/`, `Packages/jp.lilxyzw.liltoon/` | 別パッケージ可・混在は非推奨 |
| poiyomi | Poiyomi Toon Shader | https://github.com/poiyomi/PoiyomiToonShader | 8.x・9.x・10.x の各最終版と最新 | `Assets/_PoiyomiShaders/`, `Packages/com.poiyomi.toon/` | 別パッケージ可・混在は不可 |
| modular-avatar | Modular Avatar | https://github.com/bdunderscore/modular-avatar | 各 `x.y.0` と最新 | `Packages/nadena.dev.modular-avatar/` | 同梱は非推奨（別パッケージも黄） |
| ndmf | NDMF | https://github.com/bdunderscore/ndmf | 各 `x.y.0` と最新 | `Packages/nadena.dev.ndmf/` | 同梱は非推奨（MA の依存。別パッケージも黄） |
| vrcfury | VRCFury | https://github.com/VRCFury/VRCFury | 最新 | `Packages/com.vrcfury.vrcfury/` | 同梱不可 |
| vrchat-sdk | VRChat SDK | （取得できない。パスのみ） | — | `Packages/com.vrchat.`, `Assets/VRCSDK/`, `Assets/Udon/`, `Assets/VRChat Examples/` | 同梱不可 |

- 各項目に、案内文（日本語）、出典 URL、購入者向けの入手先 URL を持たせる（下記「同梱ルールの根拠」）。
- 辞書は開発用スクリプト `tools/build_known_assets.py` で作る（配布物には含めない）。git で浅く取得し、指定タグの `.meta` から `guid` とパスを集めて**全タグの和集合**にする。
  - 確認済み: lilToon 1.7.0 と 2.3.4 で共通 364 ファイルの GUID は不一致 0。Modular Avatar 1.9.0 と最新で共通 181 ファイル不一致 0。Poiyomi 8.1.167 と 10.0.23 で共通 293 ファイル中 4 件が変化 → 和集合で両方を持つ。
  - 異なる配布元の間で GUID が重複したら、スクリプトはエラーで止まる。
- 辞書のメタ情報として、作成日と各配布元のタグ一覧を JSON に入れ、レポートに「辞書の日付」を表示する。

### 同梱ルールの根拠（案内文に使う）

| id | 原文（要約） | 出典 |
|---|---|---|
| liltoon | 「VRChat 向けの配布物である場合、VCC からのインストールを案内することをオススメします」「同梱する場合は BOOTH のダウンロードページへのショートカットか、ダウンロードしてきたそのままのシェーダーの unitypackage を同梱する方法がオススメ」「シェーダー本体と制作物を 1 つの unitypackage にまとめる方法は、古いバージョンで上書きしてしまう問題が発生する可能性があるため非推奨」 | lilToon リポジトリ Document ブランチ `docs/ja_JP/first.md`（https://lilxyzw.github.io/lilToon/ja_JP/first.html） |
| poiyomi | 「do not include the `_PoiyomiShaders` folder in your asset's package」。リリースページへ案内するか、アセットのパッケージとは別に同梱する | https://github.com/poiyomi/PoiyomiToonShader （README） |
| modular-avatar / ndmf | 同梱はライセンス上許可されるが、非常に古い版を入れたり誤ってダウングレードして他のプレハブを壊す恐れがあるため、公式配布元へ案内することを強く推奨 | https://github.com/bdunderscore/modular-avatar/blob/main/docs~/docs/distributing-prefabs/index.md |
| vrcfury | 商用ライセンスの条件「VRCFury must be downloaded directly by the end user from an official distribution channel」「VRCFury must not be redistributed with your product.」 | https://github.com/VRCFury/VRCFury/blob/main/LICENSE.md |
| vrchat-sdk | SDK は VCC からのみ入手。ライセンスは非譲渡・再許諾不可で第三者への提供を認めない | https://hello.vrchat.com/legal/sdk （egress ブロック、検索要約） |

購入者向けの入手先（下書きに載せる）: lilToon https://booth.pm/ja/items/3087170 （公式ドキュメントは VCC を推奨）、
Poiyomi https://github.com/poiyomi/PoiyomiToonShader/releases 、Modular Avatar https://modular-avatar.nadena.dev/ 、
VRCFury https://vcc.vrcfury.com 、VRChat SDK（VCC） https://vcc.docs.vrchat.com/ 。NDMF は「Modular Avatar と一緒に入ります」と書く。

### zip の読み取り

- Python 標準 `zipfile`。各メンバーをストリームで読み、unitypackage は上記の方法で解析する。
- ファイル名: UTF-8 フラグ（汎用フラグの bit 11）が無く ASCII 以外を含む名前は、`cp437` でバイト列に戻して `cp932` で読み直す。
  読み直せなければ元の表示のまま「文字化けの可能性」として扱う（日本語版 Windows は Shift_JIS でファイル名を保存するため。出典: https://github.com/saberzero1/unzip-jp-gui）。
- 暗号化されたメンバーは読めないので黄。
- 展開後の合計サイズが `--max-read-mb`（既定 8192）を超えたら、そこで読むのをやめて黄（zip 爆弾対策。衣装の zip は数百 MB〜数 GB を想定）。

### 設定ファイル

なし。すべてコマンドラインで指定する（単発で使う道具なので、設定ファイルを増やさない）。

## 検品項目

重さ: **赤** = 出す前に直す / **黄** = 確認する / **緑** = 情報。コードは内部とテストで使い、画面にも表示する。

### unitypackage 単位

| コード | 重さ | 条件 | 画面の文（要旨）と次にすること |
|---|---|---|---|
| P01 | 赤 | 読めない（gzip / tar として壊れている、空） | 書き出し直す |
| P02 | 赤 | `pathname` が絶対パス（`/`・`\`・ドライブ名で始まる）か、`..` の区間を含む | 攻撃や破損の疑い。書き出し直す（出典: https://github.com/Cobertos/unitypackage_extractor/issues/14） |
| P03 | 赤 | tar にシンボリックリンク・ハードリンク・デバイスなど通常ファイル以外がある | 通常の書き出しでは起きない。書き出し直す |
| P04 | 赤 | 既知アセットの混在: 自作のアセットと同じパッケージに、既知アセット（id が liltoon / poiyomi / modular-avatar / ndmf / vrcfury / vrchat-sdk）のファイルが入っている | 書き出し時に Include dependencies で一緒に選ばれた可能性。該当 id の案内文を表示し、外して書き出し直す |
| P05 | 赤 | パッケージ全体が vrcfury か vrchat-sdk だけでできている（単独同梱） | ライセンス上同梱できない。削除して入手先を案内する |
| P06 | 黄 | パッケージ全体が modular-avatar か ndmf だけでできている | 同梱は許可されるが非推奨。公式配布元への案内に替える |
| P07 | 緑 | パッケージ全体が liltoon か poiyomi だけでできている | 配布元が認める「別パッケージのまま同梱」。版が古くないか確認を促す |
| P08 | 赤 | 実行ファイル（`.exe .bat .cmd .ps1 .vbs .scr .msi .com .jar .sh`）が入っている | アバター・衣装の unitypackage には通常入らない。意図しないなら外す |
| P09 | 黄 | `.cs` か `.dll` が入っている | 件数を表示。衣装なら通常入らない。ギミックなら意図どおりか確認 |
| P10 | 黄 | `.cs` に `InitializeOnLoad`、`Process.Start`、`DllImport`、`UnityWebRequest`、`HttpClient`、`WebClient` のどれかがある | 「Unity 起動時に自動で動く / 外部プログラムを起動する / 通信する処理があります」と事実だけ示す（マルウェア判定はしない。出典: https://github.com/advisories/GHSA-xq92-f676-63w4） |
| P11 | 黄 | 見つからないスクリプト・シェーダー・その他の参照（上の分類） | 分類ごとの文面。参照元を示す |
| P12 | 黄 | Unity のシリアライズ形式なのにバイナリ | Force Text にすれば調べられる |
| P13 | 黄 | テキスト解析の上限を超えた | 大きすぎて参照を調べていない |
| P14 | 黄 | `pathname` が `Assets/` でも `Packages/` でも始まらない、GUID 名が 32 桁 16 進でない、`pathname` が無い、`.meta` の guid とディレクトリ名が違う | 書き出し直しを勧める |
| P15 | 黄 | `pathname` の長さが `--max-path`（既定 150 文字）を超える | Windows ではパスが長いと Unity が扱えないことがある。Unity Asset Store の投稿規約も 150 文字未満（出典: https://assetstore.unity.com/publishing/submission-guidelines） |
| P16 | 黄 | 大文字小文字だけが違う `pathname` が 2 つ以上ある | Windows では同じ名前として扱われる |
| P17 | 黄 | `Assets/` 直下にファイルがある、または（既知アセットを除いて）`Assets/` 直下のフォルダが 2 つ以上 | 購入者がインポート先を見失いやすい（出典: https://note.com/efk/n/n45ff5ccb5e88 、egress ブロックのため検索要約） |
| P18 | 黄 | `.zip` か `.unitypackage` が unitypackage の中に入っている | 意図どおりか確認 |
| P19 | 緑 | 前提ツールの推定: 参照している既知アセット id（混入していないもの） | 下書きの「導入に必要なもの」に載る |
| P20 | 緑 | DLL 内の部品を参照している | VRChat SDK の部品である可能性が高い旨 |
| P21 | 緑 | 同梱物の集計: 種類別の件数と合計サイズ、`Assets/` 直下のフォルダ名 | 下書きの「同梱物」に載る |

### 複数パッケージの横断（1 回の実行に unitypackage が 2 つ以上あるとき）

| コード | 重さ | 条件 | 要旨 |
|---|---|---|---|
| X01 | 赤 | 同じ GUID で中身（SHA-256）が違う | 購入者が複数インポートすると後から入れた方で上書きされる。対応アバター別パッケージで共通テクスチャなどの版がずれている可能性 |
| X02 | 黄 | 同じ GUID で `pathname` が違う | 後から入れた方の場所に移動される可能性（Unity の実際の動作は未検証） |
| X03 | 黄 | 同じ `pathname` で GUID が違う | 別のアセットとして別名で入る可能性（Unity の実際の動作は未検証） |
| X04 | 緑 | 全パッケージに共通のアセット数と、パッケージごとにしか無いアセット数 | 対応アバター別の差分を把握する |

既知アセットの GUID は X01〜X03 の対象外（P04〜P07 で扱う）。

### zip 単位

zip を入力したときだけ判定する（unitypackage 単体の入力には Z 項目を出さない）。

| コード | 重さ | 条件 | 要旨 |
|---|---|---|---|
| Z01 | 赤 | zip として読めない | 作り直す |
| Z02 | 黄 | unitypackage が 1 つも無い | 入れ忘れでないか |
| Z03 | 黄 | 説明書らしいファイルが無い（名前に `readme` `read_me` `read me` `説明` `はじめに` `導入` `manual` `howto` `how_to` を含む `.txt .md .pdf .html .url` が無い。大文字小文字無視） | 購入者の導入トラブルが増える |
| Z04 | 黄 | 利用規約らしいファイルが無い（名前に `規約` `terms` `license` `licence` `eula` `vn3` `利用` を含むファイルが無い） | 規約を同梱するか、商品ページに書いているか確認（VN3 ライセンスなどのテンプレートがある。出典: https://www.moguravr.com/vn3-license/） |
| Z05 | 黄 | UTF-8 フラグの無い日本語ファイル名がある | 海外の Windows や Mac で文字化けする可能性。英数字の名前にするか、UTF-8 で圧縮し直す |
| Z06 | 黄 | 暗号化されたメンバーがある | 読めないので検品していない |
| Z07 | 黄 | 読み取り量の上限を超えた | 途中までしか調べていない |
| Z08 | 赤 | zip の中に実行ファイル（P08 と同じ拡張子）がある | ツール商品でなければ外す。**ただしツール商品では意図どおりのことがある**ので文面で触れる |
| Z09 | 緑 | 不要なファイル（`__MACOSX/` `.DS_Store` `Thumbs.db` `desktop.ini` `*.blend1`） | 消してよい |
| Z10 | 緑 | zip の中の unitypackage・その他ファイルの一覧（名前・サイズ） | 下書きの「同梱物」に載る |

Z08 を赤にするのは、衣装・アバターの zip に実行ファイルが入る正当な理由がほぼ無いため。ツール商品を検品する人向けに `--allow-exe` で Z08 と P08 を黄に下げる。

## 出力

### 画面

```
出品前チェッカー 0.1.0（辞書 2026-09-30）
調べています: Outfit_v1.0.zip

Outfit_v1.0.zip
  unitypackage 3 個 / 説明書 1 / 規約 1 / その他 4

[赤] P04 Outfit_Karin.unitypackage に lilToon のファイルが 212 個入っています
       → 書き出し時に「Include dependencies」で一緒に選ばれた可能性があります。lilToon を外して書き出し直してください。
         lilToon の配布元は「シェーダー本体と制作物を 1 つの unitypackage にまとめる方法は非推奨」としています。
[赤] X01 同じ ID で中身が違うファイルが 2 個あります（Outfit_Karin と Outfit_Manuka）
       → Assets/ShopName/Outfit/Textures/Body.png ほか。対応アバター別パッケージで版がずれていないか確認してください。
[黄] P11 パッケージの外のシェーダーを参照しています（1 種類、マテリアル 3 個）
       → ピンク表示の原因になります。…（参照元: Assets/ShopName/Outfit/Materials/Lace.mat ほか 2 件）
[黄] Z05 日本語のファイル名が Shift_JIS で保存されています（3 個）
       → …
[緑] P19 購入者に必要なもの: lilToon, Modular Avatar
[緑] P20 DLL の部品を使っています（14 か所。VRChat SDK なら問題ありません）

結果: 赤 2 / 黄 2 / 緑 2
レポート: C:\Users\…\Documents\UpkgPrecheck\Outfit_v1.0-20260930-221530\report.txt
説明書の下書き: C:\Users\…\Documents\UpkgPrecheck\Outfit_v1.0-20260930-221530\readme-draft.md
Enter キーを押すと閉じます…
```

- 並び順: 赤 → 黄 → 緑。同じ重さの中はコード順。
- 各項目は「何が」「→ なぜ・どうする」を必ず持つ。画面では例を最大 3 件、レポートでは全件。
- 表示はプレーンテキスト（色は付けない。exe のコンソールで確実に読めるため）。
- `--verbose` でレポートと同じ全件を画面にも出す。

### レポート（report.txt）

- 保存先: `ドキュメント\UpkgPrecheck\<最初の入力のファイル名（拡張子なし）>-YYYYMMDD-HHMMSS\report.txt`（`--out DIR` で親フォルダを変更、`--no-report` で保存しない）。
  入力ファイルの隣には保存しない（zip を作り直すときに一緒に入ってしまうのを防ぐため）。
  ドキュメントフォルダは `Path.home() / "Documents"`、無ければカレントディレクトリ。
- UTF-8（BOM 付き。メモ帳で文字化けしないため）。
- 内容: ツールのバージョン、辞書の日付、実行日時、入力ファイル名（**ファイル名のみ。フルパスは書かない**）・サイズ・SHA-256、結果の件数、全項目（例は全件）、
  パッケージごとの同梱物集計（種類別件数・サイズ・`Assets/` 直下フォルダ）、外部参照の一覧（GUID・分類・参照元）、既知アセットの検出一覧。

### 説明書の下書き（readme-draft.md）

同じフォルダに保存（`--no-draft` で作らない）。UTF-8（BOM なし）。内容:

```
# （商品名）導入に必要なもの・同梱物【下書き】

> この下書きは出品前チェッカーが unitypackage の中身から作りました。内容を確認して書き直してから使ってください。

## 導入に必要なもの
- VRChat Creator Companion（VCC）で作ったアバター用プロジェクト（VRChat SDK - Avatars）  ← DLL の部品か vrchat-sdk を参照しているとき
- lilToon: https://booth.pm/ja/items/3087170 （公式は VCC からの導入を推奨しています）  ← 検出したものだけ、下の固定順で
- Modular Avatar: https://modular-avatar.nadena.dev/ （NDMF も一緒に入ります）

## 導入手順
1. 「導入に必要なもの」を先に入れてください（シェーダー → ツールの順）。
2. お使いのアバターに対応した unitypackage をインポートしてください。
3. （ここに着せ方を書いてください）

## 同梱物
| ファイル | 内容 |
|---|---|
| Outfit_Karin.unitypackage | プレハブ 2、マテリアル 6、テクスチャ 12、メッシュ（FBX）1 |
| README.txt | |

## 同梱していないもの
- lilToon 本体（上の入手先から導入してください）
```

- 「導入に必要なもの」は、P19 の検出順ではなく次の固定順: VRChat SDK → lilToon → Poiyomi → Modular Avatar（NDMF 含む）→ VRCFury。
- 何も検出しなかった節は「（検出されませんでした）」と書く。
- ツール名・作者名・AI ツール名などは入れない（冒頭の注意書きのツール名だけ）。

### 終了コード

`0` = 赤なし、`1` = 赤あり、`2` = ツール自体のエラー（引数不正、入力が 1 つも読めない、保存先に書けない）。

## 画面 / CLI

実行ファイル `upkg-precheck.exe`。Python では `python -m upkg_precheck`。

| 起動方法 / オプション | 動作 |
|---|---|
| exe に zip などをドラッグ＆ドロップ | 全項目を調べる → 画面表示 → レポートと下書きを保存 → Enter 待ち |
| 引数なし（ダブルクリック） | 使い方（「zip をこのアイコンに重ねてドロップしてください」）を表示して Enter 待ち。終了コード 2 |
| `--out DIR` | 保存先の親フォルダ |
| `--no-report` / `--no-draft` | レポート / 下書きを保存しない |
| `--max-path N` | P15 のパス長の上限（既定 150。根拠: Unity Asset Store 投稿規約。5〜1000） |
| `--max-text-mb N` | 参照を調べるテキストの 1 ファイルあたりの上限（既定 64。1〜1024） |
| `--max-read-mb N` | zip から読む合計量の上限（既定 8192。1〜65536） |
| `--max-referrers N` | 参照元の表示件数（既定 5。1〜100） |
| `--zip-depth N` | zip の中の zip を開く深さ（既定 2。1〜3） |
| `--allow-exe` | P08 / Z08 を黄に下げる（ツール商品の検品用） |
| `--verbose` | 全件を画面にも出す |
| `--no-pause` | 終了時に Enter を待たない |
| `--version` | バージョンと辞書の日付を表示して終了（終了コード 0） |

- Enter 待ちは「オプションを 1 つも付けずに起動したとき」（ドラッグ＆ドロップとダブルクリック）で、かつ標準入力が端末のときだけ。
- 各既定値の範囲外はエラー（終了コード 2）。

## 状態遷移・主要ロジック

1. 引数を展開して入力の一覧を作る（フォルダは下位を探索）。読めないパスは画面に出して飛ばす。
2. 各入力を順に読む。zip はメンバーを列挙し、unitypackage・zip（深さ内）・その他に分ける。unitypackage は解析して「パッケージ記録」を作る。
   - パッケージ記録: 名前（zip 内のパス）、エントリ（GUID、pathname、フォルダか、サイズ、SHA-256、拡張子、テキストか、抽出した参照）、異常の一覧。
3. すべて読み終えたら、全パッケージの GUID 集合を作り、参照を分類する（内部判定は実行全体で行う）。
4. 各検品項目を判定して「所見」（コード、重さ、対象、件数、例、文面）の一覧を作る。
5. 画面に出す → レポート・下書きを保存する。
6. 終了コードを返す。

判定部は入出力から切り離し（パッケージ記録の一覧と設定を受け取り、所見の一覧を返す純粋関数）、テストで直接呼べるようにする。

### 既知アセットの判定

- エントリの GUID が辞書にあればその id。無ければ pathname が id のパス接頭辞に一致すればその id。どちらも無ければ自作。
- フォルダのエントリは判定に使わない（自作フォルダの下に既知アセットのファイルが入ることがあるため、ファイル単位で数える）。
- 「パッケージ全体が単独の id」= ファイルのエントリが 1 つ以上あり、すべてが同じ 1 つの id。
- 「混在」= 自作のファイルが 1 つ以上あり、既知 id のファイルも 1 つ以上ある → P04（id ごとに 1 件）。

## エラーと復旧

| 状況 | 動作 |
|---|---|
| 入力パスが無い・読めない | その入力を飛ばし、画面に出す。全部だめなら終了コード 2 |
| unitypackage が壊れている | P01（赤）を出して次へ |
| 途中で壊れている（tar の途中でエラー） | 読めたところまでで判定し、P01 に「途中で読めなくなりました」と添える |
| zip が壊れている | Z01（赤） |
| 保存先に書けない | 画面に理由を出し、終了コード 2（画面の結果はそのまま見られる） |
| 辞書が読めない（exe の破損） | エラーを出して終了コード 2 |
| 想定外の例外 | 画面に「予期しないエラー」と例外の種類・メッセージを出し、終了コード 2。レポートは書けるところまで書く |

## 設定項目一覧

コマンドラインのみ（上の CLI 表）。環境変数 `UPKG_PRECHECK_DOCS` でドキュメントフォルダの場所を上書きできる（テスト用・特殊環境用）。

## 既知の制限・未検証事項

- **黄の「入れ忘れ候補」が本当に入れ忘れかは確定できない。** Unity の標準パッケージ（`com.unity.*`）や、購入者の環境にある他のアセットを参照している場合も黄になる。Unity で読み込まないと確定できない。
- **VRChat SDK の部品は GUID で判別していない。** SDK を取得できないため（packages.vrchat.com が egress ブロック）。DLL 内の部品として緑で数える。SDK が `.cs` のスクリプトを持つ部品を参照している場合は黄になる（誤検知）。利用者の報告で直す。
- **実際の Booth 商品で試していない。** 誤検知の率は未検証。期間限定無料の間に報告を集める。
- 複数パッケージの GUID 衝突（X02・X03）で Unity が実際にどう振る舞うかは未検証。
- バイナリ形式のアセット・FBX の中身・テクスチャの中身は調べない（参照を持たない、または読めない）。
- preview.png は読まない（見た目の偽装は検出しない）。
- Poiyomi の「ロック」で作られた最適化シェーダーをパッケージに入れた場合の扱い（自作扱いになる）が正しいかは未確認。
- 既知アセット辞書は作成日時点。新しい版で増えたファイルは GUID で判別できず、パス接頭辞だけで判定する（VCC で入れた `Packages/` の場合は判別できる。`Assets/` の下に置き直したものは判別できない）。
- Windows の SmartScreen が初回起動時に警告を出すことがある（既存商品と同じ）。

## セキュリティ / プライバシー

- 入力ファイルを書き換えない。ディスクへ展開しない。スクリプトを実行しない。ネットワークに接続しない。
- レポートには入力のファイル名だけを書き、フルパス（Windows のユーザー名を含む）を書かない。画面には保存先のフルパスを出す（利用者本人の画面なので）。
- 他人の表示名・ユーザー ID は扱わない。
- tar のメンバー名・`pathname` は表示に使うだけで、ファイルシステムのパスとして使わない（P02 の検出はするが、それ以外で解釈しない）。

## 出典

- unitypackage の形式: https://github.com/m35/UnityPackageViewer , https://pkg.go.dev/github.com/r74tech/unitypackage
- Unity YAML と参照: https://blog.unity.com/engine-platform/understanding-unitys-serialization-language-yaml
- 組み込みリソースの GUID: https://github.com/AssetRipper/AssetRipper/issues/1271
- DLL 内スクリプトの fileID: https://forum.unity.com/threads/yaml-fileid-hash-function-for-dll-scripts.252075/
- Asset Serialization Mode の既定: https://github.com/JetBrains/resharper-unity/wiki/Asset-serialization-mode
- パス長（150 文字未満）: https://assetstore.unity.com/publishing/submission-guidelines
- pathname の攻撃: https://github.com/Cobertos/unitypackage_extractor/issues/14
- Unity パッケージのマルウェア例: https://github.com/advisories/GHSA-xq92-f676-63w4
- lilToon: https://github.com/lilxyzw/lilToon （Document ブランチ `docs/ja_JP/first.md`、MIT）
- Poiyomi: https://github.com/poiyomi/PoiyomiToonShader （README、MIT）
- Modular Avatar: https://github.com/bdunderscore/modular-avatar （`docs~/docs/distributing-prefabs/index.md`、MIT）
- NDMF: https://github.com/bdunderscore/ndmf （MIT）
- VRCFury: https://github.com/VRCFury/VRCFury/blob/main/LICENSE.md
- VRChat SDK ライセンス: https://hello.vrchat.com/legal/sdk （検索要約）
- zip の日本語ファイル名: https://github.com/saberzero1/unzip-jp-gui
- インポート先フォルダの問題提起: https://note.com/efk/n/n45ff5ccb5e88 （検索要約）
- VN3 ライセンス: https://www.moguravr.com/vn3-license/ （検索要約）
