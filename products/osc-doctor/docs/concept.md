# OSCドクター — 企画書 (concept)

作成日: 2026-09-30 / 状態: **論点 3 つの回答待ち**
市場調査: `docs/market/osc-diagnostic-tool-2026-09.md`

## Step 1: コンセプト

| 項目 | 内容 |
|---|---|
| 商品種別 | PC アプリ（Windows、ダブルクリックで動く CLI。V睡ログと同じ作り） |
| 対象ユーザー | VRChat で OSC を使う全員（表情・心拍・フルトラ・OyasumiVR・チャットボックス系ツール）。特に「OSC を有効にしたのに動かない」で止まっている人 |
| 提供体験 | ダブルクリックして 15 秒待つと、「VRChat から届いているか」「何が邪魔しているか」「次に何をすればよいか」が日本語で表示される。困ったときにサポートへ貼れるレポート txt も同時にできる |
| 販売形態 | **無料**（ブースト＝投げ銭は任意）。ショップの認知と、他ツールの導入前チェックが目的 |
| 参考作品 | VRChat 内蔵 OSC Debug（受信側のみ）、OSCキャッシュリセッター（キャッシュ削除のみ）、VRC-OSC-looker（英語・要ビルド・監視のみ） |
| 差別化 | (1) VRChat が**送っている側**を見せる (2) ポートを掴んでいるプロセス名を出す (3) 既知の原因 6 種を順に自動判定して日本語で案内 (4) 貼れるレポート |
| 対応環境 | PC VR ○ / デスクトップ ○（OSC はデスクトップでも動く。トラッキング系の項目だけ「VR のみ」と表示） / **Quest 単機 ×** |
| AI 製リスク | 画像なし。出力は文字のみ。サムネは実行画面のスクリーンショット＋文字組み |

### ユーザーの一日での位置

1. 新しい OSC ツールを入れた → 動かない → X で「OSC 動かない」と検索 → 本ツールに辿り着く
2. ダブルクリック → 結果を読む → 案内どおり直す（同意設定 ON、他アプリ終了、キャッシュ削除 など）
3. 直らなければレポート txt をツール作者に送る（他ツールの作者にも使ってもらえる形）
4. レポート末尾の一行でショップの他ツール（V睡ログ）を知る

## Step 2: 技術的実現可能性

### 診断項目と一次情報

| # | 診断 | 方法 | 出典 | 状態 |
|---|---|---|---|---|
| 1 | VRChat が OSC を送っているか | 9001 に 10 秒バインドして受信。アドレス・型・件数/秒を集計 | https://docs.vrchat.com/docs/osc-overview（送信 9001 既定） | 確認済（V睡ログの受信部を流用） |
| 2 | 9000/9001 を掴んでいるプロセス | `psutil.net_connections(kind="udp")` で PID → プロセス名。バインドに失敗したら「○○が使っています」 | psutil docs https://psutil.readthedocs.io/ | **Windows で UDP の所有 PID が非管理者で取れるか未確認**。取れなければ「他のアプリが使用中」＋既知アプリ名の候補で案内 |
| 3 | VRChat の OSCQuery が見えるか | mDNS で `_oscjson._tcp` を検索し、VRChat のサービスを見つけて `/?HOST_INFO` を読む → VRChat 側の受信ポートと OSC 有効状態 | https://github.com/vrchat-community/osc/wiki/OSCQuery | 確認済（zeroconf でブラウズ。VRChat のサービス名の実値は未検証） |
| 4 | 自分（アプリ）が VRChat に見つけてもらえるか | 自分を `_oscjson._tcp` で広告し、割り当てポートに VRChat から届くか | 同上 | 確認済（V睡ログの広告部を流用）。実機で VRChat が見つけるかは**未検証**（V睡ログと同じ） |
| 5 | 頭・手首トラッキングの同意 | 4 で `/tracking/vrsystem/*` が来なければ「設定 Allow Sending Head and Wrist VR Tracking OSC Data を ON」と案内 | https://wiki.vrchat.com/wiki/Settings | 設定名は確認済。アドレスは V睡ログと同じ |
| 6 | アバター JSON キャッシュ | `%LOCALAPPDATA%Low\VRChat\VRChat\OSC\usr_*\Avatars\*.json` の有無・更新日時。古ければ削除を案内（削除するならバックアップ付き） | https://tech.framesynthesis.co.jp/vrchat/ , https://booth.pm/ja/items/5384837 | パス確認済 |
| 7 | 起動引数 `--osc=` | `psutil` で VRChat.exe のコマンドラインを読み、ポートが既定と違えば表示 | https://docs.vrchat.com/docs/osc-overview | 確認済（読めない環境ではスキップ） |
| 8 | install.exe の残留 | プロセス一覧に `install.exe` があれば警告 | https://feedback.vrchat.com/bug-reports/p/installexe-breaks-osc-port-binding（egress ブロック、検索要約） | 未確認（プロセス名の実値） |
| 9 | ゲーム内で OSC を OFF→ON した後の送信停止 | 3 は見えるのに 4 で届かない場合に「VRChat を再起動してください」と案内 | https://feedback.vrchat.com/bug-reports/p/toggling-osc-in-game-breaks-all-existing-oscquery-connections-forever | 未確認（修正済みの可能性） |

