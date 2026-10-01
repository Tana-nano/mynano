# アップロードドクター for VRChat 仕様  v0.1

レビュー: 2026-09-30（Editor.log が別プロジェクト・過去のものである可能性への対処、エラーの重複排除、`Library/PackageCache` 由来の分類、Unity 側 `Packages/manifest.json` の破損、不足型のヒント表、伏せ字のパス正規化、自己診断の一時フォルダを追記）

実装反映: 2026-09-30（下記「実装時の決定」参照。規則表の項目、コンパイルエラーの正規表現、追加の判定 ID、伏せ字の範囲）

作成日: 2026-09-30 / 企画: `docs/concept.md` / 市場調査: `docs/market/system-tool-candidates-2-2026-09.md`

## 概要

Unity で VRChat のアバターを上げようとして失敗したとき、Unity を開かずに**プロジェクトのフォルダと `Editor.log` を読み取り専用で点検**し、
アップロードや SDK パネルの妨げになっている**原因の候補を、確からしさの順に日本語で表示**する Windows 用ツール。
各候補には根拠（どのファイル・どの行か）と「次にすること」を付ける。結果はサポートに貼れるレポート（txt、個人が特定される情報は伏せ字）にも保存する。
プロジェクトは書き換えない。通信しない。常駐しない。無料配布。

**できないこと（README の先頭にも書く）**: シーンの中身（Avatar Descriptor の有無、ボーン構成、ポリゴン数、パラメータ容量）の検証はしない。
それは Unity 内の VRChat SDK パネルの役目。本ツールは「Unity が赤いエラーで壊れている／SDK パネルが出ない／アップロードが通らない」ときの切り分け用。

## 対応環境 / 前提ソフト

| 環境 | 対応 |
|---|---|
| Unity を動かす Windows PC | ○ |
| PC VR / デスクトップの区別 | なし（VRChat を起動する必要がない） |
| Meta Quest 単機（PC なし） | × 非対応（Unity は PC で動かす） |
| Quest 向け（Android）ビルドの検証 | 対象外 |

- Windows 10 / 11（64bit）。管理者権限は不要。
- 対象は VRChat SDK3（Avatars / Worlds）の Unity プロジェクト。Unity 本体・VRChat SDK・他者アセットは同梱しない。

## 入力

すべて読み取りのみ。読むファイルは次の表に限る（`Library/` や画像・モデル本体は読まない）。

### プロジェクトフォルダ

指定方法（優先順）: ① コマンドラインの位置引数 `PROJECT`（フォルダを exe にドラッグ＆ドロップすると渡される） ② 引数なしで起動した場合は「Unity プロジェクトのフォルダをここにドラッグして Enter」と表示して 1 行入力（コンソールにフォルダをドロップするとパスが貼られる。前後の `"` `'` と、PowerShell が付ける先頭の `& ` は除去）。

Unity プロジェクトの判定: 直下に `Assets/` と `ProjectSettings/` がある。無ければ「Unity プロジェクトのフォルダではありません」を表示し、**直下の 1 階層下**に判定を満たすフォルダがあれば「このフォルダではありませんか」と候補を出して終了コード 2。

| 読むもの | 取り出す項目 | 備考 |
|---|---|---|
| `ProjectSettings/ProjectVersion.txt` | 行 `m_EditorVersion: <版>`（キーの完全一致。`m_EditorVersionWithRevision` は使わない） | 形式は Unity 公式が egress ブロックで**未確認**（一般に知られる形）。読めなければ P_UNITY_UNREADABLE |
| `Packages/manifest.json`（Unity 側の UPM マニフェスト） | JSON として読めるかだけ | 壊れていると Unity がプロジェクトを開けない。中身（`dependencies`）は判定に使わない |
| `Packages/vpm-manifest.json` | `dependencies.<id>.version`, `locked.<id>.version`, `locked.<id>.dependencies` | 形は https://vcc.docs.vrchat.com/vpm/resolver/ の検索要約（egress ブロック）。**実物未確認**。JSON として壊れていれば P_VPM_BROKEN |
| `Packages/<id>/package.json` | `name`, `version`, `vpmDependencies`（あれば） | `<id>` は `Packages/` 直下のフォルダ名。項目名 `vpmDependencies` は https://github.com/vrchat-community/vpm-package-template の要約による。**実物未確認** |
| `ProjectSettings/ProjectSettings.asset` | テキスト全体から `VRC_SDK_VRCSDK2` / `VRC_SDK_VRCSDK3` / `UDON` の語を検索 | YAML の構造は解釈しない（語の有無だけ）。バイナリ形式（Force Text でない）なら「読めません」の情報 |
| `Assets/` 直下と、その 2 階層下までの**フォルダ名** | `VRCSDK`, `Udon`, `DynamicBone*` など | ファイルの中身は読まない。走査は最大 20,000 エントリで打ち切り（打ち切ったらレポートに明記） |
| プロジェクトのパス文字列、`%USERPROFILE%` | 非 ASCII 文字の有無 | — |

### Editor.log

