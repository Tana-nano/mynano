# V睡ログ 仕様  v0.1

作成日: 2026-09-29 / レビュー反映: 2026-09-29 / 企画: `docs/concept.md`

## 概要

VR 睡眠の記録アプリ。寝る前に起動しておくと、VRChat が OSC で送るヘッドセットの姿勢から入眠・起床を判定し、
VRChat のログから「どのワールドで・誰と一緒に・寝ている間に誰が来たか」を突き合わせてローカルに保存する。
翌朝、今夜のまとめ・週次レポート・共有カード（画像）・CSV を出力する。常駐はコンソールウィンドウ 1 枚。

## 対応環境 / 前提ソフト

| 項目 | 内容 |
|---|---|
| OS | Windows 10 / 11（64bit） |
| VRChat | PC 版。OSC 有効。**`/tracking/vrsystem` 受信のため VRChat 内の追加同意（legal notice）への同意が必要** |
| モード | PC VR: 全機能 / デスクトップ: ログ由来の記録のみ（入眠・起床なし） / **Quest 単機: 非対応** |
| 任意 | OyasumiVR（スリープモード同期。v1.6.0 以降の OSC Automations） |

## 入力

### OSC 受信

本アプリは OSCQuery サービスとして自分を公開し、VRChat に以下を送らせる。OSCQuery が使えない環境では固定ポート受信にフォールバックする。

| アドレス | 型 | 送信元 | 用途 |
|---|---|---|---|
| `/tracking/vrsystem/head/pose` | 6×float（位置 X,Y,Z / オイラー角 X,Y,Z） | VRChat | 動き量 → 入眠・起床判定 |
| `/avatar/parameters/AFK` | bool | VRChat（組み込み・読み取り専用） | `afk_minutes` 以上 true が続いたら睡眠セッションを終了。**OSC で出力されるかは未検証**（出力されなければこの終了条件は働かないだけ） |
| `/avatar/parameters/VRMode` | int（1=VR, 0=デスクトップ） | VRChat（組み込み） | 0 ならログのみモード。**OSC で出力されるかは未検証**（未受信なら「head pose を受信したか」でモードを決める） |
| `/avatar/change` | string（avatar id） | VRChat | アバター変更で組み込みパラメータが再送されるきっかけ（記録はしない） |
| `oyasumi.address` の設定値（既定 `/avatar/parameters/VsuiLog/OyasumiSleep`） | bool | OyasumiVR（任意） | true/false で入眠/起床を強制（自前判定より優先）。経路は 2 つ: (a) OyasumiVR → VRChat → 本アプリ。**アバターに同名の bool パラメータが必要**（VRChat はアバターに存在するパラメータしか外に出さない） (b) OyasumiVR の Custom target（未リリース）→ 本アプリの `osc.direct_port` へ直送 |

- **送信レート: 未確認。** 判定はレートに依存しない設計にする（受信サンプルを 60 秒窓に集約）。
- **座標の単位（m / 度）: 未確認。** 位置は m、角度は度と仮定し、閾値は設定で変更可能。実機データで確定させる（UNVERIFIED）。

#### OSCQuery の実装

既製の Python ライブラリは実験段階（tinyoscquery は README で WIP と明記）のため、自前で最小実装する。

- UDP: `python-osc` の `ThreadingOSCUDPServer` を空きポートで起動
- HTTP: 標準ライブラリ `http.server` を空き TCP ポートで起動し、次を返す
  - `GET /` → OSC アドレス空間 JSON。`/avatar` と `/tracking/vrsystem` のノードを含める（VRChat はこの 2 パスの有無で送信対象を決める）
  - `GET /?HOST_INFO` → `{"NAME","OSC_IP":"127.0.0.1","OSC_PORT","OSC_TRANSPORT":"UDP","EXTENSIONS":{"ACCESS":true,"VALUE":true}}`
- mDNS: `zeroconf` で `_oscjson._tcp.local.` と `_osc._udp.local.` を広告。サービス名は `VsuiLog-<4桁乱数>`
- フォールバック: 設定 `osc.mode = "fixed"` なら OSCQuery を使わず `osc.listen_port`（既定 9001）で受信。
  既定は `auto`（OSCQuery を試し、HTTP/mDNS の起動に失敗したら fixed へ）
