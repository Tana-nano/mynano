# VRChat OSC 診断ツール（無料配布・ショップ認知用）  (調査日: 2026-09-30)

目的: ショップの認知向上のために最初に無料で配るものを決める。候補「OSC 診断ツール」の競合・需要・根拠。

## 結論（3行以内）
- **やる（無料＋ブースト任意）。** 「OSC が動かない」は OSC を使う全ユーザー（表情・心拍・ハプティクス・OyasumiVR・V睡ログ）に共通の詰まりどころで、既知の原因が複数あるのに、日本語でダブルクリックして原因を切り分けられる道具が無い。
- 差別化は「VRChat が**送っている側**を見せる」「ポートを掴んでいるプロセス名を出す」「既知の原因を順に自動チェックして日本語で案内」の 3 点。VRChat 内蔵の OSC Debug は受信側のみ。
- V睡ログの `doctor` / `oscio` / `vrc_mock` を流用でき、この環境で全部テストできる。副産物として、利用者が貼るレポートから頭の姿勢データの頻度・単位（V睡ログの未検証項目）が分かる。

## 競合一覧
| 名前 | 種別 | 価格 | 強み | 弱み | URL |
|---|---|---|---|---|---|
| VRChat 内蔵 OSC Debug | 公式（アクションメニュー → OSC → OSC Debug） | 0 | 受信中のアドレス・値を表示。開くと OSC が自動で有効化 | **VRChat が送る側は見えない**。ポート衝突や OSCQuery の失敗は分からない | https://docs.vrchat.com/docs/osc-debugging |
| OSCキャッシュリセッター | Booth（無料） | 0 | `LocalLow\VRChat\VRChat\OSC` を消す定番対処をワンクリック化 | それ以外の原因（ポート衝突・同意設定・OSCQuery）は対象外。Booth ページは egress ブロックのため検索要約のみ | https://booth.pm/ja/items/5384837 |
| VRC-OSC-looker | GitHub（Rust, TUI） | 0 | VRChat が送る OSC をライブ表形式で表示、履歴・変化検出、ローカル完結 | 英語、要 cargo ビルド、Star 0。診断（原因案内）はしない | https://github.com/AutomaticDuckCollection/VRC-OSC-looker |
| VRCWG | GitHub | 0 | 監視ツール。OSC 表示・オーバーレイ・プレイヤー情報 | 多機能で重い。英語 | https://github.com/anonymous98268/VRCWG |
| vrc-osctool | GitHub（Node.js） | 0 | Web UI から OSC を送る設定ツール | 送信専用。診断ではない。Star 0 | https://github.com/kabotya713/vrc-osctool |
| Log_Monitor 同梱 server.exe | Booth | — | 受信 OSC を見る補助（検索要約より） | 「現環境には対応していない可能性」と注記あり | https://booth.pm/ja/items/4110099 |
| Protokol / TouchOSC | 汎用 OSC モニタ（公式が推奨） | 0 / 有料 | 汎用で確実 | VRChat 固有の原因は教えてくれない。日本語なし | https://github.com/vrchat-community/osc/wiki |

## 無料の強豪
- OSC 系の無料 Booth ツールは「送る」側に集中: OSC メッセージ送信、Chatbox 送信、OSC 操作自動化、OSC Clock（https://booth.pm/en/browse/Software?tags%5B%5D=OSC）。「診断する」ものは上記キャッシュリセッターのみ。
- 手順記事は多い（note「OSC についての知見とメモ」https://note.com/yui0471/n/n0ce6b48ef025、X の「disable → reset config → enable」https://x.com/kaku_vrc/status/1731984683196424669）。= 需要はあるが道具化されていない。

