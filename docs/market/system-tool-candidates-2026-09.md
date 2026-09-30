# システム系商品の候補（調査日: 2026-09-29）

制約: AI 製ビジュアル不可 / オーナーは実機デバッグしない / この環境（Linux, Unity・VRChat なし）で検証できること。

## 結論（3行以内）
- 本命: **V睡ログ**（OyasumiVR の隣に置く睡眠ダイアリー）。競合なし、文脈（癒やし・ポケスリ）が強い、模擬 OSC＋ログで全テスト可。
- 並行: **unitypackage 検品ツール**（出品者向け B2B）。競合ゼロ、Unity 不要で完結。
- Blender アドオンは完全にテストできるが単体では薄利（HatoTools: 80 本で累計 460）。露出用の小物枠。

## 候補と評価
| # | 候補 | 対象 | 競合 | 想定価格 | ここで検証 | 判定 |
|---|---|---|---|---|---|---|
| 1 | V睡ログ（睡眠時間・同席者・週間グラフ・X 用カード） | VR 睡眠勢 | 専用品なし。OyasumiVR は無料で検知/ミュート/ポーズまで（ログ分析は無い）。おやすみレコーダー ¥有料 が同じ隙間で成立 | ¥800〜1,500 | ◎ | **Go** |
| 2 | unitypackage 検品（同梱漏れ・他者アセット混入・参照切れ・README/規約生成） | Booth 出品者 | 実物検品は無し。書き出し側は Yan-K Smart Package（無料、2026/05）あり | ¥1,000 前後（無料版＋有料版） | ◎ | **条件付き Go**（詳細: `unitypackage-inspector-2026-09.md`） |
| 3 | 配信者向けログ連動 OBS（Private 入室で自動ミュート/シーン切替、ワールド名表示） | 配信者 | マイクミュート同期（無料）程度 | ¥1,000 | ○（obs-websocket モック） | 条件付き |
| 4 | イベント主催者向け開催後レポート（来場数・滞在・リピーター） | 主催者 | 受付/整理券/抽選 Bot はあるが「終わった後」は無い | ¥1,000 | ◎ | 条件付き |
| 5 | Blender 小物アドオン（量産） | 改変勢 | HatoTools ほか多数 | ¥500 | ◎ | 露出用 |

## 競合・参考
| 名前 | 種別 | 価格 | 備考 | URL |
|---|---|---|---|---|
| OyasumiVR | 無料 (Steam/GitHub) | 0 | 睡眠検知・ミュート・寝相ポーズ・招待自動承認・**スリープモード時に OSC 送信可・OSCQuery 対応** | https://github.com/Raphiiko/OyasumiVR/blob/develop/docs/readmes/generated/README_JA.md |
| おやすみレコーダー | 有料 | — | 誰か来た時だけ OBS 録画。OyasumiVR 連動 | https://booth.pm/ja/items/6982052 |
| VRC睡眠システム / RBS SuiminSystem | 有料ギミック | — | 寝る姿勢系。ログ分析なし | https://booth.pm/ja/items/3406857 |
| VRCX / VRChatLifelog / VRC Friend Connect | 無料/有料 | — | ログ日記系は飽和 | https://github.com/vrcx-team/VRCX |
| KonoAsset / Avatar Explorer | 無料 | 0 | アセット管理は飽和 | https://booth.pm/ja/items/6641548 |
| HatoTools | Blender アドオン | ¥700 前後 | 80 本・累計 460 | https://fdaerjioa.booth.pm/ |
| VRChat Instant Video | PC アプリ | ¥900〜 | 配信/録画系は売れている例 | （note まとめ）https://note.com/kotoha_siro_page/n/nfaabdee1afc1 |
| VRChat受付システム / 整理券 | ワールドギミック | — | 主催者向けは事前工程のみ | https://booth.pm/ja/items/7403532 |

## 技術メモ（一次情報）
- VRChat OSC: 受信 9000 / 送信 9001、`/avatar/parameters/<Name>`（int/float/bool）、`/chatbox/input`。docs.vrchat.com は egress ブロック。要約: https://github.com/vrchat-community/osc/wiki
- ログ形式: `yyyy.MM.dd HH:mm:ss Log        -  [Behaviour] OnPlayerJoined <name>` ほか。VRCX `Dotnet/LogWatcher.cs` のパターンに準拠。**実ログ未取得（未検証）**。
- OyasumiVR: スリープモード切替時に任意 OSC を送信できる → V睡ログはこれを受けて記録開始/終了できる。

## 未確認事項
- OyasumiVR の OSC 送信の既定アドレス（ユーザー設定なので商品側で「このアドレスを設定してください」と案内する想定）。
- 実ログの最新形式（`OnPlayerJoined` に `(usr_...)` が付くか）。