- 直送ポート: モードに関わらず `osc.direct_port`（既定 9010）でも同じディスパッチャで受信する。外部ツール（OyasumiVR の Custom target 等）が本アプリを直接狙うための固定窓口。使用中なら警告して無効化（致命ではない）
- mDNS の TXT レコードに `txtvers=1` を付ける（vrc-oscquery-lib と同じ）

### VRChat ログ

- 監視ディレクトリ: 既定 `%LOCALAPPDATA%Low\VRChat\VRChat`（`%USERPROFILE%\AppData\LocalLow\VRChat\VRChat`）。設定で変更可
- 対象: `output_log_*.txt` のうち**最終更新が最新のもの**を追尾（tail）。新しいファイルが現れたら切り替える
  （複数クライアント起動時に閉じたログを掴む不具合が OyasumiVR で報告されているため、更新時刻で選ぶ）
- 文字コード: UTF-8（BOM 許容、デコード不能バイトは置換）
- 行の形: `yyyy.MM.dd HH:mm:ss <Level> - <message>`。タイムスタンプはローカル時刻

| イベント | 既定の正規表現（message 部分） |
|---|---|
| インスタンス参加 | `^\[Behaviour\] Joining (?P<location>wrld_[^\s]+)` |
| ワールド名 | `^\[Behaviour\] Entering Room: (?P<world_name>.+)$` |
| プレイヤー参加 | `^\[Behaviour\] OnPlayerJoined (?P<name>.+?)(?: \((?P<user_id>usr_[0-9a-f-]+)\))?$` |
| プレイヤー退出 | `^\[Behaviour\] OnPlayerLeft (?P<name>.+?)(?: \((?P<user_id>usr_[0-9a-f-]+)\))?$` |
| インスタンス退出 | `^\[Behaviour\] OnLeftRoom` |

- 正規表現は設定 `[log.patterns]` で差し替え可能（ログ形式変更への備え）
- `(usr_…)` の有無は実ログで**未確認**。無くても表示名で動くこと
- `location` から `world_id` と `instance_id`（`:` 以降〜最初の `~` まで）、アクセス種別（`~private` / `~friends` / `~hidden` / `~group` / 無し=public）を抽出

### 自分の判定

同席者から自分を除くため、自分の表示名が必要。

1. 設定 `self.display_name` があればそれを使う
2. ログの認証行 `^\[Behaviour\] User Authenticated: (?P<name>.+?)(?: \((?P<user_id>usr_[0-9a-f-]+)\))?$`（`[log.patterns].authenticated` で差し替え可）が見つかればそれを自分とし、設定に保存する（UNVERIFIED: 行の有無と形式は実ログで確認）
3. どちらも無ければ、各インスタンスで**最初の** `OnPlayerJoined` を自分の候補とし、3 インスタンス連続で同じ名前なら自分と確定して設定に保存する（UNVERIFIED: 実ログでは自分が最初に来る想定）

自分が確定するまでは同席者・来客を確定しない（人物データを保存しない）。

### 設定ファイル

- 形式: TOML。場所: `%APPDATA%\VsuiLog\config.toml`（初回起動時にコメント付きで生成）
- 上書き順: 設定ファイル → 環境変数 `VSUILOG_<SECTION>_<KEY>` → CLI 引数

## 出力

### データ保存（SQLite）

場所: `%APPDATA%\VsuiLog\vsui.db`

| テーブル | 主な列 |
|---|---|
| `nights` | id, night_date, mode(`vr`/`log_only`), world_id, world_name, instance_access, sleep_start, sleep_end, sleep_minutes, awakenings, source(`motion`/`oyasumi`/`log`) |
| `people` | id, display_name, user_id, first_seen, is_self。**同席者または来客として確定した時にだけ行を作る**。起床中に会っただけの人は保存しない |
| `presence` | night_id, person_id, joined_at, left_at, role(`co_sleeper`/`visitor`), thanked(bool) |
| `samples` | ts, motion（60 秒窓ごとの動き量。調整・デバッグ用。30 日で自動削除） |
| `achievements` | key, unlocked_at |

### OSC 送信（任意・既定 ON）

