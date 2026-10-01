# アップロードドクター テスト計画  v0.1

`python -m pytest` をリポジトリ直下で実行して全部通ること。実機（Unity・VRChat・Windows）は使わない。
**「動いた」と言えるのは、偽のプロジェクトと合成した Editor.log に対する判定まで。実 Unity の出力での正しさは未検証。**

## 設計上のテスト容易性

- 事実の収集（`project.collect`, `editorlog.parse`）と判定（`checks.judge`）を分ける。判定は `ProjectFacts` / `LogFacts` / `Rules` を入れて `Finding` の列を返す純関数。
- ファイルシステムは `tmp_path` に偽プロジェクトを作って読む（`tests/helpers.py` の `make_project(...)`）。
- 現在時刻は注入可能（規則表の 90 日判定用）。ユーザーのパス（`%USERPROFILE%`, `%LOCALAPPDATA%`）は環境変数で差し替え可能。
- 入力（フォルダの入力促し）は関数引数で注入可能（`input_fn`）。

## フィクスチャ

| もの | 内容 | 由来 |
|---|---|---|
| `tests/helpers.make_project` | `Assets/`, `ProjectSettings/ProjectVersion.txt`, `Packages/vpm-manifest.json`, `Packages/<id>/package.json`, `ProjectSettings.asset` の断片、`Assets/DynamicBone` などを引数で組み立てる | コード内 |
| `shared/fixtures/unity/editor_log_compile_error.txt` | `Assets/…(行,列): error CS0246: The type or namespace name 'Cinemachine' could not be found …` を含む数十行 | 公開質問の文言から**合成**（実ログではない）。由来を同ディレクトリの README に記す |
| `shared/fixtures/unity/editor_log_upload_failed.txt` | `Failed to build avatar!`, `Avatar validation failed`, `Attempted to load the data for an avatar we do not own, clearing blueprint id`, `NullReferenceException … CreateContentInfoGUI` を含む | 同上（合成） |
| `shared/fixtures/unity/editor_log_clean.txt` | エラーなし | 同上（合成） |
| `tests/data/rules_bad_*.json` | 規則表の不正例（level が不正、regex が不正、必須項目なし、schema 違い） | コード内 |

`shared/fixtures/README.md` に上記 3 ファイルを追記し、**「実 Unity の出力ではない。実ログ入手後に差し替える」**と書く。個人情報は入れない（`Fixture*` / `usr_0000…`）。

## ユニット