- 既定: `%LOCALAPPDATA%\Unity\Editor\Editor.log`（出典: 検索要約 https://docs.unity3d.com/ja/2018.4/Manual/LogFiles.html ／ Unity 公式は egress ブロック、**最新版は未確認**）。`--editor-log PATH` で変更できる（Editor-prev.log を渡す用途など）。
- 無ければ L_NOT_FOUND（情報）で続行し、プロジェクト診断だけ行う。
- **Editor.log は「最後に起動した Unity」のログであり、指定したプロジェクトのものとは限らず、直したあとの古いエラーも残っている。** そのため:
  - ログの先頭付近（最初の 200 行）から `-projectPath` / `-projectpath` に続くパス（`"` 囲みあり・なし。同じ行に続く場合と、`-projectpath` だけの行の次の空でない行にある場合の両方）を探し、指定プロジェクトと比較する（区切り文字 `\` `/`・大文字小文字・末尾の区切りを正規化）。一致 → 「対象プロジェクト: 一致」、不一致 → L_OTHER_PROJECT（注意）を出し、**ログ由来（`L_` で始まる）候補の確からしさを全部「低」に落とす**。見つからない → 「不明」と表示し、確からしさは変えない。（Unity が起動時にコマンドライン引数をログに書くことは**未検証**。見つからなければ「不明」になるだけで、誤検知はしない）
  - ログの更新日時が 7 日より前なら L_OLD_LOG（情報）「この Editor.log は N 日前のものです」。
  - コンパイルエラーは Unity が再コンパイルのたびに同じ行を繰り返し書くため、**(file, line, col, code) で重複を除いた件数**を「N 件（延べ M 回）」の形で出す。
  - 「ログにある＝今も出ている」ではないことを、ログ由来の候補の末尾に 1 行で必ず添える（「Unity を開いてコンソールで再確認してください」）。
- 文字コードは UTF-8（不正なバイトは置換）。ファイルが 50 MB を超えるときは**末尾の 50 MB だけ**を読む（レポートに明記）。
- 行の認識（規則表 `rules.json` の `log_rules` で定義。コードに直書きしない）:

| 種別 | パターン | 出典 |
|---|---|---|
| C# コンパイルエラー | 規則表の `compile_error_regex`。初期値 `(?P<file>(?:Assets|Packages|Library)[\\/][^\r\n:]*?\.cs)\((?P<line>\d+),(?P<col>\d+)\): error (?P<code>CS\d+): (?P<msg>.*)$`（行頭は固定しない。ファイルは `Assets` `Packages` `Library` のどれかで始まる `.cs` だけ。**フォルダ名の空白・括弧を許す**。区切りは `/` と `\` の両方） | 例: `Assets/VRCSDK/SDK3/Runtime/UnityEventFilter.cs(1018,24): error CS0246: The type or namespace name 'Cinemachine' could not be found …`（検索要約 https://ask.vrchat.com/t/errors-in-unity-sdk/12433 ほか） |
| ビルド/検証の失敗メッセージ | `Failed to build avatar`, `Avatar validation failed` | 公開質問の文言（検索要約 https://ask.vrchat.com/t/avatar-validation-failed/25422 ほか）。**完全一致でない可能性**があるので部分一致で扱う |
| 所有者違いの ID | `Attempted to load the data for an avatar we do not own, clearing blueprint id` | 同上（https://ask.vrchat.com/t/unity-vcc-console-error-when-uploading-avatar/23286 の検索要約） |
| アップロード UI の例外 | `NullReferenceException` の近傍 5 行以内に `CreateContentInfoGUI` | https://feedback.vrchat.com/sdk-bug-reports/p/avatar-upload-shows-successful-but-does-not-appear-on-vrchat-sdk-39x-3100 の検索要約 |

- 上記の実ログでの現れ方（行頭の `[Error]` や時刻の有無など）は**未検証**。パターンは行のどこにあっても一致する部分一致で書く。規則表の正規表現は**大文字小文字を区別しない**。
- `Assets` 等で始まらないパスのコンパイルエラー（`error CS####` を含むが上の正規表現に一致しない行）は「error CS####」を種類として L_UNCLASSIFIED に回す。
- 未分類のエラー（`error CS` 以外で、`\w+(Exception|Error)\b` に一致する語を含み、かつ空白＋`at ` で始まらない行＝スタックフレームを除く）は、その語を「種類」として集計して L_UNCLASSIFIED に回す。
  - ただし `Start importing ` で始まる行（アセットの読み込み記録）は除く。また、語の直前が `/` `\`、直後が `.拡張子` のもの（`VRCApiError.cs` のようなファイル名）は数えない。（2026-10-01 実機試験: 新規プロジェクトで、ファイル名に Error / Exception を含むスクリプトの読み込み記録 13 行が誤検出された）

### 規則表 `rules.json`

パッケージ内に同梱（`src/upload_doctor/rules.json`）。`--rules PATH` で差し替え可能（SDK の変更に追随して更新するため）。形:

```json
{
  "schema": 1,
  "checked_on": "2026-09-30",
  "unity": {"supported": ["2022.3.22f1"], "source": "<URL>"},
  "sdk": {"min_avatars_for_new_upload": "3.9.0", "confidence": "low", "source": "<URL>"},
  "compile_error_regex": "<上の表の正規表現。名前付きグループ file / line / col / code / msg が必須>",
  "folder_rules": [
    {"id": "dynamic_bone", "under": "Assets", "name_glob": "Dynamic*Bone*", "max_depth": 2,
     "level": "info", "confidence": "low", "title": "…", "advice": ["…"], "source": "<URL or 解説記事>"}
  ],
  "log_rules": [
    {"id": "upload.validation_failed", "regex": "Avatar validation failed",
     "level": "warn", "confidence": "low", "title": "…", "advice": ["…"], "source": "<URL>"},
    {"id": "upload.contentinfo_nre", "regex": "CreateContentInfoGUI",
     "near_regex": "NullReferenceException", "near_lines": 5, "…": "…"}
  ],
  "missing_type_hints": [
    {"match": ["DynamicBone"], "exact": [], "hint": "…", "confidence": "low", "source": "<URL>"}
  ],
  "overrides": {"P_DYNAMIC_BONE": {"level": "warn"}, "L_UPLOAD_MSGS": {"confidence": "mid"}}
}
```

- `unity.supported` は 1 個以上。先頭を「推奨」として表示し、いずれかに完全一致すれば OK。
- `folder_rules` の `name_glob` は大文字小文字を区別しない。`max_depth` は 1〜2（Assets 直下が 1）。`under` は `Assets` だけ。
- `log_rules` の `near_regex` を持つ規則は、`regex` に一致した行の前後 `near_lines` 行以内に `near_regex` の行があるときだけ数える。
- `overrides` は判定 ID（`L_UPLOAD_MSGS/<規則 ID>` は `L_UPLOAD_MSGS` でも可）ごとに `level` / `confidence` を上書きする。
- `missing_type_hints` は L_MISSING_TYPE の不足名に対する短いヒント（`match` は前方一致、`exact` は完全一致。どちらも大文字小文字無視。上から順に最初に当たったもの）。初期値は `DynamicBone`, `VRC.SDK3` 系（→ SDK 未導入）, `nadena.dev.modular_avatar` / `ModularAvatar`（→ Modular Avatar 未導入）, `VRCFury`, `lilToon`, `Cinemachine`（→ Unity パッケージ `com.unity.cinemachine`）の 6 系統に限る。**全部 confidence low**。表に無い名前はヒント無しで名前だけ出す。
- `level`: `ng` / `warn` / `info`。`confidence`: `high` / `mid` / `low`（下の定義）。読み込み時に検証し、不正なら終了コード 2 とどこが不正かを表示。
- `checked_on` から 90 日を超えたら、画面とレポートに「規則表は YYYY-MM-DD 時点です。古い可能性があります」を出す（情報）。

**確からしさ（confidence）の定義 — 主観で付けない**

| 値 | 表示 | 意味 |
|---|---|---|
| high | 高 | 公式ドキュメント（creator-docs 原文）にその原因が明記されている |
| mid | 中 | 公式に近い記述はあるが、条件や実物での現れ方が未確認 |
| low | 低 | 解説記事・質問サイトなど公式以外の情報のみ |

## 出力

### 画面

```
アップロードドクター for VRChat 0.1.0
プロジェクト: <PROJECT>
Editor.log: あり（2026-09-30 21:40、12,345 行、対象プロジェクト: 一致）