VRChat の受信ポート（既定 9000）へ送る。アバターにパラメータが無ければ VRChat が無視するだけなので害はない。
**この 2 つを「V睡ログ対応ギミック仕様」として公開する。**

| アドレス | 型 | 送るタイミング |
|---|---|---|
| `/avatar/parameters/VsuiLog/Sleeping` | bool | 入眠確定で true、起床確定で false |
| `/avatar/parameters/VsuiLog/Visitors` | int (0–255) | 睡眠中に来客があるたびに今夜の人数 |

チャットボックス（既定 OFF）: `/chatbox/input` に `[text, true, false]`。入眠時 `chatbox.sleep_text`（既定「💤 おやすみなさい」）、起床時 `chatbox.wake_text`（既定「おはようございます」）。各 1 回のみ送信。

### ファイル

出力先: `%USERPROFILE%\Documents\VsuiLog\`（設定で変更可）

| ファイル | 内容 |
|---|---|
| `tonight_YYYY-MM-DD.html` | 今夜のまとめ（単体 HTML、外部読み込みなし） |
| `week_YYYY-Www.html` | 週次レポート |
| `card_YYYY-MM-DD.png` | 共有カード 1200×675（X 推奨比）。既定は人数のみ |
| `vsui_export_YYYYMMDD.csv` | nights と presence の CSV（UTF-8 BOM 付き、Excel で開ける） |
| `chapters_YYYY-MM-DD.txt` | 来客時刻のチャプター（`HH:MM:SS 来客`。名前は `--names` 指定時のみ）。おやすみレコーダー等の録画と突き合わせる用 |

共有カード: Pillow で描画。文字と数値と単色の図形のみ（画像素材なし）。フォントは実行時に
`C:\Windows\Fonts\YuGothM.ttc` → `meiryo.ttc` → `msgothic.ttc` の順で探し、同梱しない。見つからなければエラーで案内。

## 画面 / CLI

exe をダブルクリックすると `run` が起動する。それ以外はコマンドプロンプトから。

| コマンド | 役割 |
|---|---|
| `vsui-log run` | 常駐。1 行ステータスを更新表示: `[VR] 起床中 / 動き 0.12 / Sample World / 3人 / OSC: OK / ログ: OK`。Ctrl+C で終了（進行中の夜を確定保存） |
| `vsui-log tonight [--date YYYY-MM-DD] [--open]` | 今夜のまとめをコンソール表示＋HTML 出力 |
| `vsui-log week [--week YYYY-Www] [--open]` | 週次レポート |
| `vsui-log card [--date] [--names]` | 共有カード PNG |
| `vsui-log visitors [--date]` | 来客リスト（番号付き） |
| `vsui-log thanks <番号|名前>` | 来客に「お礼済み」を付ける |
| `vsui-log export [--from] [--to]` | CSV 出力 |
| `vsui-log chapters [--date] [--names]` | チャプターファイル出力 |
| `vsui-log achievements` | 実績一覧 |
| `vsui-log forget <名前> / --all` | 指定した人（または全員）の記録を削除 |
| `vsui-log config [--path]` | 設定ファイルの場所を表示／メモ帳で開く |
| `vsui-log doctor` | 診断: ログディレクトリ、最新ログ、OSC 受信状況、フォント、ポートを表示 |
| `vsui-log doctor --log-sample` | 最新ログから対象イベント行 20 行を、表示名・`usr_` ID・ワールド名を伏せて出力（形式確認の提供用） |
| `vsui-log doctor --pose-sample [分]` | head pose を指定分（既定 5）記録し CSV 出力（閾値調整の提供用。位置と角度のみで個人情報なし） |

### 今夜のまとめ（表示項目）

日付・ワールド名・入眠時刻・起床時刻・睡眠時間・途中で起きた回数・一緒に寝た人（人数と名前）・
寝ている間に来た人（時刻と名前、お礼済みマーク）・今夜解除された実績。

### 週次レポート（表示項目）

合計睡眠時間・1 日平均・平均入眠時刻・平均起床時刻・V睡した日数／7・連続日数・
日別の睡眠時間（棒グラフ。HTML 内のインライン SVG）・よく一緒に寝た人 上位 5 名（回数）。

## 状態遷移・主要ロジック

### 動き量

- head pose を受信するたびに `(t, x, y, z, rx, ry, rz)` をバッファ
- 60 秒ごとに窓を閉じ、窓内の動き量 `motion = Σ‖Δ位置‖(m) + k·Σ|Δ角度|(度)` を計算（`k = detect.angle_weight`、既定 0.01 = 1 度を 1cm 相当とみなす）
- 窓内のサンプルが `detect.min_samples`（既定 5）未満なら「データなし」窓とする
- 角度差は ±180 度を跨ぐ場合に最短差を使う

### 状態

```
AWAKE ──(motion < sleep_threshold が sleep_minutes 窓連続)──▶ ASLEEP
ASLEEP ──(motion > wake_threshold が wake_minutes 窓連続)──▶ AWAKE
ASLEEP ──(AFK=true が afk_minutes 連続 / OnLeftRoom / データなし窓が gap_minutes 連続 / アプリ終了)──▶ AWAKE（セッション終了）
任意 ──(OyasumiVR true)──▶ ASLEEP、(OyasumiVR false)──▶ AWAKE
```

| 設定 | 既定 | 根拠 |
|---|---|---|
| `detect.sleep_threshold` | 0.03 | 仮値。1 分で累計 3cm 未満＝ほぼ静止。**実機データで要調整** |
| `detect.wake_threshold` | 0.30 | 仮値。寝返り程度では起床にしないため睡眠閾値の 10 倍 |
| `detect.sleep_minutes` | 10 | 一般的な入眠判定の目安（10 分静止） |
| `detect.wake_minutes` | 3 | 寝返り 1 回で起床扱いにしない |
| `detect.gap_minutes` | 10 | 受信が途切れたらセッションを閉じる。**終了時刻は最後に受信したサンプルの時刻**（判断した時刻ではない） |
| `detect.afk_minutes` | 2 | AFK が一瞬 true になっても（HMD が緩む）終了しない |
| `detect.max_jump` | 1.0 | 1 サンプル間で位置がこれ（m）を超えて動いたら外れ値として捨てる（トラッキング復帰時の飛び対策）。仮値 |
| `detect.frozen_samples` | 20 | 位置・角度が完全に同一のサンプルがこの数連続したら「トラッキング喪失」とみなし、その窓を「データなし」にする（静止と区別する。実機でも完全に同一値が続くことは無い想定。UNVERIFIED） |
| `detect.sensitivity` | `normal` | `low`/`normal`/`high` で閾値を 0.5×/1×/2× |

- 入眠時刻＝静止が始まった窓の開始時刻（確定の `sleep_minutes` 分前に遡る）
- 起床時刻＝動きが始まった窓の開始時刻
- 同じ夜の中で、起床から `detect.merge_minutes`（既定 30）以内に再入眠したら 1 つの夜に統合し `awakenings` を +1。**終了理由（動き／AFK／データなし／OnLeftRoom）を問わず統合する**（HMD を付け直した、VRChat が落ちて入り直した、を 1 つの夜にする）
- データなし窓・トラッキング喪失窓は入眠判定の「静止連続」にも起床判定の「動き連続」にも数えない（連続カウントを保留する）

### 夜（night）の単位と日付

- `night_date` = 入眠時刻が 12:00 以降ならその日、12:00 より前なら前日
- 1 つの `night_date` に複数セッションがある場合、HTML では合算表示（合計睡眠時間）

### ログのみモード

モードはインスタンス滞在ごとに決める: 滞在中に head pose を 1 回でも受信すれば `vr`、無ければ `log_only`（VRMode=0 を受信した場合も `log_only`）。

インスタンス滞在（Joining〜OnLeftRoom）のうち、**滞在 60 分以上かつ 0:00〜6:00 を含むもの**で、動き判定による夜が 1 つも確定しなかった場合は、
`sleep_*` を NULL、`source = log` の夜として記録する。まとめの表示:
- `log_only`: 「睡眠時間は計測していません（デスクトップモード）」
- `vr` なのに未確定: 「動きからは入眠を判定できませんでした。`detect.sensitivity = "high"` を試してください」（閾値が仮値の間の安全網）

同席者・来客はどちらの場合も滞在区間（睡眠区間の代わり）で判定する。

### 同席者と来客

- 同席者 (`co_sleeper`): 睡眠区間と `detect.co_sleeper_minutes`（既定 30）分以上重なって同じインスタンスにいた人。自分は除く
- 来客 (`visitor`): 入眠後に参加した人。同席者条件も満たす場合は同席者を優先
- 同一人物の判定: `user_id` があればそれ、無ければ表示名

### 実績（文字バッジ）

| key | 名前 | 条件 |
|---|---|---|
| `first_night` | はじめてのV睡 | 初めて夜を記録 |
| `streak_3` / `streak_7` / `streak_30` | 3日連続 / 7日連続 / 30日連続 | 連続 night_date |
| `total_100h` | 累計100時間 | 睡眠合計 |
| `long_sleep` | ぐっすり | 1 夜で 7 時間以上 |
| `early_bird` | 早起き | 6:00 前に起床 |
| `popular` | 人気者 | 1 夜で来客 5 人以上 |
| `together_10` | いつものメンバー | 同じ人と 10 夜 |

### 実装上の注意（Windows）

- コンソールは cp932 のことがある。起動時に `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` 相当を行い、表示できない文字（💤 など）で落ちない
- パスは `pathlib`、既定ディレクトリは環境変数から組み立て、テストでは引数で差し替える

## エラーと復旧

| 状況 | 挙動 |
|---|---|
| VRChat 未起動 | ステータス「VRChat 待機中」。ログ／OSC を待ち続ける |
| ログディレクトリが無い | 起動時に警告と `doctor` の案内。OSC だけで動く（同席者なし） |
| 追尾中のログファイルで、読み始めて 60 分以上、行はあるのにパターン一致が 0 件 | 警告「ログ形式が変わった可能性」（ファイルごとに 1 回）。設定の `[log.patterns]` と更新確認を案内。一致が 1 件でもあれば出さない（寝ている間に Join が無いだけの誤警告を避ける） |
| head pose を受信しない（VR 中なのに 5 分） | 警告「VRChat の OSC 設定で追加の同意が必要な場合があります」＋README の該当節 |
| ポート使用中（fixed モード） | エラー表示で終了。「他の OSC アプリと競合しています。`osc.mode = "auto"` を推奨」 |
| mDNS 起動失敗（auto） | fixed に切り替えて続行し、ステータスに `OSC: 固定ポート` と表示 |
| DB ロック／破損 | 起動時に `vsui.db` を `vsui.db.broken-<日時>` に退避して新規作成、警告 |
| 実行中にクラッシュ | 進行中の夜は 60 秒ごとにチェックポイント保存しているので、次回起動時に復元して確定。起床時刻＝最後のチェックポイント時刻 |
| `osc.direct_port` が使用中 | 警告して直送窓口だけ無効化。常駐は続ける |
| フォントなし | `card` のみ失敗。案内を表示 |

## 設定項目一覧（config.toml）

```toml
[self]
display_name = ""          # 空なら自動判定

