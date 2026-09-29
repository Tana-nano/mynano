# V睡ログ テスト計画  v0.1

`python -m pytest` をリポジトリ直下で実行して全部通ること。実機（VRChat・SteamVR）は使わない。

## フィクスチャ

| ファイル | 内容 | 由来 |
|---|---|---|
| `shared/fixtures/output_log_sample.txt` | 1 晩分（参加→同席者→来客→退出） | `vrc_mock.log` 形式で作成。実ログ入手後に差し替え |
| `products/vsui-log/tests/fixtures/pose_*.csv` | head pose の時系列（起床→静止→寝返り→起床） | 合成。`t,x,y,z,rx,ry,rz`。実機データ入手後に追加 |
| テスト内生成 | `vrc_mock.LogWriter` で日跨ぎ・複数ファイル・形式崩れ | コード内 |

`shared/vrc_mock` に追加するもの:
- `FakeVRChat.send_head_pose(x, y, z, rx, ry, rz)` と、時系列を指定レートで流す `play_pose(samples, rate_hz)`
- `OscQueryProbe`: 本アプリの HTTP に `GET /` と `GET /?HOST_INFO` を投げ、VRChat と同じ観点（`/avatar` と `/tracking/vrsystem` の有無、OSC_PORT）で検査する

## ユニット

| 対象 | ケース |
|---|---|
| ログ解析 | 各イベント行の抽出／`(usr_…)` 有り無し／表示名に空白・記号・全角・括弧を含む／BOM／デコード不能バイト／パターン差し替え設定／location からアクセス種別の抽出（private/friends/hidden/group/public） |
| ログ追尾 | 追記を検出／新ファイル出現で切替／最終更新が新しい方を選ぶ（古いログへの追記は無視）／行途中で書き込みが止まった場合の次回結合 |
| 自分の判定 | 設定優先／`User Authenticated` 行があれば即確定／無ければ 3 インスタンス連続で確定／途中で別名が来たらリセット／確定前は人物データを保存しない |
| 動き量 | 静止＝0／平行移動のみ／回転のみ／±180 度跨ぎ／サンプル不足窓＝データなし／`max_jump` 超えの外れ値を捨てる／同一値が `frozen_samples` 連続で「データなし」（トラッキング喪失） |
| 状態遷移 | 10 分静止で入眠（入眠時刻が遡る）／寝返り 1 回では起床しない／3 分連続の動きで起床／AFK が 2 分連続で終了、1 分だけなら終了しない／データなし 10 分で終了し、終了時刻＝最後のサンプル時刻／OnLeftRoom で終了／30 分以内の再入眠は終了理由を問わず統合し awakenings+1／データなし窓は連続カウントを保留する／OyasumiVR true/false が優先／感度プリセットの倍率 |
| 夜の日付 | 23:30 入眠→当日／01:00 入眠→前日／12:00 ちょうど |
| ログのみモード | head pose 未受信の滞在は log_only／VRMode=0 で log_only／60 分以上かつ 0–6 時を含む滞在だけ夜にする／VR で入眠未確定の夜も `source=log` で記録し、感度の案内文が付く／滞在区間で同席者・来客を判定 |
| 同席者・来客 | 重なり 30 分境界／入眠後参加は来客／両条件なら同席者／自分を除外／user_id で同一人物、無ければ表示名 |
| 集計 | 今夜のまとめ／週次（合計・平均・平均入眠時刻が日付を跨いでも正しい＝23:30 と 00:30 の平均が 0:00）／よく一緒に寝た人 上位 5 |
| 実績 | 各 key の境界値。一度解除したら重複しない |
| 設定 | 既定値生成／TOML 上書き／環境変数上書き／不正値でわかりやすいエラー |
| 出力 | HTML に外部 URL が含まれない／CSV が UTF-8 BOM・ヘッダ付き／カード PNG が 1200×675、既定で名前を含まない（描画テキストをフックして検査）／チャプター形式 |
| プライバシー | `forget` で people と presence から消える／`--all`／起床中に会っただけの人は people に入らない／`doctor --log-sample` の出力に表示名・`usr_` ID・ワールド名が残らない（フィクスチャの全名前で検査）／`doctor --pose-sample` の CSV は数値列のみ |
| DB | 破損ファイルを退避して新規作成／チェックポイントから復元 |

## 結合（`shared/vrc_mock` 使用）

| シナリオ | 検証 |
|---|---|
| 1 晩通し | FakeVRChat から pose を流し（時間は注入クロックで早送り）、LogWriter でログを書き、`run` のコアループを回す → `nights` 1 件、入眠・起床時刻、同席者 1・来客 1 |
| OSC 送信 | 入眠で `VsuiLog/Sleeping=true`、来客で `VsuiLog/Visitors=1`、起床で false を FakeVRChat が受信 |
| チャットボックス | 既定 OFF で送らない／ON で入眠・起床に各 1 回だけ |
| OyasumiVR 同期 | 設定アドレスに true を送ると動いていても ASLEEP |
| OSCQuery | 起動後に OscQueryProbe で `/`・`?HOST_INFO` を検査。HTTP は 127.0.0.1 のみ。zeroconf 登録は差し替え可能な関数としてモックし、サービス型 `_oscjson._tcp.local.` / `_osc._udp.local.` と TXT `txtvers=1` で呼ばれたことを確認 |
| 直送ポート | auto モードでも 9010 で受信できる／9010 が使用中なら警告のみで常駐は続く |
| コンソール出力 | 標準出力を cp932・`errors=strict` に見立てたストリームに差し替えても `run` のステータス行と `tonight` が例外を出さない |
| フォールバック | zeroconf 起動が例外 → fixed モードで受信継続 |
| ポート競合 | fixed で使用中ポート → 所定のエラーメッセージで終了コード 2 |
| ログ形式変化 | 60 分一致なし → 警告が 1 回出る |
| クラッシュ復旧 | 途中でプロセス相当のオブジェクトを破棄 → 再起動で夜が確定 |

時間は `Clock` を注入して早送りする（実時間で 8 時間待たない）。

## 手動確認（オーナー／購入者に頼る項目）

README の「既知の制限」と一致させる。

1. 実機で `doctor` を実行し、head pose の受信とレートを確認（サンプル CSV を提供してもらえれば閾値を確定）
2. VRChat が OSCQuery で本アプリを発見するか（`doctor` の「OSC: OK」表示）
3. OyasumiVR と同時起動
4. 実ログの `OnPlayerJoined` 行の形（`doctor --log-sample` で個人名を伏せた 20 行を出力する機能を用意し、提供を依頼）
5. Windows で exe が起動し、SmartScreen の案内どおりに進めるか
