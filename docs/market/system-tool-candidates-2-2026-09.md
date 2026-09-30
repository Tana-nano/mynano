# システム系商品の候補（第 2 弾: 既存候補以外）  (調査日: 2026-09-30)

前提: `system-tool-candidates-2026-09.md` の候補（V睡ログ / unitypackage 検品 / 配信者向け OBS 連動 /
主催者向け開催後レポート / Blender 小物）と `osc-diagnostic-tool-2026-09.md`（OSC ドクター）以外の案を洗い出し、
無料の強豪の有無・この環境で検証できるか・売れる根拠で絞った。
Booth・note・docs.vrchat.com・creators.vrchat.com・help.vrchat.com・vn3.org は egress ブロックのため、
これらの内容は検索結果の要約に依っている（価格・機能は要約に出た範囲のみ記載）。

## 結論（3行以内）
- **新規で残ったのは 3 つ**: (B) アップロード失敗診断（Unity 不要・購入者向け、出品者のサポート窓口にもなる）、
  (C) VN3 規約台帳（購入アセットの「配信 OK / 商用 OK」を一覧化）、(D) 主催者向け進行ツール（既存候補「開催後レポート」と合体して主催者キットにする）。
- 「OSC ルーター・パラメータ保存・写真整理・Chatbox 定型文・Join 通知・複垢切替・Udon ログ・文字起こし・売上分析」は
  無料の強豪が複数あり **やらない**。無料の統合ツール VRCNext（2026-09）も出ており、単機能ユーティリティは吸収される。
- 既存候補との序列: OSC ドクター（無料の入口）→ V睡ログ（有料）→ **(B) を無料の入口 2 号**、**(D)+開催後レポート** と
  **unitypackage 検品** が有料の柱候補。(C) は条件付き。

## 今回検討した候補と判定
| # | 候補 | 対象 | 競合（無料含む） | 想定価格 | ここで検証 | 判定 |
|---|---|---|---|---|---|---|
| A | VRC 落ちる診断（クラッシュ / 起動失敗をログから切り分け、日本語で案内、サポート用レポート） | 全ユーザー | 日本語の道具なし。VRChatAdminTools（露語、「ログだけでは原因特定不可」と自認）。公式 help は手順の羅列 | 無料（入口） | ○ ログ fixtures。実クラッシュログは未入手 | **条件付き**: 単体商品にせず OSC ドクターに「落ちる」タブとして追加 |
| B | アップロード失敗診断（Unity 不要の exe。Editor.log と Unity プロジェクトフォルダを静的解析し、SDK 版・日本語パス・Dynamic Bone 残り・lilToon / MA / VRCFury の版・vpm-manifest を点検） | 改変初心者（新規層の学生 27.9%・女性半数）＋ 出品者 | 記事は大量（ぶいなび・note・知恵袋）だが道具化されていない。ConsoleLogSaver は「共有」のみで Unity 内 | 無料 or ¥500 ＋ 出品者向け案内文テンプレ | ○ fixture プロジェクト＋公開フォーラムのエラー文言。**実 Editor.log 未入手** | **Go 候補**（実 Editor.log を 1 本入手してから） |
| C | VN3 規約台帳（購入品の規約 txt から「改変 / 商用 / 配信 / メディア掲載 / 再配布」の可否を抽出して一覧化。非 VN3 は手入力） | 配信者・企業案件・イベント主催・写真投稿者 | なし。VN3 ジェネレータは「作る側」の道具。「商用 OK・掲載報告不要のホワイトリスト整備」の動きあり | ¥800〜1,200 | ◎ 規約テキスト fixtures | **条件付き**: VN3 v1.10 の原文構造を入手し、機械抽出できる項目を確認してから |
| D | 主催者向け進行ツール（Chatbox に残り時間・次のコーナーを常時表示、アナウンス定型文、join ログで来場者数リアルタイム表示） | イベント主催者・司会 | ワールド側タイマー（Udon Timer 等、Unity と改変が必要）。Chatbox 送信ツールは汎用のみ。「進行」専用の PC アプリは見当たらず | ¥1,000〜1,500（開催後レポートと同梱） | ◎ vrc_mock | **Go 候補**（既存候補 4 と合体） |
| E | VRChat 設定お引っ越し（レジストリ `HKCU\Software\VRChat\VRChat` ＋ config.json ＋ OSC フォルダの退避・復元） | PC 買い替え者 | 専用品なし。VRC Runner（無料）が起動プロファイル管理 | ¥500 | × レジストリは Windows 実機のみ | **やらない**（需要が買い替え時だけ、検証不能） |
| F | 就寝・プレイ時間セルフコントロール（指定時刻に Chatbox 警告→ VRChat 終了） | 夜更かし勢 | 「VRChat強制終了システム」¥400（アバターギミック、MA/lilToon 必要）。OyasumiVR。VRCNext がプレイ時間記録 | — | ◎ | **単体ではやらない**。需要はある（¥400 で成立）ので V睡ログの「就寝リマインダー」機能として吸収 |