| 対象 | ケース |
|---|---|
| 規則表の読み込み | 同梱の `rules.json` が検証を通る／不正例ごとに終了コード 2 相当の例外と、箇所（ID・項目名）を含むメッセージ／`--rules` で差し替え／全 `log_rules` の regex がコンパイルできる／全ルールに `source` と `advice` がある／`confidence` が `high/mid/low` のみ |
| 規則表の鮮度 | `checked_on` から 89 日 → 出ない、91 日 → R_STALE |
| Unity バージョン | 完全一致 → OK／`2022.3.20f1`（パッチ違い）→ warn・mid／`2019.4.31f1` → ng・high／`6000.0.x` → ng・high／ファイルなし → P_UNITY_UNREADABLE／`m_EditorVersion` 行がない → 同上／CRLF・BOM 付き |
| プロジェクト判定 | `Assets` と `ProjectSettings` あり → OK／なし → 終了コード 2／1 階層下に本物がある → 候補メッセージ／パスに `"` が付いて渡された |
| vpm-manifest | 正常／JSON 破損 → P_VPM_BROKEN／manifest なし＋`Packages/com.vrchat.*` あり → P_VPM_NO_MANIFEST／`locked` にあるが `Packages/<id>/` なし → P_VPM_MISSING_PACKAGE／版の不一致 → P_VPM_VERSION_DRIFT／`locked` が無く `dependencies` だけの場合も動く |
| 依存 | `vpmDependencies` が満たされている／欠落／`3.1.x` 範囲に対し 3.1.4 → 満たす、3.2.0 → 満たさない／完全一致／`>=`／解釈できない書式 → 判定しない（Finding を出さない） |
| SDK | `Assets/VRCSDK` のみ／`Packages/com.vrchat.*` のみ／両方 → P_SDK_DUPLICATE／どちらもなし → P_NO_SDK／`com.vrchat.avatars` 3.8.9 → P_SDK_OLD、3.9.0 → 出ない |
| シンボル | `ProjectSettings.asset` に `VRC_SDK_VRCSDK2` と SDK3 → P_DEFINE_SYMBOLS／SDK2 のみで SDK3 なし → 出ない／バイナリ内容 → 情報 |
| フォルダ走査 | `Assets/DynamicBone` → ヒット／`Assets/Foo/Dynamic Bone`（2 階層下）→ ヒット／3 階層下 → ヒットしない／20,000 エントリ超で打ち切り注記／`Library/` は読まない |
| パス | 非 ASCII のプロジェクトパス → P_PATH_NON_ASCII／`%USERPROFILE%` が非 ASCII／ASCII のみ → 出ない |
| Editor.log の帰属・鮮度 | 先頭 200 行に `-projectPath "C:/Foo/Proj"` があり指定と一致（`\\` と `/`、大文字小文字、末尾区切りの違いを吸収）→ 一致／別パス → L_OTHER_PROJECT かつ全 `L_` 候補が low／無い → 不明で確からしさ据え置き／201 行目以降にあっても見ない／更新日時 8 日前 → L_OLD_LOG、6 日前 → 出ない |
| 重複排除 | 同じ (file,line,col,code) が 4 回 → 「1 件（延べ 4 回）」／別の行番号は別件 |
| UPM manifest | `Packages/manifest.json` 破損 → P_UPM_BROKEN／無い → 何も出ない |
| P_NO_SDK の境界 | ディスクに無いが manifest に `com.vrchat.avatars` → P_VPM_MISSING_PACKAGE（ng）で P_NO_SDK は出ない／manifest にも無い → P_NO_SDK |
| パス長 | 121 文字 → P_PATH_LONG、120 文字 → 出ない |
| 不足型のヒント | `'DynamicBone'` → ヒント付き（low）／`'Foo.Bar'` → ヒント無し／大文字小文字違い／最大 20 個 |
| 由来分類 | `Library/PackageCache/com.unity.x@1.0.0/...` → L_COMPILE_OTHER（PackageCache の案内）／`Packages/com.vrchat.base/...` → L_COMPILE_SDK／`Assets/VRCSDK/...` → L_COMPILE_SDK／`Assets/Foo/...` → L_COMPILE_ASSETS／行頭に `[Error] 12:34:56 ` などの前置きがあっても一致／`Assets/` で始まらないパス → 一致しない |
| Editor.log 解析 | 規則表の `compile_error_regex` がフォルダ名の空白・括弧、`\` 区切りを受け付け、`Assets` 等で始まらないパスは拒む／コンパイルエラー行の分解（file, line, col, code, msg）／`Assets/`・`Packages/`・`Assets/VRCSDK` の由来分類／CS0246・CS0234 の不足名抽出（`'…'` 内）／エラーなし → 空／行末が CRLF／不正な UTF-8 バイトで落ちない／50 MB 超は末尾のみ読み L_TRUNCATED／空ファイル |
| Editor.log 規則 | 4 つの初期規則が合成ログで一致／一致しない行で誤検知しない（`clean` フィクスチャ）／NRE の近傍 5 行以内に `CreateContentInfoGUI` があるときだけ一致（6 行離れたら不一致） |
| 判定 `judge` | 判定表の各行を 1 ケース以上。特に: `Assets/` 由来のエラー → L_COMPILE_ASSETS（ng・high）／SDK 由来のみ → L_COMPILE_SDK／混在で両方／未分類 → L_UNCLASSIFIED／Editor.log 無し → L_NOT_FOUND でプロジェクト診断は継続／OK 行が候補に入らない |
| 並べ替え | NG > 注意 > 情報／同じ状態内で high > mid > low／同順位で根拠件数の多い順／最後は ID の辞書順（同じ入力で常に同じ順） |
| 確からしさ表示 | low の候補に「公式以外の情報にもとづく…推測です」が必ず付く／high と mid には付かない／別プロジェクトで low に下げた候補には「別のプロジェクトのログのため…」が付き、推測の注記は付かない |
| 伏せ字 | `<PROJECT>` の置換が `C:/Users/foo/Proj`（スラッシュ）・`c:\\users\\foo\\proj`（小文字）にも効く／`<PROJECT>` を先に置換するので `%USERPROFILE%\\Proj` にならない／`usr_<uuid>` / `avtr_<uuid>` / `wrld_<uuid>`／`C:\Users\名前\`・`D:\Users\名前\`・`C:/Users/名前/`・日本語名／指定プロジェクトのフルパス → `<PROJECT>`／メールアドレス／伏せ字を適用したあと元の文字列が残らない（プロパティ的に、全フィクスチャに適用して検査） |
| レポート | UTF-8 BOM／各節の存在／引用行 200 文字・60 行の上限と「ほか N 件」／伏せ字後に元のユーザー名・プロジェクト名が含まれない／末尾の案内 1 行／パッケージ一覧が入る |
| CLI | 位置引数あり・なし／`--version`／`--rules` 不正 → 2／プロジェクトでない → 2／NG あり → 1／NG なし → 0／Enter 待ち条件（オプションなしで待つ、`--no-pause` で待たない、`--verbose` を付けたら待たない）／`input_fn` でパス入力（`"` 付き） |
| 実機試験の再発防止（`test_field_findings.py`） | 実ログの抜粋（`real_editor_log_win_*.txt`）で `Start importing` の行・`…Error.cs` のファイル名を未分類に数えない／本物の例外（IOException、SocketException など）は数える／日本語パスの `-projectPath` が 2 行の形で「一致」／比較条件の中の `x`（`>=3.5.2 < 3.9.X` ほか 4 種の演算子）／判定できない書き方 → P_VPM_DEP_UNKNOWN／エラーのファイルが全部消えた → 低＋消えた注記、一部だけ → 高のまま行末に印／`Temp/UnityLockfile` → P_UNITY_OPEN／日本語パスは info／Windows 11 の表記／入力を待った後の時刻がレポート名と実行日時になる |
| 再試験の再発防止（同ファイル末尾） | `error CS2001` の実際の行 → L_SOURCE_GONE（未分類に入らない）／別プロジェクトのとき、確からしさの無いログ由来の候補も「低」／別プロジェクトのパスを `<OTHER_PROJECT>` に伏せる（画面で確認）／同じパスなら `<PROJECT>` が優先 |
| 読み取り専用 | 診断の前後でプロジェクトフォルダ全体のファイル一覧と更新日時・サイズが完全に同じ（書き換えていない）／レポートは `--out` にだけ書かれる |