[osc]
mode = "auto"              # auto | oscquery | fixed
listen_port = 9001         # fixed モードの受信ポート
direct_port = 9010         # 外部ツール直送用（常時）。0 で無効
send_host = "127.0.0.1"
send_port = 9000
send_parameters = true     # VsuiLog/Sleeping, VsuiLog/Visitors を送る

[oyasumi]
enabled = false
address = "/avatar/parameters/VsuiLog/OyasumiSleep"

[chatbox]
enabled = false
sleep_text = "💤 おやすみなさい"
wake_text = "おはようございます"

[detect]
sensitivity = "normal"
sleep_threshold = 0.03
wake_threshold = 0.30
angle_weight = 0.01
sleep_minutes = 10
wake_minutes = 3
gap_minutes = 10
afk_minutes = 2
merge_minutes = 30
min_samples = 5
max_jump = 1.0
frozen_samples = 20
co_sleeper_minutes = 30

[log]
directory = ""             # 空なら %LOCALAPPDATA%Low\VRChat\VRChat
[log.patterns]             # 空なら既定の正規表現（joining, entering_room, player_joined, player_left, left_room, authenticated）

[output]
directory = ""             # 空なら Documents\VsuiLog
card_show_names = false    # true で共有カードを既定で名前入りにする
keep_samples_days = 30
```

`card_show_names` の既定は false（企画の決定）。`card --names` で一時的に名前入りにできる。

## 既知の制限・未検証事項

README の「既知の制限」に転記する。

| 項目 | 状態 |
|---|---|
| head pose の送信レート・単位（m / 度） | **未検証**。閾値は仮値。実機データで調整予定 |
| VRChat が本アプリを OSCQuery で発見するか（mDNS、Windows ファイアウォール） | **未検証**。失敗時は fixed モードで回避可能 |
| OyasumiVR と同時起動時の OSC 配信 | **未検証**（両方 OSCQuery 対応のため問題ない想定） |
| 実ログの行形式（`(usr_…)` の有無、`User Authenticated` 行の有無、自分が最初に Join として記録されるか） | **未検証** |
| AFK / VRMode が OSC で出力されるか | **未検証**。出力されなくても動く設計 |
| トラッキング喪失時に VRChat が送る値（同一値の繰り返しか、送信停止か） | **未検証**。どちらでも「データなし」になる設計 |
| ヘッドセットが外れたまま朝まで寝た場合 | 外れた時刻で夜が終わる（仕様どおり。README に明記） |
| デスクトップモードの入眠検知 | 非対応（ログのみ） |
| Quest 単機 | 非対応 |

## セキュリティ / プライバシー

- 他人の表示名・`usr_` ID は `vsui.db` と、利用者が明示的に出力したファイルにのみ保存する。外部送信はしない（ネットワーク通信は localhost の OSC と mDNS 広告のみ）
- 共有カードは既定で人数のみ。名前入りは `--names` または `output.card_show_names = true` の時だけ
- 削除: `vsui-log forget <名前>` / `forget --all`、またはフォルダ `%APPDATA%\VsuiLog` を削除
- README に「来客・同席者の名前を本人の同意なく公開しないでください」と明記
- HTTP サーバーは `127.0.0.1` にのみバインド

## 公開する付属文書

- `docs/gimmick-spec.md`: 対応ギミック仕様（`VsuiLog/Sleeping`, `VsuiLog/Visitors`, `VsuiLog/OyasumiSleep` の型と意味、送信タイミング、Modular Avatar での受け方の例は**文章のみ**）。無料公開・再配布可

## 依存ライブラリ

| ライブラリ | 用途 | ライセンス |
|---|---|---|
| python-osc 1.10 | OSC 送受信 | パブリックドメイン（Unlicense 相当。pip metadata で確認） |
| zeroconf 0.151 | mDNS 広告 | LGPL-2.1-or-later（PyInstaller onedir 配布でライブラリを差し替え可能な形にする。THIRD_PARTY.md に全文） |
| Pillow 12 | 共有カード描画 | MIT-CMU |

## 出典

- VRChat OSC 概要（ポート 9000/9001、`--osc` 引数）: https://github.com/vrchat-community/osc/wiki / https://docs.vrchat.com/docs/osc-overview（egress でブロック、検索要約で確認）
- OSCQuery（`/avatar` と `/tracking/vrsystem` を公開したアプリに送信、Windows では同一マシンのみ）: https://github.com/vrchat-community/osc/wiki/OSCQuery
- OSCQuery エンドポイント・HOST_INFO・`_oscjson._tcp`: https://github.com/vrchat-community/vrc-oscquery-lib/blob/main/Readme.md
- `/tracking/vrsystem/head/pose` の 6 floats（位置 XYZ・オイラー XYZ）と追加同意の必要性: https://wiki.vrchat.com/wiki/OSC（egress でブロック、検索要約で確認）
- 組み込みパラメータ AFK / VRMode（読み取り専用）: https://creators.vrchat.com/avatars/animator-parameters/
- ログ行パターン: VRCX `Dotnet/LogWatcher.cs` https://github.com/vrcx-team/VRCX/blob/master/Dotnet/LogWatcher.cs
- 複数クライアント時のログ誤追尾: https://github.com/Raphiiko/OyasumiVR/issues/275
- OyasumiVR OSC Automations / Custom target（未リリース）: https://github.com/Raphiiko/OyasumiVR/blob/develop/CHANGELOG.md
- tinyoscquery（WIP のため不採用）: https://github.com/cyberkitsune/tinyoscquery
