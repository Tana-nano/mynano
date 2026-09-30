# fixtures

テスト用のサンプルデータ。**実際の他人の表示名・ユーザー ID を入れない**（`Fixture*` / `usr_0000...` を使う）。

| ファイル | 由来 | 備考 |
|---|---|---|
| `output_log_sample.txt` | `shared/vrc_mock/log.py` の形式で生成。行の形は VRCX の LogWatcher が解析するパターンに合わせている | 実ログとの差分は **未検証**。実ログを入手したら個人情報を置換して差し替える |

## 実ログを追加するとき

1. `%LOCALAPPDATA%Low\VRChat\VRChat\output_log_*.txt` からコピー
2. 表示名・`usr_` ID・ワールド名を `Fixture*` / `usr_0000…` に置換
3. ここに由来（VRChat のビルド番号、日付）を記録