### この環境で検証できる範囲 / できない範囲

| 検証できる（模擬 VRChat・フィクスチャ） | できない（README に未検証と書く） |
|---|---|
| 受信集計、レポート生成、判定ロジック（各原因のパターンを模擬で再現） | 実 VRChat の mDNS サービス名・HOST_INFO の中身 |
| 自分の OSCQuery 広告（プローブで検証済み） | Windows での UDP 所有プロセス名の取得（CI の windows-latest で最低限は確認可能） |
| ポート占有時の表示（テスト内で先にバインド） | VRChat の起動引数・install.exe 残留の実物 |
| キャッシュフォルダの判定（テンポラリで再現） | Windows Firewall の影響 |

### 外部依存

- python-osc（Unlicense）、zeroconf（LGPL-2.1+）、psutil（BSD-3）。V睡ログと同じ CI で exe 化。

### 失敗しやすい点

- 「直す」機能（キャッシュ削除・プロセス終了）は利用者のファイルとプロセスに触る → **既定は診断のみ**。削除はバックアップ付きで明示操作、プロセス終了はしない（案内のみ）
- 自分が 9001 を占有している間は他の固定ポートアプリが受信できない → 診断は 10 秒で終了し、常駐しない
- Defender SmartScreen → README に定型説明（V睡ログと同じ）
- 無料なので問い合わせが増える → レポート txt で一次切り分けを利用者側で済ませる設計

## Step 3: Go / No-Go

**Go**。競合が「受信側のみ」「キャッシュ削除のみ」「英語・要ビルド」に分かれていて、まとめて日本語で案内するものが無い。無料なので価格根拠は不要、認知が目的。部品の 8 割が V睡ログにあり、この環境で全部テストできる。

## 論点（回答待ち）

### 論点 1: 「直す」までやるか
- **提案**: 診断＋案内が基本。自動で直すのは「アバター JSON キャッシュのバックアップ付き削除」だけ（`--fix-cache` で明示）。プロセス終了はしない
- **理由**: 無料ツールが利用者の環境を壊すと信用を失う。キャッシュ削除だけは定番で、バックアップすれば戻せる
- **選択肢**: A) 提案どおり / B) 診断のみ（何も変更しない） / C) install.exe 終了なども自動
- **確認**: どれにしますか？（推奨 A）

### 論点 2: 販売形態
- **提案**: 無料＋ブースト（投げ銭）任意
- **理由**: Booth の無料品はまとめ記事・フォロー動線になる。ブーストは価格を上げずに応援を受けられる
- **選択肢**: A) 無料＋ブースト / B) 完全無料（ブーストなし） / C) 無料版＋有料の常駐監視版
- **確認**: どれにしますか？（推奨 A。C は後から足せる）

### 論点 3: 商品名
- **提案**: 「OSCドクター for VRChat」（ディレクトリ `osc-doctor`）
- **理由**: 「診断してくれる」が名前で分かる。V睡ログの `doctor` コマンドとも揃う
- **選択肢**: A) OSCドクター for VRChat / B) VRChat OSC 健康診断 / C) 別案
- **確認**: どれにしますか？
