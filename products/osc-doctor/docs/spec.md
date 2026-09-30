# OSCドクター for VRChat 仕様  v0.1

レビュー: 2026-09-30（受信ポートの決め方、固定ポートの横取り防止、OSCQuery の直接確認、無受信時の延長、トラッキング判定の条件を修正）

作成日: 2026-09-30 / 企画: `docs/concept.md` / 市場調査: `docs/market/osc-diagnostic-tool-2026-09.md`

## 概要

VRChat の OSC が「動かない」ときに、ダブルクリックで約 15 秒の診断を行い、原因と次にすることを日本語で表示する Windows 用ツール。
VRChat が**送っている** OSC を実際に受け取って一覧にし、ポートを使っているアプリ、VRChat の OSCQuery の状態、トラッキング送信の同意、アバター設定キャッシュを順に確認する。
結果はサポートに貼れるレポート（txt、個人を特定する ID は伏せ字）にも保存する。常駐しない。自動で直すのはアバター設定キャッシュの退避（明示オプション）だけ。無料配布。

## 対応環境 / 前提ソフト

| 環境 | 対応 |
|---|---|
| PC VR | ○ すべての診断 |
| デスクトップモード | ○（トラッキング送信の診断だけ「VR のみ」として省略） |
| Meta Quest 単機（PC なし） | × 非対応 |

- Windows 10 / 11（64bit）。管理者権限は不要。
- VRChat（PC 版）。VRChat が起動していなくても実行はでき、その旨を診断結果に出す。

## 入力

### OSC 受信（VRChat → 本ツール）

| 経路 | ポート | 内容 |
|---|---|---|
| 固定ポート | `--out-port`（既定 9001、VRChat の送信既定値） | VRChat が固定で送る先。**他のアプリが使っていれば受信しない**（奪わない）。判定は psutil の持ち主情報を主とし、持ち主が他プロセスならバインドしない。バインドは `0.0.0.0` に対して行い、Windows では `SO_EXCLUSIVEADDRUSE` を付ける（Windows は既定で「0.0.0.0 に束縛済みのポートへ 127.0.0.1 で二重に束縛できる」ため、そのままだと他アプリの受信を 10 秒間横取りしてしまう。**Windows の挙動は未検証**） |
| OSCQuery | 空き UDP ポートを自動取得 | 本ツールを `_oscjson._tcp` / `_osc._udp` で広告し、`/avatar` と `/tracking/vrsystem` を公開 → VRChat が見つけて送ってくる |

受信したものはすべて集計する（アドレス、型タグ、件数、受信経路、最初と最後の受信時刻）。値そのものは保存しない。ただし次は統計を取る:
- `/tracking/vrsystem/head/pose` ほか `/tracking/vrsystem/*`：件数/秒、各成分の最小・最大（単位と頻度の確認用。V睡ログの未検証項目の確定に使う）
- `/avatar/parameters/VRMode`：最後の値（VR / デスクトップの判定）
- `/avatar/change`：受信の有無だけ（値はアバター ID なので保存しない）

受信アドレスの意味は https://github.com/vrchat-community/osc/wiki と https://github.com/vrchat-community/osc/wiki/OSCQuery による（`/avatar` は `/avatar/change` と `/avatar/parameters/*`、`/tracking/vrsystem` は頭・手首。トラッキングは VRChat 内の同意後のみ）。

**VRChat はアバターパラメータを「変化したとき」に送る。** そのため計測中は画面に「体を少し動かす・手の形を変える・しゃべってください」と表示する。VR のトラッキングは常時送られる想定（頻度は未検証）。

### VRChat の OSCQuery サービス