## 結合

| シナリオ | 検証 |
|---|---|
| 正常な偽プロジェクト＋clean ログ | 終了コード 0、NG なし、「問題は見つかりませんでした」相当の要約 |
| 旧 Unity ＋ 第三者スクリプトのコンパイルエラー ＋ Dynamic Bone | 候補が「Unity 版（ng・high）→ Assets のコンパイル（ng・high）→ Dynamic Bone（warn・low）」の順、根拠に該当ファイルと行、終了コード 1 |
| アップロード失敗ログ | Blueprint ID 所有者違いの案内に Detach/Attach が含まれる |
| VPM 不整合 | manifest にあるが実体がないパッケージ、依存欠落を検出 |
| 通し | `cli.main([project, "--editor-log", log, "--out", tmp, "--no-pause"])` → 画面出力・レポートファイルの内容を検証（伏せ字済み） |
| 自己診断 | `--self-check` の一時フォルダが終了後に残らない |
| 自己診断 | `--self-check` が同梱 `rules.json` を読み、内蔵の偽プロジェクトで診断まで通して終了コード 0 |

## Windows（CI）

- `build-windows.yml`: `--version` と `smoke.args`（`--self-check --no-pause`）で exe が最後まで走り、終了コードが 0 または 1。これで PyInstaller に `rules.json` が同梱されたこと（`--collect-data`）も確認できる（同梱漏れなら規則表の読み込みで終了コード 2 になり失敗）。

## 手動確認（購入者・オーナーに頼る項目。README の「既知の制限」と一致させる）

2026-10-01 の実機試験（`docs/cowork-test.md`、結果は spec.md「実機試験」）で、次は確認済み: 実プロジェクトのファイルの読み取り、`locked`、ドラッグ＆ドロップ、日本語パス、Unity 起動中の Editor.log、GUI の Unity のコンパイルエラー行、`-projectPath` の行。

残る手動確認:

- `upload.build_failed`・`upload.validation_failed` の規則が実ログで一致するか（アップロードの失敗が必要なため、試験では行わない）
- SmartScreen の警告の文面と、README の手順で進めるか
- Unity Hub から直接開いた場合に `-projectPath` が書かれるか
- Windows 10 での動作

## 実装の順序（/vrc-build 向けの目安）

1. `rules`（読み込み・検証）と `rules.json`
2. `mask`（伏せ字）
3. `project`（収集）と `helpers.make_project`
4. `editorlog`（解析）
5. `checks.judge` と並べ替え
6. `report` / `console` / `cli`（`--self-check` を含む）
7. CI 連携（`pyinstaller.args`, `smoke.args`）
