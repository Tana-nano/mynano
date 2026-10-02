# 出品前チェッカー（unitypackage 検品） 仕様  v0.1

レビュー: 2026-09-30（本物の書き出し lilToon 1.7.0 で tar の内部名と辞書の当たりを確認。VRChat SDK の DLL 識別番号を辞書に追加。パス接頭辞だけの一致を黄に分離。同梱の別パッケージへの参照、フォルダの除外、既知アセット内のスクリプトの扱い、Windows で扱えない名前を追加）

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
  - フォルダ: 直下と下位の `.zip` / `.unitypackage` をすべて調べる（1 回の実行に含める）。表示名はフォルダからの相対パス（区切りは `\`。例 `テスト商品\lilToon.unitypackage`）。
  - 入力が 2 個以上のとき、zip の中のパッケージ名には zip 名を前に付ける（例 `B.zip/Outfit.unitypackage`。フォルダ内のファイルと見分けるため）。それでも同じ名前（同じファイルを 2 回渡した）なら ` (2)` を付ける。
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
- メンバー名の先頭の `./` は取り除く（Unity の版や書き出しツールによって付く・付かないが分かれる。確認済み: lilToon 1.7.0 の書き出しは付かない。出典: https://gist.github.com/yasirkula/dfc43134fbfefb820d0adbc5d7c25fb3 は `./` を除去している）。
- ディレクトリのメンバー（`<guid>` 自体）は読み飛ばす。ルート直下のファイル（`.icon.png` など、GUID ディレクトリの外にあるもの）は無視して件数だけ数える（インポート画面のアイコン。出典: https://github.com/foxscore/add-icon-to-unitypackage）。P14 にはしない。
- `pathname` は UTF-8 として読む（読めない文字は置換し P14）。末尾の改行は取り除き、2 行目以降（`00` などが付くことがある）は捨てる。確認済み: lilToon 1.7.0 の 370 件はすべて 1 行・改行なし。
- フォルダのエントリは `pathname` と `asset.meta` だけを持ち、`.meta` に `folderAsset: yes` がある。`pathname` は末尾に `/` を付けない（例 `Assets/lilToon`）。フォルダ判定は「`asset` が無い」で行い、`folderAsset` は補助に使う。
- GUID ディレクトリのうち `pathname` を持たないもの、`<guid>/` の下に既定の 4 種以外の名前があるものは P14。
- `asset` は全体を読んで SHA-256 を計算する。テキスト解析の対象（下記）だけ、先頭 `--max-text-mb`（既定 64 MB）までメモリに保持する。
  超えたものは「大きすぎて参照を調べていない」と黄で出す。

### 参照の抽出

Unity はアセット間の参照を `{fileID: <数>, guid: <32桁>, type: <数>}` の形で YAML に書く。
出典: https://pkg.go.dev/github.com/r74tech/unitypackage , https://blog.unity.com/engine-platform/understanding-unitys-serialization-language-yaml

- 対象:
  - `asset.meta`（すべて。FBX の材質割り当てなどが入る）
  - `asset` のうち、先頭が `%YAML` で始まるもの（テキスト形式で保存された Unity アセット）
  - `.asmdef` / `.asmref`（JSON 内の `"GUID:<32桁>"`）
- 正規表現（1 行内で完結する前提。Unity の出力はこの形。確認済み: lilToon / Modular Avatar / Poiyomi / VRCFury の全 YAML でこの形以外の `{fileID:` は無かった）:
  `(?:(\w+):\s*)?\{fileID:\s*(-?\d+),\s*guid:\s*([0-9a-fA-F]{32}),\s*type:\s*(\d+)\}`
  - 1 番目のキー名（`m_Shader`、`m_Script` など）は種類の推定に使う。無い（リストの要素 `- {fileID: …}` や `- _FurNoiseMask: {…}`）こともある。
  - `.meta` の中にも参照がある（シェーダーの `defaultTextures`、FBX の材質割り当てなど。確認済み: lilToon のシェーダー `.meta`）。
  - `.meta` 先頭の自分自身の `guid: xxx` は波括弧が無いので拾わない。
  - GUID が全部 0 のものは「参照なし」なので捨てる。
- 拡張子が Unity のシリアライズ形式（`.prefab .mat .asset .controller .overrideController .anim .mask .unity .physicMaterial .playable .signal .lighting .renderTexture .flare .guiskin .fontsettings .spriteatlas .terrainlayer .brush .cubemap`）なのに `%YAML` で始まらないものは
  「バイナリ形式のため参照を調べられない」として黄（Unity の Asset Serialization Mode を Force Text にすれば調べられる。新規プロジェクトの既定は Force Text。出典: https://github.com/JetBrains/resharper-unity/wiki/Asset-serialization-mode）。

### 参照先の分類

参照された GUID ごとに、次の順で 1 つに分類する。

| 分類 | 条件 | 重さ |
|---|---|---|
| 内部 | 参照元と同じ unitypackage に含まれる | —（数えるだけ） |
| 同梱の別パッケージ | 同じ実行で読んだ別の unitypackage にだけ含まれる | 黄（P23。購入者が両方インポートする前提になる） |
| Unity 組み込み | 先頭 16 桁がすべて 0（`0000000000000000e000000000000000` = unity default resources、`...f000...` = unity_builtin_extra。出典: https://github.com/AssetRipper/AssetRipper/issues/1271） | —（数えるだけ） |
| 既知の前提ツール | 既知アセット辞書（下記）に載っている。VRChat SDK の DLL（PhysBone、アバターディスクリプタなど）もここに入る | 緑（「購入者に別途導入してもらうもの」） |
| 不明な DLL 内の部品 | キーが `m_Script` で `fileID` が `11500000` 以外（DLL 内のクラスは fileID が型名のハッシュになる。出典: https://forum.unity.com/threads/yaml-fileid-hash-function-for-dll-scripts.252075/）で、GUID が辞書に無い | 緑（「辞書に無い DLL の部品を使っています。購入者に別途導入してもらうツールがあれば説明書に書いてください」） |
| 見つからないスクリプト | キーが `m_Script` で `fileID` が `11500000` | 黄（「Missing (Script) の原因になります」） |
| 見つからないシェーダー | キーが `m_Shader` | 黄（「ピンク表示の原因になります」） |
| 見つからないその他 | 上のどれでもない | 黄（入れ忘れ候補。種類は fileID から推定: `2100000` マテリアル、`2800000` テクスチャ、`4300000` メッシュ、`7400000` アニメーション、`9100000` アニメーターコントローラー、`4800000` シェーダー、`8300000` オーディオ、`100100000` プレハブ。キー名からも推定: `m_SourcePrefab` プレハブ、`m_Mesh` メッシュ、`m_Avatar` モデル（FBX）、`m_Controller` アニメーターコントローラー、asmdef の参照はアセンブリ定義。fileID の絶対値が 10 億以上はプレハブかモデル（FBX）の中身（FBX 内の部品も大きな値になるため区別しない）。その他は「アセット」） |

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
| vrchat-sdk | VRChat SDK | SDK 本体は取得できない。DLL の GUID だけを固定値で持つ（下記） | — | `Packages/com.vrchat.`, `Assets/VRCSDK/`, `Assets/Udon/`, `Assets/VRChat Examples/` | 同梱不可 |

VRChat SDK の DLL の GUID（アバター向け SDK3）。2 つの独立した情報源で一致したものだけを載せる: (a) Modular Avatar のプレハブが `m_Script` で参照している GUID、(b) SDK 互換の置き換え DLL を配る https://github.com/CMoyuer/VRChatAvatarSDK3Container の `.dll.meta`。

| DLL | GUID |
|---|---|
| VRCSDK3A.dll | `67cc4cb7839cd3741b63733d5adf0442` |
| VRCSDKBase.dll | `db48663b319a020429e3b1265f97aff1` |
| VRC.Dynamics.dll | `cdfe97a8253414b4bb5dd295880489bd` |
| VRC.SDK3.Dynamics.PhysBone.dll | `2a2c05204084d904aa4945ccff20d8e5` |
| VRC.SDK3.Dynamics.Contact.dll | `80f1b8067b0760e4bb45023bc2e9de66` |
| VRCCore-Editor.dll | `4ecd63eff847044b68db9453ce219299` |

ワールド向け SDK（Udon）の DLL は未確認のため載せない（「不明な DLL 内の部品」になる）。

- 各項目に、案内文（日本語）、出典 URL、購入者向けの入手先 URL を持たせる（下記「同梱ルールの根拠」）。
- 辞書は開発用スクリプト `tools/build_known_assets.py` で作る（配布物には含めない）。git で浅く取得し、指定タグの `.meta` から `guid` とパスを集めて**全タグの和集合**にする。
  - Unity が無視するフォルダ（名前が `~` で終わる・`.` で始まる。`UnitTests~` など）は除く。Modular Avatar・NDMF の古いタグは Unity プロジェクトの形で、
    開発用の `Assets/`（テスト用アセット。配布されていない）を含むため除く。VRCFury はタグが 1,500 以上あるため main の最新だけ使う。
  - 2026-09-30 の作成結果: lilToon 439、Poiyomi 1,571、Modular Avatar 465、NDMF 301、VRCFury 749、VRChat SDK 6（合計 3,531）。
  - 確認済み: lilToon 1.7.0 と 2.3.4 で共通 364 ファイルの GUID は不一致 0。Modular Avatar 1.9.0 と最新で共通 181 ファイル不一致 0。Poiyomi 8.1.167 と 10.0.23 で共通 293 ファイル中 4 件が変化 → 和集合で両方を持つ。
  - 確認済み: 本物の書き出し `lilToon_1.7.0.unitypackage`（GitHub リリース、MIT）の 370 個の GUID は、git の `.meta` から作った辞書に 370 個すべて当たった。
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
| P04 | 赤 | 既知アセットの混在: 自作のアセットと同じパッケージに、**GUID が辞書に当たる**既知アセット（id が liltoon / poiyomi / modular-avatar / ndmf / vrcfury / vrchat-sdk）のファイルが入っている | 書き出し時に Include dependencies で一緒に選ばれた可能性。該当 id の案内文を表示し、外して書き出し直す |
| P22 | 黄 | 既知アセットのフォルダ名の下のファイル: GUID は辞書に無いが、pathname が既知アセットのパス接頭辞に一致する（新しい版で増えたファイル、Poiyomi の「ロック」で生成された最適化シェーダー、自作ファイルを配布元のフォルダに置いたもの、のどれか） | 「配布元のフォルダの下にあります。配布元のファイルなら外してください。自分で作ったもの（ロックしたシェーダーなど）なら、自分のフォルダに移すことを検討してください」 |
| P23 | 黄 | 同梱の別パッケージへの参照（分類「同梱の別パッケージ」） | 「購入者が両方インポートする前提です。説明書にインポートの順番を書いてください（共通パッケージ → アバター別パッケージ など）」。下書きの導入手順に反映する |
| P05 | 赤 | 既知アセットだけのパッケージ（下記）に vrcfury か vrchat-sdk が含まれる（単独同梱） | ライセンス上同梱できない。削除して入手先を案内する |
| P06 | 黄 | 既知アセットだけのパッケージに modular-avatar か ndmf が含まれる | 同梱は許可されるが非推奨。公式配布元への案内に替える |
| P07 | 緑 | 既知アセットだけのパッケージに liltoon か poiyomi が含まれる | 配布元が認める「別パッケージのまま同梱」。版が古くないか確認を促す |
| P08 | 赤 | 実行ファイル（`.exe .bat .cmd .ps1 .vbs .scr .msi .com .jar .sh`）が入っている。**既知アセットと判定したエントリも対象** | アバター・衣装の unitypackage には通常入らない。意図しないなら外す |
| P09 | 黄 | `.cs` か `.dll` が入っている。GUID が辞書に当たるエントリ（配布元そのままのファイル）は数えない。パス接頭辞だけの一致は数える | 件数を表示。衣装なら通常入らない。ギミックなら意図どおりか確認 |
| P10 | 黄 | `.cs`（P09 と同じ範囲）に `InitializeOnLoad`、`Process.Start`、`DllImport`、`UnityWebRequest`、`HttpClient`、`WebClient` のどれかがある | 「Unity 起動時に自動で動く / 外部プログラムを起動する / 通信する処理があります」と事実だけ示す（マルウェア判定はしない。出典: https://github.com/advisories/GHSA-xq92-f676-63w4） |
| P11 | 黄 | 見つからないスクリプト・シェーダー・その他の参照（上の分類） | 分類ごとの文面。参照元を示す |
| P12 | 黄 | Unity のシリアライズ形式なのにバイナリ（GUID が辞書に当たるエントリは除く。P13 も同じ） | Force Text にすれば調べられる |
| P13 | 黄 | テキスト解析の上限を超えた | 大きすぎて参照を調べていない |
| P14 | 黄 | `pathname` が `Assets/` でも `Packages/` でも始まらない、GUID 名が 32 桁 16 進でない、`pathname` が無い、`.meta` の guid とディレクトリ名が違う | 書き出し直しを勧める |
| P15 | 黄 | `pathname` の長さが `--max-path`（既定 150 文字）を超える | Windows ではパスが長いと Unity が扱えないことがある。Unity Asset Store の投稿規約も 150 文字未満（出典: https://assetstore.unity.com/publishing/submission-guidelines） |
| P16 | 黄 | Windows で扱えない名前: 大文字小文字だけが違う `pathname` が 2 つ以上ある / 区間の名前が予約名（`CON PRN AUX NUL COM1〜9 LPT1〜9`、拡張子付きも）/ 区間の末尾が空白かドット / 名前に `< > : " \| ? *` を含む | Windows では同じ名前として扱われる、または作れない |
| P17 | 黄 | `Assets/` 直下にファイルがある、または `Assets/` 直下のフォルダ名（ファイルのエントリの `pathname` の 2 番目の区間。フォルダのエントリは数えない。既知アセットのエントリは除く）が 2 つ以上 | 購入者がインポート先を見失いやすい（出典: https://note.com/efk/n/n45ff5ccb5e88 、egress ブロックのため検索要約） |
| P18 | 黄 | `.zip` か `.unitypackage` が unitypackage の中に入っている | 意図どおりか確認 |
| P19 | 緑 | 前提ツールの推定: 参照している既知アセット id（VRChat SDK を含む。同梱している id も載せ、「同梱しています」と添える） | 下書きの「導入に必要なもの」に載る |
| P20 | 緑 | 辞書に無い DLL 内の部品を参照している | 「購入者に別途導入してもらうツールがあれば説明書に書いてください」 |
| P21 | 緑 | 同梱物の集計: 種類別の件数と合計サイズ、`Assets/` 直下のフォルダ名 | 下書きの「同梱物」に載る |

P15〜P18 は自作と判定したエントリ（GUID もパス接頭辞も既知アセットに当たらないもの）だけを対象にする。P08 はすべてのエントリ、P09・P10 は上の表のとおり。

### 複数パッケージの横断（1 回の実行に unitypackage が 2 つ以上あるとき）

| コード | 重さ | 条件 | 要旨 |
|---|---|---|---|
| X01 | 赤 | 同じ GUID で中身（SHA-256）が違う | 購入者が複数インポートすると後から入れた方で上書きされる。対応アバター別パッケージで共通テクスチャなどの版がずれている可能性 |
| X02 | 黄 | 同じ GUID で `pathname` が違う | 後から入れた方の場所に移動される可能性（Unity の実際の動作は未検証） |
| X03 | 黄 | 同じ `pathname` で GUID が違う | 別のアセットとして別名で入る可能性（Unity の実際の動作は未検証） |
| X04 | 緑 | 全パッケージに共通のアセット数と、パッケージごとにしか無いアセット数（既知アセットとフォルダは数えない。数える対象が 1 つも無ければ出さない） | 対応アバター別の差分を把握する |

既知アセットの GUID は X01〜X03 の対象外（P04〜P07 で扱う）。フォルダのエントリも X01〜X03 の対象外（中身が無く、フォルダの GUID は書き出し元のプロジェクトごとに違うのが普通）。

### zip 単位

zip を入力したときだけ判定する（unitypackage 単体の入力には Z 項目を出さない）。

| コード | 重さ | 条件 | 要旨 |
|---|---|---|---|
| Z01 | 赤 | zip として読めない | 作り直す |
| Z02 | 黄 | unitypackage が 1 つも無い | 入れ忘れでないか |
| Z03 | 黄 | 説明書らしいファイルが無い（名前に `readme` `read_me` `read me` `説明` `はじめに` `導入` `manual` `howto` `how_to` を含む `.txt .md .pdf .html .url` が無い。大文字小文字無視） | 購入者の導入トラブルが増える |
| Z04 | 黄 | 利用規約らしいファイルが無い（名前に `規約` `terms` `license` `licence` `eula` `vn3` `利用` を含むファイルが無い） | 規約を同梱するか、商品ページに書いているか確認（VN3 ライセンスなどのテンプレートがある。出典: https://www.moguravr.com/vn3-license/） |
| Z05 | 黄 | UTF-8 フラグの無い日本語ファイル名がある | 海外の Windows や Mac で文字化けする可能性。英数字の名前にするか、UTF-8 で圧縮し直す |
| Z06 | 黄 | 読めないメンバーがある: 暗号化されている、または Python が読めない圧縮方式（Deflate64 など。Windows のエクスプローラーが大きなファイルに使う） | 読めないので検品していない。パスワードなし・通常の圧縮で作り直すと調べられる |
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
【出品前に直すものがあります。赤の項目を直してください。】
結果のページ: C:\Users\…\Documents\UpkgPrecheck\Outfit_v1.0-20260930-221530\report.html
レポート: C:\Users\…\Documents\UpkgPrecheck\Outfit_v1.0-20260930-221530\report.txt
説明書の下書き: C:\Users\…\Documents\UpkgPrecheck\Outfit_v1.0-20260930-221530\readme-draft.md
Enter キーを押すと閉じます…
```

- 並び順: 赤 → 黄 → 緑。同じ重さの中はコードの文字列順（P → X → Z、番号順）。
- 各項目は「何が」「→ なぜ・どうする」を必ず持つ。画面では例を最大 3 件、レポートでは全件。
- 項目と項目の間に空行を入れる。最後に件数の行と、ひとことの判定（赤あり「出品前に直すものがあります…」／黄だけ「直すもの（赤）はありません。黄の項目を確認してください。」／それ以外「問題は見つかりませんでした。」）。
- 色: 本物のコンソールのときだけ、`[赤]` `[黄]` `[緑]` と判定の行に ANSI の色を付ける（Windows では仮想端末処理を有効にできたときだけ。リダイレクトやパイプでは付けない）。色が無くても文字で区別できる。
  Windows の従来のコンソールでの色は未検証（2026-10-02 追加。オーナーの「見やすい画面に」を受けて）。
- `--verbose` でレポートと同じ全件を画面にも出す。

### レポート（report.txt）

- 保存先: `ドキュメント\UpkgPrecheck\<最初の入力の名前（ファイルは拡張子なし、フォルダはフォルダ名）>-YYYYMMDD-HHMMSS\report.txt`（`--out DIR` で親フォルダを変更、`--no-report` で保存しない）。
  入力ファイルの隣には保存しない（zip を作り直すときに一緒に入ってしまうのを防ぐため）。
  ドキュメントフォルダは Windows の既知フォルダ（FOLDERID_Documents。OneDrive で移動されていてもその先）、取れなければ `Path.home() / "Documents"`、無ければカレントディレクトリ。
- UTF-8（BOM 付き。メモ帳で文字化けしないため）。
- 内容: ツールのバージョン、辞書の日付、実行日時、入力ファイル名（**ファイル名のみ。フルパスは書かない**。フォルダ入力は中の各ファイル）・サイズ・SHA-256、結果の件数、全項目（例は全件）、
  パッケージごとの同梱物集計（種類別件数・サイズ・`Assets/` 直下フォルダ）、外部参照の一覧（GUID・分類・参照元）、既知アセットの検出一覧。

### 結果のページ（report.html）

report.txt と同じフォルダに、同じ内容をブラウザで読みやすく並べた `report.html` を保存する（`--no-report` で report.txt と一緒に作らない）。

- UTF-8。CSS は中に書き、スクリプト・外部ファイル・フォントの読み込みは無し（オフラインで開け、何も送信しない）。ファイル名だけを書きフルパスは書かない点は report.txt と同じ。
- 上から: 見出し（バージョン・辞書の日付・実行日時・調べたファイル）→ 判定の帯（最も重い色。件数の丸印付き）→ 赤・黄・緑の節ごとのカード（コード、題、→ の行、例は 3 件まで見せて残りは「ほか N 件を表示」で開閉）→ パッケージごとの同梱物の表 → 外部参照の一覧（パッケージごとに開閉）→ 既知アセットの検出。
- 色だけに頼らず、カードには「赤」「黄」「緑」の文字も付ける。ダークモード（`prefers-color-scheme`）にも合わせる。
- **ドラッグ＆ドロップで起動したとき**（Enter 待ちになる条件と同じ）は、保存後に既定のブラウザで開く（`os.startfile`。Windows での動作は未検証）。オプションを付けた実行では開かない。開けなければ画面にそう出して続ける。

### 説明書の下書き（readme-draft.md）

同じフォルダに保存（`--no-draft` で作らない）。UTF-8（BOM なし）。内容:

```
# （商品名）導入に必要なもの・同梱物【下書き】

> この下書きは出品前チェッカーが unitypackage の中身から作りました。内容を確認して書き直してから使ってください。

## 導入に必要なもの
- VRChat Creator Companion（VCC）で作ったアバター用プロジェクト（VRChat SDK - Avatars）  ← vrchat-sdk の GUID かパスを参照しているとき
- lilToon: https://booth.pm/ja/items/3087170 （公式は VCC からの導入を推奨しています）  ← 検出したものだけ、下の固定順で
- Modular Avatar: https://modular-avatar.nadena.dev/ （NDMF も一緒に入ります）

## 導入手順
1. 「導入に必要なもの」を先に入れてください（シェーダー → ツールの順）。
2. （P23 があるとき）先に共通のパッケージ（○○.unitypackage）をインポートしてください。
3. お使いのアバターに対応した unitypackage をインポートしてください。
4. （ここに着せ方を書いてください）

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
| exe に zip などをドラッグ＆ドロップ | 全項目を調べる → 画面表示 → レポート・結果のページ・下書きを保存 → 結果のページをブラウザで開く → Enter 待ち |
| 引数なし（ダブルクリック） | 使い方（「zip をこのアイコンに重ねてドロップしてください」）を表示して Enter 待ち。終了コード 2 |
| `--out DIR` | 保存先の親フォルダ |
| `--no-report` / `--no-draft` | レポート（report.txt・report.html）/ 下書きを保存しない |
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
5. 画面に出す → レポート・結果のページ・下書きを保存する → ドラッグ＆ドロップなら結果のページを開く。
6. 終了コードを返す。

判定部は入出力から切り離し（パッケージ記録の一覧と設定を受け取り、所見の一覧を返す純粋関数）、テストで直接呼べるようにする。

### 既知アセットの判定

- エントリの GUID が辞書にあればその id。無ければ pathname が id のパス接頭辞に一致すればその id。どちらも無ければ自作。
- フォルダのエントリは判定に使わない（自作フォルダの下に既知アセットのファイルが入ることがあるため、ファイル単位で数える）。
- 「既知アセットだけのパッケージ」= ファイルのエントリが 1 つ以上あり、自作のファイルが 0（GUID の一致とパス接頭辞の一致を合わせて判定）。
  含まれる id ごとに P05〜P07 を出す（Modular Avatar と NDMF を 1 つのパッケージに入れた場合は P06 が 2 件）。
  配布元のパッケージに新しい版のファイルがあるのは普通なので、このときは P22 を出さない。
- 「混在」= 自作のファイルが 1 つ以上あり、既知 id のファイルも 1 つ以上ある → GUID が当たったものは P04（id ごとに 1 件）、パス接頭辞だけのものは P22。

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
- **VRChat SDK の判別はアバター向け SDK3 の DLL 6 個だけ。** SDK 本体を取得できないため（packages.vrchat.com が egress ブロック）、GUID は 2 つの二次情報源の一致で決めた。ワールド向け SDK の DLL、SDK に含まれる `.cs` の部品への参照は「不明な DLL 内の部品」または黄になる。利用者の報告で辞書に足す。
- **本物の書き出しで確認したのは lilToon 1.7.0 の unitypackage 1 個。** `./` 接頭辞付きの書き出し、`.icon.png` 付きの書き出し、pathname に 2 行目がある書き出しは、他ツールのコードから形式を取り込んだだけで実物は未確認。
- **実際の Booth 商品で試したのは 3 個（2026-10-01、Windows 実機確認の W11）。** 明らかな誤検知は無かったが、P11（lilToon マテリアルから外部テクスチャ 2 種）が本当に外部参照かは Unity で確かめていない。誤検知の率は期間限定無料の間に報告を集める。
- 複数パッケージの GUID 衝突（X02・X03）で Unity が実際にどう振る舞うかは未検証。
- バイナリ形式のアセット・FBX の中身・テクスチャの中身は調べない（参照を持たない、または読めない）。
- preview.png は読まない（見た目の偽装は検出しない）。
- Poiyomi の「ロック」で作られた最適化シェーダーは、配布元のフォルダの下に生成されるため P22（黄）になる想定。生成先のフォルダ名の実値は未確認。
- 既知アセット辞書は作成日時点。新しい版で増えたファイルは GUID で判別できず、パス接頭辞だけで判定する（VCC で入れた `Packages/` の場合は判別できる。`Assets/` の下に置き直したものは判別できない）。
- Windows の SmartScreen が初回起動時に警告を出す（2026-10-01 に確認。「詳細情報」→「実行」で起動でき、2 回目以降は出ない。Defender の検出は無し）。
- ドキュメントフォルダを OneDrive に移している PC での保存先は未確認（確認した PC は OneDrive でない `C:\Users\<名前>\Documents` で、既知フォルダの取得が正しく動いた）。
- Shift_JIS の名前の zip（Z05）は、本物の日本語版 Windows の zip では未確認。Windows 11 25H2 のエクスプローラーの「ZIP ファイルに圧縮する」は名前を UTF-8（汎用フラグ 0x800）、圧縮方式を Deflate で書くため、Z05・Deflate64（Z06）の確認にはならなかった。Shift_JIS の zip は Windows 10 の「送る → 圧縮 (zip 形式) フォルダー」などで作られる想定。
- 出力をファイルにリダイレクトすると、コンソールのコードページ（cp932）で表せない文字（NBSP など）は `?` になる（`errors="replace"`。画面への表示は未確認）。
- 「Enter キーを押すと閉じます」で実際に Enter を押して閉じる動作は未確認（実機確認ではキー入力を送れなかった）。

### Windows 実機確認の記録（2026-10-01）

依頼文は `docs/cowork-check.md`。Windows 11 Pro 25H2（ビルド 26200）、Windows ターミナル、コードページ 932、OneDrive でないドキュメントフォルダ。
ドラッグ＆ドロップは、同じ引数で exe を起動する .bat で代替した（画面操作でドラッグできなかったため）。

| 項目 | 結果 |
|---|---|
| W01 ダブルクリック・日本語表示 | OK（文字化けなし） |
| W02 `--version` | OK |
| W03 lilToon 1.7.0 | OK（P07・P19・P21、赤 0 / 黄 0） |
| W04 保存先 | OK（`Documents\UpkgPrecheck\…`。OneDrive の PC は未確認） |
| W05 report.txt | OK（BOM 付き UTF-8、ユーザー名・フルパスなし） |
| W06 Windows 11 の zip | OK（Z04・P07・P19・P21・Z10。名前は UTF-8 だったので Z05 は確認できず） |
| W07 複数同時 | OK。同じ lilToon 2 個で X04 が「共通 0 / 差分 0」と出て分かりにくい → 数える対象が無ければ出さないよう修正 |
| W08 フォルダ | OK。下位フォルダの同名ファイルが `… (2)` と表示されて分かりにくい → フォルダからの相対パスで表示するよう修正 |
| W09 終了コード | OK（0） |
| W10 SmartScreen | 出た（上記） |
| W11 Booth の購入品 3 個 | 明らかな誤検知なし（P11 の 1 件は判断保留） |
| W12 Unity の書き出し | 未実施 |

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
- 本物の書き出し（形式確認用）: https://github.com/lilxyzw/lilToon/releases/download/1.7.0/lilToon_1.7.0.unitypackage （MIT）
- `./` 接頭辞と `.icon.png`: https://gist.github.com/yasirkula/dfc43134fbfefb820d0adbc5d7c25fb3 , https://github.com/foxscore/add-icon-to-unitypackage
- VRChat SDK の DLL GUID（二次情報源）: https://github.com/CMoyuer/VRChatAvatarSDK3Container
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