- mDNS で `_oscjson._tcp.local.` をブラウズし、インスタンス名が `VRChat-Client-` で始まるものを VRChat とみなす（例 `VRChat-Client-07091F`。出典: 検索要約 https://github.com/vrchat-community/vrc-oscquery-lib/issues/28 ／ https://feedback.vrchat.com/bug-reports/p/vrchat-client-advertises-loopback-address-as-oscquery-service-endpoint）。
- 見つけたら `http://<addr>:<port>/?HOST_INFO` を GET。使う項目は `NAME`, `OSC_IP`, `OSC_PORT`, `OSC_TRANSPORT`（出典: vrc-oscquery-lib `HostInfo.cs`）。`OSC_PORT` が VRChat の受信ポート。
- `http://<addr>:<port>/` を GET し、ルートの `CONTENTS` に `avatar` があるか（あれば OSC が有効でアバターが読み込まれている）。
- ブラウズ時間は `--browse-seconds`（既定 3 秒。mDNS の応答は通常 1 秒以内に届くため、余裕を見て 3 秒）。
- **mDNS で見つからなければ `http://127.0.0.1:<oscquery-port>/?HOST_INFO` を直接 GET する**（VRChat の OSCQuery HTTP は既定で TCP 9001。出典: vrc-oscquery-lib Readme「VRChat will start a TCP service at http://localhost:9001 by default, or whatever port you have specified with your launch arguments」。`--oscquery-port` で変更、既定は起動引数の outPort があればそれ、なければ 9001）。応答があれば「見つかった（直接）」として扱い、mDNS では見えなかった事実を別に記録する（→ ファイアウォールか mDNS の問題であって OSC は ON、と切り分けられる）。
- `NAME` が `VRChat-Client-` で始まらなくても、HTTP が応答すれば VRChat とみなし、NAME をレポートに残す（実機の NAME は未検証のため）。

### 「VRChat の受信ポート」の決め方

以後の判定で使う VRChat の受信 UDP ポートは、次の優先順で 1 つに決める:
1. HOST_INFO の `OSC_PORT`（見つかった場合。VRChat は起動時に 9000 が塞がっていると別の空きポートを選ぶことがあるため、これが最も確か。出典: https://docs.vrchat.com/docs/vrchat-202331 の検索要約「VRChat will automatically find a good UDP port if you turn on OSC at runtime」）
2. `--in-port` の明示指定
3. VRChat の起動引数 `--osc=` の inPort
4. 9000

1 と 2〜4 が食い違うときは「情報」で両方を表示する（固定ポートで送るアプリは 1 の値に送る必要がある）。

### プロセスとポート（psutil）

- VRChat の起動確認: プロセス名 `VRChat.exe`（大文字小文字を無視）。
- 起動引数: VRChat.exe のコマンドラインから `--osc=<inPort>:<senderIP>:<outPort>` を読む（出典: https://docs.vrchat.com/docs/osc-overview）。あれば以後の既定ポートをこの値に置き換える（`--in-port` / `--out-port` を明示した場合は明示を優先）。読めなければ省略。
- ポートの持ち主: `psutil.net_connections(kind="udp")` から `laddr.port` が一致するものの PID → プロセス名。取れない（権限・例外）場合は「使用中（アプリ名は取得できませんでした）」。
- `install.exe` という名前のプロセスがあれば警告（VRChat のインストーラが残ってポートを掴む不具合。出典: https://feedback.vrchat.com/bug-reports/p/installexe-breaks-osc-port-binding ／ egress ブロックのため検索要約）。

### アバター設定キャッシュ

- 場所: `%LOCALAPPDATA%Low\VRChat\VRChat\OSC\usr_*\Avatars\*.json`（出典: https://tech.framesynthesis.co.jp/vrchat/）。
- 集計: ユーザーフォルダ数、JSON 数、最新の更新日時。
- `OSCDOCTOR_VRC_DIR` 環境変数で `...\VRChat\VRChat` の場所を上書きできる（テスト用・特殊環境用）。

### 設定ファイル

なし。すべてコマンドラインで指定する（無料の単発ツールなので、設定ファイルを増やさない）。

## 出力

### 画面

