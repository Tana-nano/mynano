# 出品前チェッカー テスト計画  v0.1

対象: `docs/spec.md` v0.1。`python -m pytest`（リポジトリ直下）で全部通ること。
ネットワーク・Unity・Windows に依存するテストは置かない（exe の起動確認だけ Windows CI の smoke で行う）。

## フィクスチャの作り方

バイナリのフィクスチャはリポジトリに置かず、テスト内で組み立てる。

- `tests/builders.py`
  - `make_unitypackage(entries, *, extra_members=None) -> bytes`: `entries` は `(guid, pathname, asset_bytes | None, meta_text)` の列。
    `tarfile` + `gzip` でメモリ上に作る。`asset_bytes=None` はフォルダ。`extra_members` で異常なメンバー（シンボリックリンク、GUID でない名前、pathname 無し）を足せる。
  - `meta(guid, refs=())`: `.meta` のテキスト（`fileFormatVersion: 2` / `guid: ...` と、任意の参照行）。
  - `mat(shader_guid, tex_guids=())`, `prefab(script_refs=(), material_guids=())`: 参照を持つ最小の YAML（`%YAML 1.1` で始まる）。
  - `make_zip(files, *, sjis_names=())`: `files` は `{名前: bytes}`。`sjis_names` の名前は UTF-8 フラグ無しの cp932 で書く
    （`zipfile.ZipInfo` を継承し `_encodeFilenameFlags` を上書きする。Python の非公開 API に依存するので、テスト内だけで使う）。
- 実在の GUID: 同梱辞書 `known_assets.json` から取る。代表値をテストに定数で持つ（例: lilToon `Shader/lts.shader` = `df12117ecd77c31469c224178886498e`）。
  辞書を作り直して値が消えたらテストが落ちる（辞書の劣化検知を兼ねる）。
- `shared/fixtures/` には何も足さない（この商品専用のデータは商品フォルダの中で完結させる）。

## ユニット

### 読み取り（`unitypackage` モジュール）
| # | 入力 | 期待 |
|---|---|---|
| U01 | 正常なパッケージ（フォルダ 1、prefab 1、mat 1、png 1） | エントリ 4、フォルダ判定、SHA-256、拡張子、テキスト判定が正しい |
| U02 | tar 内のメンバー順がばらばら（asset が pathname より先） | 同じ結果 |
| U03 | pathname に 2 行目がある | 1 行目だけ使う |
| U04 | GUID が大文字 | 小文字に正規化 |
| U05 | gzip でない / 空 / 途中で切れている | P01 用の異常（途中切れは読めた分を返す） |
| U06 | 絶対パス（`/etc/x`、`C:\x`、`\\srv\x`）、`Assets/../x` | P02 用の異常 |
| U07 | シンボリックリンクのメンバー | P03 用の異常 |
| U08 | GUID でない名前、pathname 無し、meta の guid 不一致、`Assets/` 以外で始まる | P14 用の異常 |
| U09 | `--max-text-mb` を超えるテキスト | 参照を抽出せず P13 用の印、SHA-256 は計算済み |
| U10 | ディスクに何も書かない | 実行前後で一時ディレクトリが空のまま |

### 参照抽出（`refs` モジュール）
| # | 入力 | 期待 |
|---|---|---|
| R01 | `m_Shader: {fileID: 4800000, guid: X, type: 3}` | キー `m_Shader`、fileID、GUID |
| R02 | リスト要素 `- {fileID: 2100000, guid: X, type: 2}` | キー無しで抽出 |
| R03 | `.meta` 先頭の `guid: X` | 抽出しない |
| R04 | 全部 0 の GUID | 捨てる |
| R05 | `%YAML` で始まらない `.mat` | 抽出せず P12 用の印 |
| R06 | `.asmdef` の `"GUID:X"` | 抽出する |
| R07 | 負の fileID（プレハブの参照でよく出る） | 抽出する |

