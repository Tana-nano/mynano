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

実 `Editor.log`（`%LOCALAPPDATA%\Unity\Editor\Editor.log`）を入手したら、ユーザー名・`usr_` ID・プロジェクト名を置換してここに追加し、上の合成ファイルと差し替える。