```
OSCドクター for VRChat 0.1.0
計測中… 10 秒（体を少し動かす・手の形を変える・しゃべってください）

[OK]   VRChat         起動しています（起動引数 --osc なし）
[OK]   ポート 9000    VRChat.exe が受信に使っています
[情報] ポート 9001    VRCFaceTracking.exe が使っています（OSCドクターは OSCQuery で受信します）
[OK]   OSCQuery       VRChat を見つけました（VRChat-Client-07091F、受信ポート 9000）
[OK]   受信           VRChat から 23 種類・412 件届きました（OSCQuery 経由）
[注意] トラッキング   頭・手首の位置が届いていません
         → VRChat の設定で「Allow Sending Head and Wrist VR Tracking OSC Data」を ON にしてください
[情報] キャッシュ     アバター設定 14 件（最新 2026-09-29 23:10）

結果: 注意 1 件。レポートを保存しました: C:\Users\…\Documents\OscDoctor\report-20260930-221530.txt
Enter キーを押すと閉じます…
```

- 状態は 4 種: `OK` / `情報`（問題ではないが知っておくこと）/ `注意`（一部の機能が動かない）/ `NG`（OSC が動かない原因）。
- `→` の行に「次にすること」を 1〜2 行。
- `--verbose` で受信したアドレスの一覧（アドレス・型・件数・経路）も画面に出す。レポートには常に入る。

### レポート（txt）

- 保存先: `ドキュメント\OscDoctor\report-YYYYMMDD-HHMMSS.txt`（`--out <dir>` で変更、`--no-report` で保存しない）。UTF-8（BOM 付き。メモ帳で文字化けしないため）。
- 内容: ツールのバージョン、実行日時、Windows のバージョン（`platform.platform()`）、各診断の結果と次にすること、受信アドレス一覧（アドレス・型タグ・件数・経路）、トラッキングの統計（件数/秒、各成分の最小・最大）、ポートの持ち主、キャッシュの集計。
- 伏せ字（プライバシー参照）を必ず通す。
- 末尾に 1 行だけ作者の他のツールの案内（「VR 睡眠を記録するツール『V睡ログ』もあります（Booth）」）。

### OSC 送信（`--send-test` 指定時のみ）

- `/chatbox/input` に `["OSCドクター: 送信テスト", true, false]` を VRChat の受信ポートへ 1 回送る（出典: https://github.com/vrchat-community/osc/wiki の chatbox）。VRChat は届いたことを返さないため、画面に「頭の上にチャットが出たら VRChat への送信は正常です」と表示する（結果は `情報`）。
- 既定では何も送らない。

### キャッシュの退避（`--fix-cache` 指定時のみ）