原因の候補（上ほど可能性が高い順）
 1. [NG]   確からしさ:高  Unity のバージョンが VRChat の推奨と違います（2019.4.31f1 / 推奨 2022.3.22f1）
             根拠: ProjectSettings/ProjectVersion.txt
             → 推奨版の Unity で開き直してください。Unity Hub の「アップグレードしますか」には従わないでください
 2. [NG]   確からしさ:高  Assets 内のスクリプトがコンパイルエラーです（3 件、延べ 12 回。SDK パネルが出ない原因になります）
             根拠: Assets/Foo/Bar.cs(10,5) error CS0246: The type or namespace name 'DynamicBone' could not be found ほか
             → 足りないパッケージの導入、または該当アセットの削除
             ※ ログにある＝今も出ているとは限りません。Unity を開いてコンソールで再確認してください
 3. [注意] 確からしさ:低  旧 Dynamic Bone のフォルダがあります（Assets/DynamicBone）
             …
問題なしの項目: SDK パッケージ 3 個が manifest と一致

レポートを保存しました: C:\Users\…\Documents\UploadDoctor\report-20260930-221530.txt
Enter キーを押すと閉じます…
```

- 状態は `NG`（アップロードや SDK パネルを妨げる）/ `注意`（原因になりうる）/ `情報` / `OK`。
- 並べ替え: ①状態（NG > 注意 > 情報） ②確からしさ（高 > 中 > 低） ③根拠の件数が多い順 ④ID の辞書順。**OK は候補に含めず、最後に 1 行で要約**する。
- 各候補は「タイトル」「確からしさ」「根拠（最大 3 行）」「次にすること（1〜3 行）」。低の候補には「公式以外の情報にもとづく、または前提を確かめられない推測です。断定はできません」を必ず付ける。ただし別プロジェクトのログのために低へ下げた候補には、代わりに「別のプロジェクトのログのため、確からしさを「低」に下げています」を付ける。
- `--verbose` で根拠を全件（上限 20 件/候補）、読んだファイル一覧、Editor.log の種類別件数も出す。

### レポート（txt）

- 保存先: `ドキュメント\UploadDoctor\report-YYYYMMDD-HHMMSS.txt`（`--out <dir>` で変更、`--no-report` で保存しない）。UTF-8（BOM 付き）。
- 内容: ツールのバージョン、実行日時、Windows のバージョン（`Windows 11 (10.0.26200)` の形。Python 3.11 は Windows 11 を release `10` と返すため、ビルド番号 22000 以上を 11 と表示する）、規則表の日付、Unity のバージョン、`com.vrchat.*` と他の VPM パッケージの ID とバージョン一覧、Editor.log の行数・エラー件数・種別、全候補（`--verbose` 相当）。
- **根拠の引用行**は 1 行 200 文字まで、全体で 60 行まで。超えたら「ほか N 件」。
- 末尾に 1 行だけ作者の他のツールの案内（「VRChat の OSC が動かないときの『OSCドクター』もあります（Booth）」）。
- 伏せ字（プライバシー参照）を必ず通す。

## 画面 / CLI

実行ファイル `upload-doctor.exe`。

| 起動方法 / オプション | 動作 |
|---|---|
| フォルダをドラッグ＆ドロップ | 診断 → 画面表示 → レポート保存 → Enter 待ち（引数の位置引数 `PROJECT` と同じ） |
| ダブルクリック（引数なし） | フォルダ入力を促す → 上と同じ |
| `PROJECT` | Unity プロジェクトのフォルダ |
| `--editor-log PATH` | Editor.log の場所（既定は `%LOCALAPPDATA%\Unity\Editor\Editor.log`） |
| `--rules PATH` | 規則表 JSON を差し替え |
| `--verbose` | 根拠の全件・読んだファイル・種別件数も表示 |
| `--out DIR` / `--no-report` | レポートの保存先 / 保存しない |
| `--no-pause` | 終了時に Enter を待たない |
| `--version` | バージョン表示して終了 |

終了コード: `0` = NG なし、`1` = NG あり、`2` = ツール自体のエラー（引数不正、プロジェクトでない、規則表が不正を含む）。
Enter 待ちは、`--` で始まるオプションが 1 つも無く、かつ `--no-pause` が無いときだけ（= ダブルクリック起動とドラッグ＆ドロップ起動。コンソールから `PROJECT` だけ渡した場合も待つ）。オプションを 1 つでも付けたら待たない。

## 状態遷移・主要ロジック

処理順:

1. **規則表の読み込み・検証**（`rules.load`）。
2. **プロジェクトの確認**（`project.collect` → `ProjectFacts`）。読み取り例外はその項目だけ「読めない」として続行。
3. **Editor.log の解析**（`editorlog.parse` → `LogFacts`）。ストリームで 1 行ずつ。エラーは件数と、先頭 N 件（N=各集計で最大 20）だけ保持。
4. **判定**（`checks.judge(project_facts, log_facts, rules) -> list[Finding]`、副作用なしの純関数）。
5. 並べ替え、伏せ字、表示、レポート保存。

判定表（`ID` と条件。level と confidence は下記が既定で、規則表で上書き可）:

| ID | 条件 | level / confidence | 次にすること |
|---|---|---|---|
| P_UNITY_VERSION | `m_EditorVersion` が `unity.supported` のいずれかと**完全一致** | OK | — |
| P_UNITY_VERSION | 年.マイナー（例 `2022.3`）が推奨と同じで、パッチ以降が違う | warn / mid | 推奨版に揃える。Unity Hub のアップグレード警告は無視してよい、と公式が案内（原文: current-unity-version.md） |
| P_UNITY_VERSION | 年.マイナーが違う（`2019.4.x`, `6000.x` を含む） | ng / high | 推奨版の Unity で開き直す。バージョンを上げるとアップロードに失敗する、と公式が案内 |
| P_UNITY_UNREADABLE | `ProjectVersion.txt` が無い/読めない | info | — |
| P_NO_SDK | `Assets/VRCSDK` も `Packages/com.vrchat.*` も無く、`vpm-manifest.json` にも `com.vrchat.*` が無い | ng / high | VCC でプロジェクトに SDK（Avatars）を追加。手動導入も VCC 経由で入手（公式 sdk/index.md） |
| P_UPM_BROKEN | `Packages/manifest.json` が JSON として壊れている | ng / mid | Unity がプロジェクトを開けない状態。バックアップから戻すか、VCC で開き直す（Unity 側の挙動で、VRChat 公式文書の記載ではない） |
| P_VPM_BROKEN | `vpm-manifest.json` が JSON として壊れている | ng / mid | VCC でプロジェクトを開き直す／バックアップから戻す |
| P_VPM_NO_MANIFEST | `vpm-manifest.json` が無く、`Packages/com.vrchat.*` はある | info | VCC 管理外のプロジェクト |
| P_VPM_MISSING_PACKAGE | manifest の `locked`（無ければ `dependencies`）にある ID の `Packages/<id>/` が無い。**欠けているのが `com.vrchat.*` なら ng**、それ以外は warn | warn(ng) / mid | VCC で「Resolve」または開き直し（リゾルバは欠落パッケージを復元する、と VCC ドキュメントの要約） |
| P_VPM_VERSION_DRIFT | `locked` のバージョンと `Packages/<id>/package.json` の `version` が違う | warn / low | 同上 |
| P_VPM_DEP_UNSATISFIED | あるパッケージの `vpmDependencies` の ID が `Packages/` に無い、または版が範囲外 | warn / mid | 見出しは「パッケージ同士のバージョンの条件が合っていません」。条件を出している側を VCC で更新、足りないものは追加。範囲は `x` ワイルドカード（`3.1.x`, `3.x.x`）と、空白区切りの比較条件（`>=` `<=` `>` `<` `=`、例 `>=3.7.0 <3.11.0`。演算子と数字の間の空白も可）を判定する。比較条件の中の `x`（実例 `>=3.5.2 < 3.9.X`）は npm の semver と同じく `<3.9.x`→`<3.9.0`、`<=3.9.x`→`<3.10.0`、`>3.9.x`→`>=3.10.0`、`=3.9.x`→`>=3.9.0 <3.10.0` と読む。`||` `^` `~` などは判定しない。境界と同じ数字のプレリリース版も判定しない |
| P_VPM_DEP_UNKNOWN | 上の判定ができない書き方の条件がある | info | 「判定していません。VCC の画面で警告を確認」。（実機試験で「判定できない書き方がある」と表示してほしいという要望） |
| P_SDK_DUPLICATE | `Assets/VRCSDK` があり、かつ `Packages/com.vrchat.base` もある | warn / mid | 旧方式の SDK と VCC 方式の SDK が二重に入っている可能性。バックアップを取り、VCC 方式に統一（公式は VCC を推奨。sdk/index.md） |
| P_DEFINE_SYMBOLS | `VRC_SDK_VRCSDK2` の語が `ProjectSettings.asset` にあり、SDK3 相当（`Packages/com.vrchat.avatars` か `worlds`）が入っている | warn / mid | SDK2 のシンボルが残っている。公式: 「そのプロジェクトの SDK に関係ないシンボルは消す」（sdk-troubleshooting.md）。Unity の Player Settings → Scripting Define Symbols から消す |
| P_SDK_OLD | 導入済み `com.vrchat.avatars` の版が規則表 `sdk.min_avatars_for_new_upload` 未満 | warn / low | SDK 3.9.0 未満だと新規アバターのアップロードができない、という案内が解説記事にある。VCC で最新版に更新（バックアップ後） |
| P_DYNAMIC_BONE | `folder_rules.dynamic_bone` にヒット | info / low | 旧 Dynamic Bone のフォルダがある。それ自体がアップロードを妨げるとは限らない（解説記事に「残っていると問題」の例がある程度）。PhysBone への置き換えは商品の指示に従う |
| P_PATH_NON_ASCII | プロジェクトのパスか `%USERPROFILE%` に非 ASCII 文字 | info / low | 日本語パスがエラーの原因になる例が解説記事にある。英数字のみのフォルダに移す。（2026-10-01 に warn から info へ: 実機試験で、日本語を含むパスの新規プロジェクトが Unity 2022.3.22f1 でエラーなく開けたため） |
| P_UNITY_OPEN | `Temp/UnityLockfile` がある | info / low | Unity で開いている最中の可能性。ログが書き込み途中かもしれないので、直した後なら Unity を終了してから再実行。（Unity が開いている間だけこのファイルを置くことは一般に知られた挙動だが、公式文書では**未確認**） |
| P_PATH_LONG | プロジェクトのフルパスが 120 文字を超える | info / low | パスが長いと `Library/PackageCache` 配下のファイルが Windows のパス長上限に当たる例がある（Unity フォーラムの報告）。短いパスに移す |
| L_NOT_FOUND | Editor.log が無い | info | Unity を一度起動してから再実行。または `--editor-log` で指定 |
| L_OTHER_PROJECT | ログ内の `-projectPath` が指定プロジェクトと不一致 | warn / high（事実の比較） | このログは別のプロジェクトのもの。対象プロジェクトを Unity で開き直してから再実行。以降の `L_` 候補は確からしさ「低」に落とす |
| L_OLD_LOG | ログの更新日時が 7 日より前 | info | 対象プロジェクトを Unity で開き直してから再実行 |
| L_COMPILE_ASSETS | `Assets/` 由来（`Assets/VRCSDK` 以外）のコンパイルエラーが 1 件以上 | ng / high（下の「消えたファイル」参照） | 公式: 第三者スクリプトのコンパイルエラーは SDK パネルが出ない原因（sdk-troubleshooting.md）。該当ファイルの元アセットを特定して、導入手順の抜け（依存パッケージ）を確認、または削除 |
| L_COMPILE_SDK | `Packages/com.vrchat.*` または `Assets/VRCSDK` 由来のコンパイルエラーが 1 件以上 | ng / mid | SDK の一部が欠けている、または依存の版が合っていない。VCC で SDK を再インストール／更新（バックアップ後） |
| L_COMPILE_OTHER | 上記以外（`Packages/` の他パッケージ、または `Library/PackageCache/` = Unity レジストリのパッケージ）由来 | warn / mid | `Packages/` なら該当パッケージの導入手順を確認。`Library/PackageCache/` なら Unity 側のパッケージの不整合で、`Library` フォルダを消して開き直す／Package Manager でリセットする対処が Unity フォーラムで案内されている（Unity 側の挙動） |
| L_MISSING_TYPE | `CS0246` / `CS0234` のメッセージから取れた不足名（`'…'` 内）が 1 個以上 | warn / mid | 不足名の一覧（重複除去、最大 20 個）を表示。`missing_type_hints` に当たる名前にはヒント（低）を添える。当たらない名前は「その名前を提供するパッケージを入れる。どれかは商品ページの導入手順に従う」 |
| L_UPLOAD_MSGS | `log_rules` の各パターンが 1 件以上一致 | 規則表どおり | 規則表の `advice` |
| L_UNCLASSIFIED | 未分類の `Error` / `Exception` 行が 1 件以上 | info | 種類ごとの件数と先頭行を表示。「レポートを貼って相談してください」 |
| L_TRUNCATED | 末尾 50 MB だけ読んだ | info | — |
| R_STALE | `checked_on` から 90 日超 | info | 最新版の配布ページを確認 |
| P_SDK_FOUND | SDK（`Packages/com.vrchat.*` か `Assets/VRCSDK`）がある | OK | 「問題なしの項目」に版を表示 |
| P_VPM_OK | manifest があり、欠落も版違いもない | OK | — |
| P_SETTINGS_UNREADABLE | `ProjectSettings.asset` がバイナリ形式か開けない | info | — |
| P_SCAN_TRUNCATED | Assets の走査を上限で打ち切った | info | — |
| P_<規則 ID 大文字> | `folder_rules` の各規則にヒット（例 `P_DYNAMIC_BONE`） | 規則表どおり | 規則表の `advice` |
| L_UNREADABLE | Editor.log はあるが開けない | info | Unity を終了してから再実行 |
| L_NO_COMPILE_ERRORS | Editor.log にコンパイルエラーなし | OK | — |

- `L_UPLOAD_MSGS` の判定 ID は `L_UPLOAD_MSGS/<規則 ID>`（規則ごとに 1 候補）。
- **消えたファイル**: `L_COMPILE_*` の根拠のファイルがプロジェクト内に今は無いとき、その根拠の行末に「（このファイルは今はありません）」を付ける。グループの全ファイルが無いときは確からしさを「低」にし、「ログにあるファイルは、今はもうありません。直した後なら、Unity で開き直してから再実行してください」を添える（推測の注記は付けない）。（実機試験: エラーのスクリプトを消した直後に診断すると、古いログのまま NG・高が出た）

- 1 つの事実から複数の Finding が出てよい（例: 同じエラー群から L_COMPILE_ASSETS と L_MISSING_TYPE）。
- `L_UPLOAD_MSGS` の初期規則（`rules.json`）:
  - `upload.build_failed`（`Failed to build avatar`）: warn / low。次にすること: 「この行より前の赤いエラーを確認する。原因は別の行にあることが多い」
  - `upload.validation_failed`（`Avatar validation failed`）: warn / low。次にすること: 「SDK パネルの Builder 画面の警告を確認する」
  - `upload.blueprint_not_owned`（`we do not own, clearing blueprint id`）: warn / mid。次にすること: 「Blueprint ID が別のアカウントのものです。SDK の Pipeline Manager で Detach し、自分のアカウントで Attach（新しい ID が自動生成される）してから上げ直す」（出典: https://raw.githubusercontent.com/vrchat-community/creator-docs/main/Docs/docs/sdk/vrcpipelinemanager.md — Detach/Attach と自動生成の記述。「別アカウントの場合」の直接の記述はなく、**mid**）
  - `upload.contentinfo_nre`（`CreateContentInfoGUI` を含む例外）: warn / low。次にすること: 「SDK 3.9.x〜3.10.0 でアップロード後にアバターが出ない不具合の報告がある。SDK を更新する」（出典: 上記 feedback の検索要約）
- ワールドのビルドやアップロードは診断対象外。ただしプロジェクト診断とコンパイルエラーの診断は SDK が Worlds でも同じく動く。

## エラーと復旧

| 状況 | 挙動 |
|---|---|
| プロジェクトのフォルダでない | メッセージと候補（1 階層下）を出して終了コード 2 |
| 個別ファイルが読めない（権限・破損） | その項目を情報「読めませんでした」にして続行 |
| Editor.log が別プロセスに掴まれている（Unity 起動中） | 読み取り共有で開く。開けなければ L_NOT_FOUND に準じて「Unity を終了してから再実行」を表示（**Windows の共有読み取りの挙動は未検証**） |
| 規則表が不正 | 終了コード 2、不正な箇所（ID・項目名）を表示 |
| レポートの保存失敗 | 画面にエラー、終了コードは判定どおり |
| 想定外の例外 | トレースバックを表示、終了コード 2、ダブルクリック時は Enter 待ち |
| Ctrl+C | 中断して終了コード 2（部分結果は出さない。誤診を避ける） |

## 設定項目一覧

CLI オプション（上表）と規則表 `rules.json` が全て。設定ファイルは作らない。
既定値の根拠: 90 日は SDK や推奨 Unity 版が変わりうる周期の目安（根拠は運用上の判断であり、公式の周期ではない）／50 MB は Editor.log を数秒で読める上限（2026-09-30 実測: Linux の 4 コア環境で 60 MB・53 万行のログの末尾 50 MB を 4.1 秒。Windows 実機では未測定）／走査 20,000 エントリは大きなプロジェクトでも数秒で終わる目安（同上）。**いずれも `rules.json` ではなく定数として持ち、README に書く。**

## 既知の制限・未検証事項

- アップロード失敗のログ規則のうち、実ログで一致を確かめたのは `upload.blueprint_not_owned` と `upload.contentinfo_nre` だけ（2026-10-01）。`upload.build_failed`・`upload.validation_failed` は公開質問の断片から起こしたままで、実ログで一致しない可能性がある（**未検証**）。
- Editor.log のコマンドライン引数（`-projectPath`）は、VCC の「Open Project」から起動した場合に書かれることを確認した。Unity Hub から直接開いた場合は**未確認**（書かれていなければ「対象プロジェクト: 不明」になるだけ）。
- Unity を 2 つ同時に開いたとき、2 つ目がどのファイルにログを書くかは**未確認**。
- 推奨 Unity 版・SDK の仕様は変わる。規則表の日付を見て、古いときは最新の配布版に更新する。
- 低の確からしさの候補は解説記事ベースの推測で、外れることがある。
- シーン・プレハブ・アニメーターの中身は見ない（パラメータ容量 256 bit の検査は v0.2 候補。上限と単価は公式に記載あり）。
- VRChat アカウント側の問題（Steam/Meta アカウントでは上げられない、信頼ランクが足りない等）は診断できない。公式: VRChat アカウントの New User 以上が必要（sdk/index.md）。
- Windows での Editor.log の共有読み取り、日本語パス、ドラッグ＆ドロップ起動は、2026-10-01 の実機試験（Windows 11、1 台）で確認した。それ以外の環境（Windows 10、OneDrive 配下のフォルダなど）は**未検証**。

## セキュリティ / プライバシー

- インターネットへの送信は一切しない。読み取りのみで、プロジェクトのファイルは 1 つも書き換えない。書くのはレポート txt だけ。
- 他人の表示名は扱わない。
- レポートと画面の**根拠の引用行**には次の伏せ字を通す（画面にも同じ処理を適用）:
  - `usr_…` → `usr_xxxx`、`avtr_…` → `avtr_xxxx`、`wrld_…` → `wrld_xxxx`（`_` に続く 8 文字以上の英数字・ハイフン。UUID 形式と旧形式の両方）
  - Windows のユーザー名を含むパス: 任意のドライブの `X:\Users\<名前>\` → `%USERPROFILE%\`（スラッシュ表記も）
  - 指定されたプロジェクトフォルダのフルパス → `<PROJECT>`（プロジェクト名がアバター名・本名になっていることがあるため）。Editor.log は `/` 区切りで書くため、`\` と `/` の両方・大文字小文字の違いも同じものとして置換する。**`<PROJECT>` の置換を先に、`%USERPROFILE%` の置換を後に**行う
  - メールアドレス形式 → `<email>`（最後の区切りが英字 2 文字以上のものだけ。`com.unity.ugui@1.0.0` のようなパッケージのパスは伏せない）
- 診断の前に出すエラー（フォルダが無い、Unity プロジェクトでない）は、利用者が指定したパスを確かめられるよう**伏せずに**画面に出す（レポートは作らない）。
- パッケージの ID とバージョンの一覧は伏せない（個人を特定しないため。README に明記）。

## ビルド

- 依存: 標準ライブラリのみ。`requirements.txt` は空（コメントのみ）。
- `pyinstaller.args`: `--collect-submodules upload_doctor --add-data src/upload_doctor/rules.json;upload_doctor`（`rules.json` を exe に同梱するため。区切りの `;` は Windows 用。最初に使った `--collect-data upload_doctor` は、CI が `--paths src` で探索パスに足すだけのパッケージを見つけられず、何も同梱されなかった＝`--self-check` の起動確認で検出）。
- `smoke.args`: `--no-pause --no-report`（CI にはプロジェクトも Editor.log も無いので「プロジェクトのフォルダでない」で終了コード 2 になってしまう）。そのため **`--self-check` を追加する**: 同梱の `rules.json` を読み込んで検証し、内蔵の最小の偽プロジェクトを一時フォルダ（`tempfile`、終了時に削除）に作って診断まで通し、終了コード 0 を返す。**これが「レポート以外に書かない」の唯一の例外**で、書く先は一時フォルダだけ。`smoke.args` は `--self-check --no-pause`。CI の合格は 0 または 1（既存の仕組みどおり）。
  - `--self-check` は隠しオプション（README には書かない。サポート用に `--version` と並べて残すのは可）。

## 実物での確認（2026-09-30、出品前）

Windows 実機と VRChat アカウントの無い環境で、次の方法で「実物」と突き合わせた。

| 確認したもの | 方法 | 結果 |
|---|---|---|
| Unity 2022.3.22f1 本体のログ | Docker イメージ `unityci/editor:ubuntu-2022.3.22f1-base-3`（game-ci）でバッチモード起動 | ライセンス未認証のため**プロジェクト読み込み前に終了**。先頭のログ（`[Licensing::…] Error: …` を含む）で誤検知なし。この時点までにコマンドライン引数は出力されない（`-projectPath` の判定は「不明」になる） |
| コンパイルエラーの行の形と文言 | 同イメージ同梱の C# コンパイラで、壊れたスクリプトを `Assets/...` の相対パスでコンパイル | 正規表現で全行を解析できた。**名前空間ごと無い場合、不足名は先頭の 1 語だけ**（例 `'nadena'`、`'VRC'`）→ Modular Avatar のヒントに `nadena` の完全一致を追加 |
| `ProjectSettings.asset` | 同イメージ内の Unity 標準テンプレート | テキスト形式（`%YAML 1.1`）。`scriptingDefineSymbols` の項目がある → 語の検索で読める |
| `ProjectVersion.txt`, `vpm-manifest.json` | VRChat 公式のアバター用テンプレート（GitHub） | `m_EditorVersion: 2022.3.22f1` の形を確認。`vpm-manifest.json` は `dependencies.<id>.version`、版は `3.x.x`。**`locked` の実物は未確認** |
| パッケージの `vpmDependencies` | Modular Avatar・NDMF・Avatar Optimizer の `package.json`（GitHub） | 範囲は `>=1.14.7 <2.0.0-a`、`>=3.7.0 <3.11.0` のように**空白区切りの複数条件**が使われていた → 複数条件と `3.x.x` に対応。`||` などは判定しない |

まだ確かめられていないもの: Windows で GUI 起動したときの Editor.log の全体（コマンドライン引数の有無、コンパイルエラーがそのまま書かれるか、アップロード失敗の文言）、`vpm-manifest.json` の `locked`、Windows 上での exe の動作。

## 実機試験（2026-10-01、Windows 11 実機）

手順は `docs/cowork-test.md`。オーナーの PC で、画面を操作できるエージェントとオーナーが実施した。結果の原本はオーナーの Google ドライブ（`UploadDoctor-実機試験結果.md`）。

| 確認したもの | 結果 |
|---|---|
| exe の起動・SmartScreen | 起動した。警告は出たが文面は未記録 |
| 画面へのドラッグ、exe へのドロップ | どちらも動いた。日本語の表示も正常（Windows ターミナル内） |
| 既存のアバタープロジェクト（SDK 3.10.4、パッケージ 8 個） | Unity 版・SDK・パッケージ・ログの対象判定はすべて実際と一致。**依存条件 `>=3.5.2 < 3.9.X` を判定できず見逃した** → 比較条件の中の `x` に対応 |
| 実ログのアップロード関連の行 | `Loaded data for an avatar we do not own, clearing blueprint ID` と `CreateContentInfoGUI` のスタックが規則に一致した（実ログでの初確認） |
| 日本語を含むパスの新規プロジェクト | 落ちず、対象判定も一致。Unity もエラーなく開けた → `P_PATH_NON_ASCII` を info に。**`Start importing …/IError.cs` などの読み込み記録 13 行を未分類エラーと誤検出** → 除外 |
| `vpm-manifest.json` の `locked` | 実物を確認（`locked.<id>.version` と `locked.<id>.dependencies`）。照合は正しく動いた |
| Unity を開いたままの診断 | 読めた（書き込み途中のログ）→ `Temp/UnityLockfile` があれば知らせる |
| GUI の Unity のコンパイルエラー | `Assets\UDTestBroken\Broken.cs(5,28): error CS0029: …` の形（区切りは `\`、行頭の時刻なし）で Editor.log に書かれ、NG・高で検出 |
| Editor.log の先頭 | `COMMAND LINE ARGUMENTS:` の次に 1 行ずつ `-projectPath` とパスが並ぶ → 対象判定「一致」 |
| その他 | レポートの実行日時が exe の起動時刻になっていた → 診断時刻に。Windows 11 が `Windows-10-…` と出ていた → 表記を修正。エラーのファイルを消した後も古いログで NG・高が出た → 「消えたファイル」の扱いを追加 |

抜き出した実ログは `shared/fixtures/unity/real_editor_log_win_*.txt`（伏せ字済み）。

## 実装時の決定（2026-09-30）

- コンパイルエラーの正規表現を規則表 `compile_error_regex` に移した（仕様の「コードに直書きしない」に合わせる）。レビュー版の `[^\s(]+` はフォルダ名の空白（例 `Assets/Dynamic Bone/…`）で一致しなかったため、空白・括弧を許す形に直した。
- 同梱の規則表が PyInstaller の exe で読めない場合に備え、`importlib.resources` が使えないときはモジュールと同じフォルダから読む。CI の `--self-check` で確認する。
- 追加の判定 ID（OK と情報のみ）は判定表の末尾に記載。

## 出典

- https://raw.githubusercontent.com/vrchat-community/creator-docs/main/Docs/docs/sdk/upgrade/current-unity-version.md（推奨 Unity 2022.3.22f1、アップグレードでアップロード失敗）
- https://raw.githubusercontent.com/vrchat-community/creator-docs/main/Docs/docs/sdk/sdk-troubleshooting.md（パネルが出ない原因、SDK シンボルの食い違い）
- https://raw.githubusercontent.com/vrchat-community/creator-docs/main/Docs/docs/sdk/updating-the-sdk.md
- https://raw.githubusercontent.com/vrchat-community/creator-docs/main/Docs/docs/sdk/index.md（VCC 推奨、VRChat アカウントの要件）
- https://raw.githubusercontent.com/vrchat-community/creator-docs/main/Docs/docs/sdk/vrcpipelinemanager.md（Blueprint ID、Detach/Attach）
- https://raw.githubusercontent.com/vrchat-community/creator-docs/main/Docs/docs/avatars/animator-parameters/index.md（256 bit。v0.2 候補）
- https://raw.githubusercontent.com/vrchat-community/creator-docs/main/Docs/docs/avatars/avatar-size-limits.md（対象外の根拠）
- https://vcc.docs.vrchat.com/vpm/resolver/ ／ https://vcc.docs.vrchat.com/vpm/packages/（egress ブロック、検索要約）
- https://github.com/vrchat-community/vpm-package-template
- https://ask.vrchat.com/t/errors-in-unity-sdk/12433 ／ https://ask.vrchat.com/t/avatar-validation-failed/25422 ／ https://ask.vrchat.com/t/unity-vcc-console-error-when-uploading-avatar/23286 ／ https://ask.vrchat.com/t/error-building-avatar-2022-3-6f1/22003（検索要約）
- https://feedback.vrchat.com/sdk-bug-reports/p/avatar-upload-shows-successful-but-does-not-appear-on-vrchat-sdk-39x-3100（検索要約）
- https://docs.unity3d.com/ja/2018.4/Manual/LogFiles.html（Editor.log の場所。検索要約）
- https://discussions.unity.com/t/library-packagecache-error/776799 ／ https://discussions.unity.com/t/library-packagecache-com-unity-ugui-1-0-0-runtime-ui-error/915135（`Library/PackageCache` 由来のコンパイルエラーと対処、パス長の報告。検索要約）
- 解説記事（確からしさ: 低）: https://koshishirai.com/en/unity-vrchat-avatar-upload-solution/ ／ https://vrnavi.jp/unity-error/ ／ https://zenn.dev/sarashinanoniki/articles/d5cee765cea0f7 ／ https://note.com/moegitsubasa/n/nafcfae7fde16