## トレンド・公式アップデートの影響
既知の「動かない原因」（すべて公式 docs / feedback / wiki に記録あり。feedback.vrchat.com は egress ブロックのため検索要約）:
1. **ポート衝突**: VRChat は受信 9000 / 送信 9001。他アプリ（VRCFaceTracking 等）が同じポートを使うと衝突。起動引数 `--osc=inPort:senderIP:outPort` で変更可（https://docs.vrchat.com/docs/osc-overview, https://github.com/vrchat-community/osc/wiki）。
2. **install.exe がポートを掴んだまま残る**: 手動でプロセス終了か再起動が必要（https://feedback.vrchat.com/bug-reports/p/installexe-breaks-osc-port-binding）。
3. **ゲーム内で OSC を OFF→ON すると、OSCQuery で接続済みのアプリへの送信が止まる**（https://feedback.vrchat.com/bug-reports/p/toggling-osc-in-game-breaks-all-existing-oscquery-connections-forever）。修正状況は未確認。
4. **OSCQuery が既定ポート 9000 を誤って広告**: 2024.1.1 で修正（https://feedback.vrchat.com/bug-reports/p/oscquery-vrchat-reports-the-incorrect-listening-port-for-osc-when-changing-it-vi）。
5. **アバター JSON キャッシュが古い**: `LocalLow\VRChat\VRChat\OSC\<usr_id>\Avatars\*.json` が更新されない問題。2024.3.1 Build 1490 で解決とされるが、依然として定番対処として案内されている（https://tech.framesynthesis.co.jp/vrchat/）。
6. **頭・手首のトラッキング送信は別途同意が必要**: 設定「Allow Sending Head and Wrist VR Tracking OSC Data」（https://wiki.vrchat.com/wiki/Settings）。V睡ログの前提でもある。
7. OSCQuery は 2023.3.1 から。VRChat は OSCQuery 対応アプリを自動で見つけ、アプリごとに新しいポートを開いて送る（https://docs.vrchat.com/docs/vrchat-202331, https://github.com/vrchat-community/osc/wiki/OSCQuery）。

→ 原因が 6〜7 種類に分散しており、ユーザーは「どれか」を切り分けられない。ここが道具の価値。公式が同等の診断機能を出す兆候は見当たらない。

## ユーザー層と需要の根拠
- OSC 利用者: 表情トラッキング（VRCFaceTracking）、心拍（HR-VR-OSC 等）、フルトラ（OSC Trackers、最大 8 点 https://docs.vrchat.com/docs/osc-trackers）、OyasumiVR、Chatbox 系ツール。Booth の OSC タグは 1,984 点（https://booth.pm/ja/search/OSC）。
- Booth の無料配布は「フォロワー ○○人記念」など集客手段として定着している（https://note.com/yugena/n/n5ca31ff80470）。無料ツールは note のまとめ記事に載りやすい（https://note.com/kotoha_siro_page/n/nfaabdee1afc1）。
- 販売数の一次データは Booth が egress ブロックのため取得できず（**未確認**）。

## 差別化の仮説
1. **送信側を見せる**: 9001（または OSCQuery で割り当てられたポート）に 10 秒待ち、届いたアドレス・型・レートを一覧。内蔵 OSC Debug と補完関係。
2. **原因を順に自動判定して日本語で案内**: ポート占有プロセス名 → OSCQuery 応答 → トラッキング同意 → キャッシュ状態 → 起動引数。
3. **サポートに貼れるレポート txt**（ユーザー ID マスク）。他ツールの作者にも「まずこれを貼って」と使ってもらえる形にする。
4. 無料＋ブースト任意。ショップの他ツール（V睡ログ）はレポート末尾と README に一行だけ。

## 未確認事項
- feedback.vrchat.com の各バグの現在の修正状況（3, 4 の再発有無）。
- Booth の競合の DL 数・いいね数（ページが読めない）。
- VRChat が OSCQuery 経由で送るときのポート決定と、固定 9001 に同時に送るかどうか（V睡ログでも未検証）。
- Windows でポート占有プロセス名を取る方法（`psutil.net_connections` は UDP でも取れる想定。要 CI で確認）。

## 出典
- https://docs.vrchat.com/docs/osc-debugging
- https://docs.vrchat.com/docs/osc-overview
- https://docs.vrchat.com/docs/vrchat-202331
- https://docs.vrchat.com/docs/osc-trackers
- https://wiki.vrchat.com/wiki/Settings
- https://github.com/vrchat-community/osc/wiki
- https://github.com/vrchat-community/osc/wiki/OSCQuery
- https://feedback.vrchat.com/bug-reports/p/installexe-breaks-osc-port-binding
- https://feedback.vrchat.com/bug-reports/p/toggling-osc-in-game-breaks-all-existing-oscquery-connections-forever
- https://feedback.vrchat.com/bug-reports/p/oscquery-vrchat-reports-the-incorrect-listening-port-for-osc-when-changing-it-vi
- https://booth.pm/ja/items/5384837
- https://booth.pm/en/browse/Software?tags%5B%5D=OSC
- https://github.com/AutomaticDuckCollection/VRC-OSC-looker
- https://github.com/anonymous98268/VRCWG
- https://github.com/kabotya713/vrc-osctool
- https://note.com/yui0471/n/n0ce6b48ef025
- https://tech.framesynthesis.co.jp/vrchat/
- https://note.com/yugena/n/n5ca31ff80470