## 見送った候補と理由（無料の強豪）
| 候補 | 強豪 | URL |
|---|---|---|
| OSC ルーター（1 ポート→複数アプリ） | OSC Multi Launcher（無料）、OscRaw（無料）、OSC Router、VOR、VRCRouter、VRCOSC 内蔵 | https://booth.pm/ja/items/7828100 / https://booth.pm/ja/items/5108127 / https://booth.pm/ja/items/7074724 / https://github.com/SutekhVRC/VOR / https://github.com/VolcanicArts/VRCOSC/wiki/VRCOSC-Router |
| アバターパラメータのプリセット保存・復元 | AvatarParameterLoader（無料版あり・フル ¥1,000、OSCQuery 対応）、OSCさんといっしょ | https://booth.pm/ja/items/4996160 / https://booth.pm/ja/items/3701540 |
| 写真整理・撮影ワールド記録 | VRChat Photo Manager、スクリーンショット自動整理（無料）、VRC_PhotoToWorld、メタデータ表示 | https://rio-sw.booth.pm/items/6862739 / https://booth.pm/ja/items/8168389 / https://booth.pm/ja/items/8077337 / https://booth.pm/ja/items/7277797 |
| Chatbox 定型文・ホットキー・デスクトップ表情 | ChatBox定型文（無料）、VRC ChatPad、Chatbox Sender、ParticleFlickChat、OSC操作自動化ツール（無料）、ポーズ&表情即出し（無料） | https://booth.pm/ja/items/5633453 / https://booth.pm/ja/items/4386198 / https://booth.pm/ja/items/6895109 / https://booth.pm/ja/items/8217210 / https://booth.pm/ja/items/4247265 |
| Join / フレンド通知（Discord・スマホ） | VRChatJoinNotifier（無料）、VRCNotify（無料）、VRC Friend Connect、フレンドオンライン通知 | https://booth.pm/ja/items/2947584 / https://booth.pm/ja/items/4926880 / https://booth.pm/ja/items/5098669 |
| 複数アカウント切替・起動プロファイル | VRCPS、VRC Runner（無料）、SimpleVRChatLauncher、アカウント別起動ショートカット（無料） | https://booth.pm/ja/items/6830742 / https://booth.pm/ja/items/7898187 / https://booth.pm/ja/items/4177332 |
| Udon ログビューア（ワールド作者） | VRCLogDebugger（無料あり）、ArG0_Console、CHAMCHI Console | https://booth.pm/ja/items/6864249 / https://booth.pm/ja/items/6225557 / https://github.com/kibalab/CHAMCHI_Console |
| 会話の文字起こし・議事録 | VRCT（無料、ローカル音声認識）。他人の音声を録る倫理面の問題もある | https://booth.pm/ja/items/5155325 |
| Booth 売上 CSV 分析（出品者向け） | BoothViz（無料）、売上個数グラフ表示ツール、Freee 変換 | https://booth.pm/ja/items/6575925 / https://booth.pm/ja/items/3085868 / https://booth.pm/ja/items/5519458 |
| Booth 購入品の更新チェッカー | Booth に公開 API がなくスクレイピングは規約リスク。専用品も見当たらず | — |
| PC 通知→Chatbox 転送 | JustNotification（XSOverlay 向け）、VRCNext の Chatbox 機能 | https://zenn.dev/nekobox/scraps/5e46be61b89fca |
| OSC パラメータの録画・再生 | CameraMaster OSC（タイムライン）、モーション記録ギミック | https://machanbazaar.com/vrchat-osc%E3%83%97%E3%83%A9%E3%82%B0%E3%82%A4%E3%83%B3/ / https://booth.pm/ja/items/2970849 |
| イベントカレンダー表示 | EventTT for VRChat（無料、GitHub 公開） | https://booth.pm/ja/items/5822088 |