### 分類（`classify` モジュール）
| # | 参照 | 期待 |
|---|---|---|
| C01 | 同じ実行の別パッケージにある GUID | 内部 |
| C02 | `0000000000000000e000000000000000` / `...f000...` | 組み込み |
| C03 | 辞書の lilToon シェーダー GUID | 既知（liltoon） |
| C04 | `m_Script` で fileID が `11500000` 以外、GUID 不明 | DLL 内の部品 |
| C05 | `m_Script`、fileID `11500000`、GUID 不明 | 見つからないスクリプト |
| C06 | `m_Shader`、GUID 不明 | 見つからないシェーダー |
| C07 | キー無し、fileID `2800000`、GUID 不明 | 見つからないその他（テクスチャ） |
| C08 | 参照元が 7 件 | 例は `--max-referrers` 件、件数は 7 |

### 既知アセット判定（`known` モジュール）
| # | 入力 | 期待 |
|---|---|---|
| K01 | 辞書の GUID を持つファイル | その id |
| K02 | 辞書に無い GUID で `Packages/com.vrchat.base/x.cs` | vrchat-sdk |
| K03 | 辞書に無い GUID で `Assets/lilToon/New.shader` | liltoon（パス接頭辞） |
| K04 | 自作フォルダ `Assets/Shop/` の下に lilToon の GUID のファイル | ファイルは liltoon、フォルダは判定に使わない |
| K05 | 辞書 JSON の読み込み | 6 id がそろい、各 id に案内文・出典・入手先があり、GUID の重複が無い |

### 検品項目（`checks` モジュール。パッケージ記録から所見を作る純粋関数）
spec の各コードに最低 1 つの「出る」テストと、紛らわしい「出ない」テストを置く。

| # | 状況 | 期待 |
|---|---|---|
| T-P04 | 自作 prefab ＋ lilToon のファイル 3 個 | P04（赤、liltoon、件数 3）。案内文に「非推奨」 |
| T-P04n | 自作のみ、lilToon は参照だけ | P04 なし、P19 に liltoon |
| T-P05 | vrcfury のファイルだけのパッケージ | P05（赤） |
| T-P06 | modular-avatar だけのパッケージ | P06（黄） |
| T-P07 | liltoon だけのパッケージ | P07（緑）。P04 なし |
| T-P08 | `.exe` を含む | P08（赤）。`allow_exe=True` で黄 |
| T-P09/P10 | `.cs` に `[InitializeOnLoad]` | P09 と P10（黄） |
| T-P10n | `.cs` にそれらの語が無い | P09 のみ |
| T-P11 | 見つからないシェーダー / スクリプト / テクスチャ | それぞれの文面で P11（黄）、参照元付き |
| T-P11n | 参照先が別パッケージにある | P11 なし（C01） |
| T-P12/P13/P14 | 読み取り側の印 | 各コード |
| T-P15 | 151 文字の pathname / 150 文字 | 151 で P15、150 で出ない。`max_path` で変えられる |
| T-P16 | `Assets/A/x.png` と `Assets/a/X.png` | P16 |
| T-P17 | `Assets/readme.txt`、`Assets/A/`＋`Assets/B/` | P17。`Assets/A/` と `Assets/lilToon/`（既知）だけなら出ない |
| T-P18 | 中に `.zip` | P18 |
| T-P19 | lilToon と MA を参照 | P19 に固定順で liltoon, modular-avatar |
| T-P20 | DLL 内の部品の参照 | P20（緑） |
| T-P21 | 種類別件数 | prefab / マテリアル / テクスチャ / メッシュ / アニメーション / スクリプト / その他が正しい |
| T-X01 | 2 パッケージで同 GUID・別内容 | X01（赤） |
| T-X01n | 同 GUID・同内容 | X01 なし、X04 の共通に数える |
| T-X02/X03 | 同 GUID・別パス / 同パス・別 GUID | X02 / X03（黄） |
| T-X-known | 既知アセットの GUID が 2 パッケージにある | X01〜X03 に出さない |
| T-order | 赤・黄・緑が混ざる | 赤 → 黄 → 緑、同じ重さはコード順 |