- `...\VRChat\VRChat\OSC` フォルダを丸ごと `<--out の場所>\backup\OSC-YYYYMMDD-HHMMSS\`（既定 `ドキュメント\OscDoctor\backup\…`）へ**移動**する（削除しない。戻すときは移動し返すだけ）。
- 実行前に対象パスと件数を表示し `y` の入力を求める（`--yes` で省略）。
- 移動後に「VRChat で OSC を Disable → Enable にするか、アバターを着替え直してください」と案内（出典: https://x.com/kaku_vrc/status/1731984683196424669）。
- OSC フォルダが無ければ何もしない。移動に失敗したら（使用中など）何も変えずにエラーを出す。

## 画面 / CLI

実行ファイル `osc-doctor.exe`。

| 起動方法 / オプション | 動作 |
|---|---|
| ダブルクリック（引数なし） | 全診断 → 画面表示 → レポート保存 → Enter 待ち |
| `--seconds N` | 受信の計測時間（既定 10、1〜120） |
| `--browse-seconds N` | VRChat の OSCQuery を探す時間（既定 3、1〜30） |
| `--in-port N` / `--out-port N` | VRChat の受信 / 送信ポート（既定 9000 / 9001。VRChat の起動引数が読めればその値） |
| `--oscquery-port N` | VRChat の OSCQuery HTTP ポート（mDNS で見つからないときの直接確認用。既定 9001） |
| `--send-test` | チャットボックスに送信テスト |
| `--fix-cache` | アバター設定キャッシュを退避（確認あり） |
| `--yes` | 確認を省略 |
| `--verbose` | 受信アドレス一覧も画面に |
| `--out DIR` / `--no-report` | レポートの保存先 / 保存しない |
| `--no-pause` | 終了時に Enter を待たない |
| `--version` | バージョンを表示して終了 |

終了コード: `0` = NG なし、`1` = NG あり、`2` = ツール自体のエラー（引数不正を含む）。
Enter 待ちは「引数なしで起動したとき」だけ（`--no-pause` が無くても、引数ありなら待たない）。

## 状態遷移・主要ロジック

処理順（計測は並行、判定は最後にまとめて）:

1. **環境収集**（`probe.collect_system`）: VRChat プロセス、起動引数、`install.exe`、各ポートの持ち主、キャッシュ集計。
2. **受信開始**: 固定ポートでバインドを試み（失敗は記録）、OSCQuery 用 UDP と HTTP を起動して広告。
3. **VRChat の OSCQuery を探す**（受信と並行、`--browse-seconds`）。
4. **計測**（`--seconds`）。残り秒数を 1 行で表示。**計測終了時点で 1 件も受信していなければ、「アバターを動かす・しゃべる」を強調表示してもう一度同じ秒数だけ計測する（延長は 1 回だけ）。** VRChat はパラメータを変化時にしか送らないため、静止していると正常でも 0 件になりうる。
5. 受信・広告を停止し、`--send-test` があれば送信。
6. **判定**（`checks.judge(facts) -> list[Finding]`、副作用なしの純関数）。
7. 表示、レポート保存、`--fix-cache` があれば退避。

判定表（上から評価。1 つの事実から複数の Finding が出てよい）:

| ID | 条件 | 状態 | 次にすること |
|---|---|---|---|
| VRC_NOT_RUNNING | VRChat.exe が無い | NG | VRChat を起動してから再度実行 |
| VRC_RUNNING | ある | OK | —（起動引数 `--osc` があれば値を表示） |
| INSTALLER_LEFT | `install.exe` がある | 注意 | タスクマネージャーで終了するか PC を再起動 |
| IN_PORT_VRC | 「VRChat の受信ポート」の持ち主が VRChat | OK | — |
| IN_PORT_OTHER | 「VRChat の受信ポート」の持ち主が VRChat 以外 | NG | そのアプリを閉じるか、ポートを変える（起動引数 `--osc`） |
| IN_PORT_FREE | 「VRChat の受信ポート」が空き、VRChat 起動中、OSCQuery で見つからない | NG | VRChat の OSC が OFF。アクションメニュー → Options → OSC → Enabled |
| IN_PORT_STALE | 「VRChat の受信ポート」が空き、OSCQuery では見つかった | 注意 | VRChat の状態が食い違っている。VRChat を再起動 |
| IN_PORT_UNKNOWN | 使用中だが持ち主不明 | 情報 | — |
| IN_PORT_ROUTED | 9000 の持ち主が VRChat 以外で、HOST_INFO の受信ポートが 9000 以外 | 情報 | ルーター構成（例: VRChatOSCRouter）。固定ポートのアプリは 9000 のそのアプリに送る |
| OUT_PORT_OTHER | 送信ポート（9001）を他アプリが使用 | 情報 | 固定ポートのアプリは 1 つしか受信できない。OSCQuery 対応アプリは影響なし |
| OQ_FOUND | mDNS で `VRChat-Client-*` が見つかり HOST_INFO が読めた | OK | 受信ポートを表示。`OSC_PORT` と `--in-port` が違えば「情報」で両方表示 |
| OQ_FOUND_DIRECT | mDNS では見えず、直接 HTTP では読めた | 注意 | OSC は ON だが mDNS が通っていない（ファイアウォール／他の mDNS ソフトの干渉）。OSCQuery 対応アプリが VRChat を見つけられない可能性。固定ポートのアプリは動く |
| OQ_NOT_FOUND | どちらでも見つからない、VRChat 起動中 | 注意 | OSC が OFF の可能性が高い。Enabled にして再実行 |
| OQ_NO_AVATAR | 見つかったがルートに `avatar` が無い | 注意 | アバターを読み込み直す |
| RX_OK | 何か受信した | OK | 経路（OSCQuery / 固定 / 両方）と件数 |
| RX_NONE_OQ | 延長後も何も受信せず、OQ_FOUND または OQ_FOUND_DIRECT | NG | ゲーム内で OSC を OFF→ON した後は OSCQuery のアプリに送られなくなる不具合がある → VRChat を再起動（出典: feedback「Toggling OSC in game breaks…」）。アバターが読み込み中でないかも確認 |
| RX_NONE | 延長後も何も受信せず、OQ が見つからない、VRChat 起動中 | NG | OSC を Enabled に。固定ポートが他アプリに使われていれば閉じる |
| RX_ONLY_FIXED | 固定ポートでだけ受信、OSCQuery では無受信、OQ_FOUND | 注意 | OSCQuery アプリが受信できない状態。VRChat を再起動 |
| TRACKING_OK | `/tracking/vrsystem/*` が届いた | OK | 件数/秒を表示 |
| TRACKING_DESKTOP | VRMode = 0 を受信 | 情報 | デスクトップのため対象外 |
| TRACKING_MISSING | OSCQuery 経由の受信があり、`/tracking/vrsystem/*` なし、VRMode = 1 または VR ランタイム（`vrserver.exe` = SteamVR）が起動中 | 注意 | 同意設定「Allow Sending Head and Wrist VR Tracking OSC Data」を ON（出典: https://wiki.vrchat.com/wiki/Settings） |
| TRACKING_UNKNOWN | OSCQuery 経由の受信があり、トラッキングなし、VRMode 不明かつ VR ランタイムなし | 情報 | デスクトップなら対象外。VR なら上と同じ同意設定を確認 |
| TRACKING_NOT_JUDGED | OSCQuery 経由の受信が無い（固定ポートのみ、または無受信） | （出さない） | トラッキングは OSCQuery で `/tracking/vrsystem` を公開したアプリにだけ送られるため、固定ポートで来ないのは正常（出典: osc wiki OSCQuery） |
| CACHE_INFO | キャッシュの集計 | 情報 | RX で `/avatar/parameters/*` が 0 件かつ受信はある場合、「`--fix-cache` を試す」を併記 |
| CACHE_NONE | OSC フォルダなし | 情報 | — |

- VRChat が起動していないときは RX_* / TRACKING_* / OQ_* / IN_PORT_* を出さない（原因が明らかなため）。
- `VRMode` は変化時にしか送られないため 10 秒の計測では「不明」が普通。VR ランタイムの判定は `vrserver.exe`（SteamVR）のみ（Oculus / Virtual Desktop の PC 側プロセス名は**未確認**のため使わない）。
- 「結果:」行は NG 件数 → 注意件数の順で要約。全部 OK/情報なら「問題は見つかりませんでした」。

## エラーと復旧

| 状況 | 挙動 |
|---|---|
| 固定ポートが使用中 | 受信を試みず記録（OUT_PORT_OTHER）。診断は続行 |
| mDNS が使えない（例外） | OSCQuery の広告・ブラウズを省略し、該当 Finding を「確認できませんでした（mDNS が使えません）」の情報で出す |
| psutil が例外 | 該当項目を「取得できませんでした」で続行 |
| レポートの保存失敗 | 画面にエラーを出し、終了コードは判定どおり |
| `--fix-cache` の移動失敗 | 何も変えず「VRChat を終了してから再度実行してください」、終了コード 2 |
| 想定外の例外 | トレースバックを表示、終了コード 2、ダブルクリック時は Enter 待ち |
| Ctrl+C | 計測を打ち切り、その時点までの結果で判定する |
| 初回起動時の Windows ファイアウォールの確認ダイアログ | 本ツールが UDP/TCP を待ち受けるため出ることがある。README に「プライベート ネットワークで許可」を書く。ブロックされても同一 PC 内（127.0.0.1）の通信は通る想定（**未検証**） |

## 設定項目一覧

CLI オプション（上表）が全て。既定値の根拠: ポート 9000/9001 は VRChat の既定、計測 10 秒はパラメータの変化を拾うための最小限（トラッキングは常時送信の想定）、ブラウズ 3 秒は mDNS 応答の余裕。

## 既知の制限・未検証事項

- VRChat の mDNS インスタンス名 `VRChat-Client-*` は検索要約での確認。実機で見つからない場合は OQ_NOT_FOUND になる（**未検証**）。
- VRChat が OSCQuery で本ツールを見つけて送ってくるか（V睡ログと同じ、**未検証**）。
- Windows で UDP ポートの持ち主（PID）が非管理者で取れるか（**未検証**。CI の windows-latest で起動までは確認）。
- ゲーム内 OSC の OFF→ON 不具合の現状（修正済みの可能性。**未確認**）。
- Windows ファイアウォールの状態は調べない。
- Windows で `0.0.0.0` 束縛済みポートへの二重束縛（`SO_EXCLUSIVEADDRUSE` の効き方）は**未検証**。
- VRChat の OSCQuery HTTP が既定で TCP 9001 にあること、起動引数のどの値で変わるかは Readme の記述のみで**未検証**。
- トラッキングの頻度・値の範囲はレポートに出すだけで判定には使わない。

## セキュリティ / プライバシー

- インターネットへの送信は一切しない。通信は同じ PC 内（mDNS はローカルネットワーク）。
- 保存するのはレポート txt のみ。他人の表示名は扱わない（VRChat ログは読まない）。
- レポートでは次を伏せ字にする: `usr_…` → `usr_xxxx`、`avtr_…` → `avtr_xxxx`、`wrld_…` → `wrld_xxxx`、Windows のユーザー名を含むパス（`C:\Users\<名前>\` → `%USERPROFILE%\`）。アバターパラメータ名はそのまま（個人を特定しないため。README に明記）。
- `--fix-cache` は移動のみ。削除しない。

## ビルド

- 依存: python-osc（Unlicense）、zeroconf（LGPL-2.1+）、psutil（BSD-3-Clause）。`pyinstaller.args` に `--collect-submodules zeroconf --collect-submodules osc_doctor`（V睡ログと同じ）。
- `build-windows.yml` に「商品フォルダに `smoke.args` があれば、`--version` に加えて `<exe> <smoke.args>` を実行し、終了コード 0 または 1 を合格とする」を追加する。osc-doctor の `smoke.args` は `--no-pause --no-report --seconds 1 --browse-seconds 1`（VRChat が無い CI で最後まで走り、psutil と zeroconf が Windows で動くことを確認）。

## 出典

- https://docs.vrchat.com/docs/osc-overview
- https://docs.vrchat.com/docs/osc-debugging
- https://github.com/vrchat-community/osc/wiki
- https://github.com/vrchat-community/osc/wiki/OSCQuery
- https://github.com/vrchat-community/vrc-oscquery-lib（`HostInfo.cs`, `Readme.md`）
- https://github.com/vrchat-community/vrc-oscquery-lib/issues/28
- https://feedback.vrchat.com/bug-reports/p/vrchat-client-advertises-loopback-address-as-oscquery-service-endpoint
- https://feedback.vrchat.com/bug-reports/p/installexe-breaks-osc-port-binding
- https://feedback.vrchat.com/bug-reports/p/toggling-osc-in-game-breaks-all-existing-oscquery-connections-forever
- https://wiki.vrchat.com/wiki/Settings
- https://tech.framesynthesis.co.jp/vrchat/
- https://x.com/kaku_vrc/status/1731984683196424669
- https://psutil.readthedocs.io/