## トレンド・公式アップデートの影響
| 事項 | 内容 | 影響 | 出典 |
|---|---|---|---|
| VRCNext（無料の統合ツール） | フレンド・グループ・ワールド・アバター管理、行動履歴とプレイ時間の記録、写真整理、OSC / Chatbox / VR ツールを 1 本に。Windows、WebView2 | 単機能ユーティリティ（通知・写真・プレイ時間・Chatbox）は無料統合ツールに吸収される。**診断・主催者・出品者向けの「仕事寄り」に寄せる** | https://booth.pm/ja/items/8691505 |
| VRChat 2026.3.2（9/2） | アクションメニューのテーマカラー対応、パーソナルミラーのプリセット、カメラ「投げて片付け」、アクセサリー購入の改善 | 既存候補に直撃なし | https://metacul-frontier.com/?p=37249 |
| VRChat 2026.3.3（Open Beta） | デスクトップ向け HUD（画面四隅にクリックできるボタン） | デスクトップ操作補助系ツールは公式が改善中。避ける | https://docs.vrchat.com/docs/vrchat-202633-open-beta |
| VN3 ライセンス v1.10 | 6/1 から韓国語・中国語に対応。アバター取引で最も使われる規約テンプレート | (C) の抽出対象が事実上の標準になっている | https://vr-lifemagazine.com/vn3/ / https://www.moguravr.com/vn3-license/ |
| Booth 3D モデル売上 | 2025 年に 100 億円規模。年 10 万円以上のヘヴィ層がミドル層を上回る | 購入品が増える＝規約管理 (C) とアップロード失敗 (B) の母数が増える | https://www.inside-games.jp/article/2026/02/06/177087.html |

## ユーザー層と需要の根拠
- **アップロード失敗 (B)**: 知恵袋・zenn・note・ぶいなび・Ask Forum に「アップロードできない」の記事と質問が多数。既知の原因は
  SDK 3.9.0 未満での新規アップロード不可、Dynamic Bone 残り、ユーザーフォルダの日本語、サムネ未設定、Descriptor 違い、
  lilToon 未導入でピンク化など、種類が分散している（https://vrnavi.jp/unity-error/ / https://zenn.dev/sarashinanoniki/articles/d5cee765cea0f7 /
  https://note.com/moegitsubasa/n/nafcfae7fde16 / https://koshishirai.com/en/unity-vrchat-avatar-upload-solution/）。
  「エラー解決に強いフレンドにコンソールを見せる」文化があり（https://note.com/azukimochi25/n/n042c495e55f4）、
  ConsoleLogSaver のような共有ツールが使われている＝**貼れるレポート**への需要がある。
  出品者側は「Unity バージョン記載なし・動作確認環境がバラバラ」で問い合わせが発生している（https://detail.chiebukuro.yahoo.co.jp/qa/question_detail/q12297611582）。
- **規約台帳 (C)**: 規約はクリエイターごとに違い「必ず確認」と繰り返し案内される（https://www.moguravr.com/vrchat-avatar-update-how-to/）。
  メディア掲載許諾の整理と「商用 OK・報告不要」ホワイトリストの検討（https://note.com/asada_kadura/n/n137a5d63db03）。
  VN3 公式ジェネレータとサードパーティ生成器はあるが、**買った側が一覧化する道具はない**（https://www.vn3.org/generator / https://lowteq.github.io/vn3-easy-generator/）。