### zip（`archive` モジュール）
| # | 状況 | 期待 |
|---|---|---|
| A01 | unitypackage 2 ＋ README.txt ＋ 利用規約.txt | Z02〜Z04 なし、Z10 に一覧 |
| A02 | unitypackage 無し | Z02 |
| A03 | 説明書・規約なし | Z03・Z04 |
| A04 | `Readme_JP.pdf`、`VN3License.txt`（大文字小文字混在） | Z03・Z04 なし |
| A05 | cp932 の `説明書.txt`（フラグ無し） | 名前を正しく読み直す（Z03 なし）＋ Z05 |
| A06 | UTF-8 フラグ付きの日本語名 | Z05 なし |
| A07 | zip の中の zip の中の unitypackage（深さ 2） | 解析される。`zip_depth=1` なら解析されない |
| A08 | 壊れた zip | Z01（赤） |
| A09 | `max_read_mb` を超える | Z07、途中までの結果 |
| A10 | `__MACOSX/x`、`Thumbs.db` | Z09（緑） |
| A11 | zip 内の `.exe` | Z08（赤）。`allow_exe` で黄 |
| A12 | 暗号化メンバー（ZipInfo のフラグ bit 0 を立てたもの） | Z06 |

### 出力（`report` / `draft` モジュール）
| # | 状況 | 期待 |
|---|---|---|
| O01 | レポート | UTF-8 BOM 付き、入力はファイル名のみ（テストで渡した一時ディレクトリのパス文字列が含まれない）、全項目・例全件 |
| O02 | 下書き | BOM なし、「導入に必要なもの」が固定順、検出なしの節は「（検出されませんでした）」、入手先 URL が辞書どおり |
| O03 | 下書き | lilToon を参照し同梱していない → 「同梱していないもの」に載る |
| O04 | 画面 | 例は最大 3 件、`verbose` で全件。最後に件数の行 |

## 結合（CLI）

`upkg_precheck.cli.main(argv, env)` を呼ぶ（`env` で標準入出力・ドキュメントフォルダ・時刻を差し替える。osc-doctor と同じ作り）。

| # | 状況 | 期待 |
|---|---|---|
| I01 | 正常な zip 1 個、`--out tmp` | 終了コード 0、`tmp/<名前>-<時刻>/report.txt` と `readme-draft.md` ができる |
| I02 | 赤が出る zip | 終了コード 1 |
| I03 | 存在しないパスだけ | 終了コード 2 |
| I04 | フォルダを渡す | 下位の zip と unitypackage を全部調べ、横断比較する |
| I05 | `--no-report --no-draft` | 何も保存しない |
| I06 | `--max-path 0`（範囲外） | 終了コード 2 |
| I07 | `--version` | バージョンと辞書の日付、終了コード 0 |
| I08 | オプション無し・標準入力が端末 | 最後に Enter 待ち。オプション付き・`--no-pause`・端末でないときは待たない |
| I09 | 引数なし | 使い方を表示、終了コード 2 |
| I10 | 保存先に書けない（読み取り専用ディレクトリ） | 終了コード 2、画面の結果は出ている |
| I11 | 入力ファイルが変更されない | 実行前後で SHA-256 と更新日時が同じ |

## 辞書の作成スクリプト（`tools/build_known_assets.py`）

ネットワークを使う取得部と、ディレクトリから辞書を作る部分を分ける。テストするのは後者だけ。

| # | 状況 | 期待 |
|---|---|---|
| D01 | 一時ディレクトリに `.meta` を 3 個（2 タグ分、1 個は GUID が変化） | 和集合で GUID 4 個、パスは新しいタグのもの |
| D02 | 2 つの配布元で同じ GUID | エラーで止まる |
| D03 | `.meta` に guid 行が無い | 飛ばして警告 |

実データでの確認（開発時に 1 回、手順を `tools/README.md` に書く）: 各リポジトリを取得して辞書を作り、件数が
lilToon ≥ 400、Modular Avatar ≥ 900、Poiyomi ≥ 1,200、NDMF ≥ 400、VRCFury ≥ 700（2026-09-30 時点の最新版の `.meta` 数）であることを確かめる。

## Windows ビルド

- `smoke.args` = `--version`（終了コード 0 で合格）。
- `pyinstaller.args` に `--collect-data upkg_precheck`（辞書 JSON を exe に入れる）。

## 手動確認（README の「既知の制限」と一致させる）

- 実際の Booth 商品の zip での誤検知（期間限定無料の間に利用者の報告で確認）。
- Unity で X02・X03 の状況を実際にインポートしたときの挙動。
- VRChat SDK の部品が DLL として参照されるか（`.cs` の部品があると黄になる）。
- exe のコンソールでの日本語表示とドラッグ＆ドロップ（Windows CI では引数付き起動しか確認できない）。
