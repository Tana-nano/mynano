# fixtures

テスト用のサンプルデータ。**実際の他人の表示名・ユーザー ID を入れない**（`Fixture*` / `usr_0000...` を使う）。

| ファイル | 由来 | 備考 |
|---|---|---|
| `output_log_sample.txt` | `shared/vrc_mock/log.py` の形式で生成。行の形は VRCX の LogWatcher が解析するパターンに合わせている | 実ログとの差分は **未検証**。実ログを入手したら個人情報を置換して差し替える |

## 実ログを追加するとき

1. `%LOCALAPPDATA%Low\VRChat\VRChat\output_log_*.txt` からコピー
2. 表示名・`usr_` ID・ワールド名を `Fixture*` / `usr_0000…` に置換
3. ここに由来（VRChat のビルド番号、日付）を記録

## Unity の Editor.log（アップロードドクター用・合成）

| ファイル | 由来 | 備考 |
|---|---|---|
| `unity/editor_log_compile_error.txt` | 公開質問（ask.vrchat.com）に載っている CS0246 の文言から**合成** | 実 Unity の出力ではない。行頭の装飾や時刻の有無は**未検証** |
| `unity/editor_log_upload_failed.txt` | 同上（`Failed to build avatar` ほかの文言から合成） | 同上 |
| `unity/editor_log_clean.txt` | 合成 | エラーなし |

### 実物の Unity から取ったもの（2026-09-30）

| ファイル | 由来 | 備考 |
|---|---|---|
| `unity/real_unity_2022.3.22f1_batchmode_unlicensed_head.txt` | Docker イメージ `unityci/editor:ubuntu-2022.3.22f1-base-3`（game-ci）で Unity 2022.3.22f1 を `-batchmode -nographics -quit -projectPath /work/FixtureAvatar` で起動した出力の先頭 32 行。Session / Correlation / Machine の各 ID は伏せた | **ライセンス未認証のため、プロジェクトの読み込み前に終了している**。Linux・バッチモードの出力で、Windows の GUI 起動の Editor.log と同じとは限らない |
| `unity/real_csc_2022.3.22f1_errors.txt` | 同じイメージに同梱の C# コンパイラ（`Editor/Data/DotNetSdkRoslyn/csc.dll`、`NetCoreRuntime/dotnet`）で、壊れたスクリプトを Unity と同じ相対パス（`Assets/...`）でコンパイルしたときの出力そのまま | コンパイラの出力の形と文言は実物。**Unity がこれを Editor.log にそのまま書くかは未確認** |

| `unity/template-avatar/vpm-manifest.json`, `unity/template-avatar/ProjectVersion.txt` | VRChat 公式のアバター用テンプレート https://github.com/vrchat-community/template-avatar の `Packages/vpm-manifest.json` と `ProjectSettings/ProjectVersion.txt` をそのまま | VCC で開く前の状態（`locked` なし、`dependencies` の版は `3.x.x`） |

実 `Editor.log`（`%LOCALAPPDATA%\Unity\Editor\Editor.log`）を入手したら、ユーザー名・`usr_` ID・プロジェクト名を置換してここに追加し、上の合成ファイルと差し替える。