- **主催者進行 (D)**: 主催者向けは受付・整理券・カレンダーが有料/無料で成立している（第 1 弾ノート、EventTT）。
  進行中の「残り時間」はワールド側 Udon タイマー（https://booth.pm/ja/items/1977611 / https://booth.pm/ja/items/5150091）しかなく、
  持ち込みワールドに置けない主催者は使えない。
- **落ちる診断 (A)**: 「落ちる」記事は多い（https://www.moguravr.com/vrchat-troubleshooting/ / https://note.com/yama_0825/n/n13acdee6c991 /
  https://note.com/charuktya/n/n043a1c93d71b）が、原因が仮想メモリ・BIOS・ドライバ・EAC・キャッシュとハードウェア寄りで、
  ログから言えるのは「正常終了なしに途切れた」「EAC エラー」「キャッシュ由来のエラー」程度。公式の対処は Clear Local Profile Data /
  Clear Content Cache / EAC 再インストール（https://help.vrchat.com/hc/en-us/articles/1500002247921-VRChat-keeps-crashing-or-has-issues-launching-properly）。
  → 単体商品にする根拠は弱く、OSC ドクターの機能追加が妥当。
- **時間管理 (F)**: 「VRChat強制終了システム」が ¥400 で成立（https://booth.pm/ja/items/8019367）。需要はあるが V睡ログの文脈に吸収できる。

## 既存候補との比較
| 候補 | 対象 | 競合 | 検証 | 単価 | 役割 |
|---|---|---|---|---|---|
| OSC ドクター（実装済） | OSC 利用者 | 弱い | ◎ | 無料 | 入口 1 |
| V睡ログ（実装済） | V睡勢 | なし | ◎ | ¥800〜1,500 | 有料の柱 1 |
| unitypackage 検品 | 出品者 | なし | ◎ | ¥1,500〜2,500 | 有料の柱 2（B2B） |
| **(B) アップロード失敗診断** | 改変初心者＋出品者 | 弱い（記事のみ） | ○（実 Editor.log 未入手） | 無料〜¥500 | **入口 2**。検品ツールと同じ出品者チャネルを共有 |
| 主催者向け開催後レポート ＋ **(D) 進行ツール** | 主催者 | 弱い | ◎ | ¥1,000〜1,500 | 有料の柱 3（主催者キット） |
| **(C) VN3 規約台帳** | 配信者・法人・主催者 | なし | ◎ | ¥800〜1,200 | 条件付き（原文構造の確認待ち） |
| 配信者向け OBS 連動 | 配信者 | 弱い | ○ | ¥1,000 | 条件付き（変わらず） |
| Blender 小物 | 改変勢 | 多い | ◎ | ¥500 | 露出用（変わらず） |

## 差別化の仮説
- (B): 「Unity を開かずにダブルクリックで原因が日本語で出る」「結果を出品者に貼れる」。出品者には商品ページに
  「困ったらこれを実行して結果を送ってください」と書いてもらう導線で、unitypackage 検品と組み合わせて **出品者に配る無料ツール** にする。
- (C): 台帳は「参考情報。必ず原文を確認」を明記し、抽出根拠（規約の該当行）を並べて表示する。責任を負わない設計にする。
- (D): Chatbox 1 本で完結（ワールド改変不要、持ち込みワールドでも使える）。join ログの来場者数と合わせて「開催前・中・後」を 1 つのアプリで。

## 未確認事項
- (B): 実際の `Editor.log`（`%LOCALAPPDATA%\Unity\Editor\Editor.log`）と VRChat SDK の最新エラー文言。creators.vrchat.com が読めず、
  Ask Forum の断片（"Failed to build avatar!", "Avatar validation failed" など）のみ。vpm-manifest.json の項目名も未確認（vcc.docs.vrchat.com がブロック）。
- (C): VN3 v1.10 の条文構造と、生成器が出す形式（PDF か テキストか）。vn3.org / vn3-portal.org が読めなかった。
- (A): クラッシュ時に output_log がどこで途切れるか、crash dump（help.vrchat.com 記事）の形式。
- Booth 各商品の価格・DL 数は検索要約のみ。VRCNext の公開日と利用者規模も未確認。

## 出典
- https://booth.pm/ja/items/7828100 / https://booth.pm/ja/items/5108127 / https://booth.pm/ja/items/7074724 / https://booth.pm/ja/items/5098799
- https://github.com/SutekhVRC/VOR / https://github.com/valuef/VRCRouter / https://github.com/VolcanicArts/VRCOSC/wiki/VRCOSC-Router
- https://booth.pm/ja/items/4996160 / https://booth.pm/ja/items/3701540
- https://rio-sw.booth.pm/items/6862739 / https://booth.pm/ja/items/8168389 / https://booth.pm/ja/items/8077337 / https://booth.pm/ja/items/7277797
- https://booth.pm/ja/items/5633453 / https://booth.pm/ja/items/4386198 / https://booth.pm/ja/items/6895109 / https://booth.pm/ja/items/6423486 / https://booth.pm/ja/items/8217210 / https://booth.pm/ja/items/4247265
- https://booth.pm/ja/items/2947584 / https://booth.pm/ja/items/4926880 / https://booth.pm/ja/items/5098669 / https://booth.pm/ja/items/4268968
- https://booth.pm/ja/items/6830742 / https://booth.pm/ja/items/7898187 / https://booth.pm/ja/items/4177332 / https://booth.pm/ja/items/3726816
- https://booth.pm/ja/items/6864249 / https://booth.pm/ja/items/6225557 / https://github.com/kibalab/CHAMCHI_Console
- https://booth.pm/ja/items/5155325 / https://github.com/lighfu/VRCT-0/pull/3
- https://booth.pm/ja/items/6575925 / https://booth.pm/ja/items/3085868 / https://booth.pm/ja/items/5519458 / https://booth.pm/announcements/515
- https://booth.pm/ja/items/8691505 (VRCNext)
- https://booth.pm/ja/items/8019367 (VRChat強制終了システム)
- https://booth.pm/ja/items/5822088 / https://github.com/wondernote/EventTTForVRChat / https://booth.pm/ja/items/1977611 / https://booth.pm/ja/items/5150091
- https://github.com/Rosecod337/VRChatAdminToolsPublic / https://github.com/vrclog / https://github.com/Kavex/VRChat-Log-Monitor
- https://help.vrchat.com/hc/en-us/articles/9521522810899-Where-do-I-find-my-Output-Logs-and-Crash-Dumps
- https://help.vrchat.com/hc/en-us/articles/1500002247921-VRChat-keeps-crashing-or-has-issues-launching-properly
- https://www.moguravr.com/vrchat-troubleshooting/ / https://note.com/yama_0825/n/n13acdee6c991 / https://note.com/charuktya/n/n043a1c93d71b / https://tony-lewis.fanbox.cc/posts/8660204
- https://vrnavi.jp/unity-error/ / https://zenn.dev/sarashinanoniki/articles/d5cee765cea0f7 / https://note.com/moegitsubasa/n/nafcfae7fde16 / https://koshishirai.com/en/unity-vrchat-avatar-upload-solution/
- https://note.com/azukimochi25/n/n042c495e55f4 (ConsoleLogSaver) / https://vrnavi.jp/lileditortoolbox/
- https://ask.vrchat.com/t/avatar-validation-failed/25422 / https://ask.vrchat.com/t/error-building-avatar-2022-3-6f1/22003
- https://docs.unity3d.com/ja/2018.4/Manual/LogFiles.html
- https://www.vn3.org/generator / https://lowteq.github.io/vn3-easy-generator/ / https://vr-lifemagazine.com/vn3/ / https://www.moguravr.com/vn3-license/
- https://note.com/asada_kadura/n/n137a5d63db03 / https://www.moguravr.com/vrchat-avatar-update-how-to/
- https://metacul-frontier.com/?p=37249 / https://docs.vrchat.com/docs/vrchat-202633-open-beta
- https://www.inside-games.jp/article/2026/02/06/177087.html
- https://zenn.dev/nekobox/scraps/5e46be61b89fca / https://vrnavi.jp/vrchat-config/ / https://note.com/lucky_str1ke/n/na1dfe345e91b
