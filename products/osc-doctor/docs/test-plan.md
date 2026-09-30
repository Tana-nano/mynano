# OSCドクター テスト計画  v0.1

`python -m pytest` をリポジトリ直下で実行して全部通ること。実機（VRChat・Windows）は使わない。

## 設計上のテスト容易性

- 事実の収集（`probe`）と判定（`checks.judge`）を分ける。判定は `Facts` データクラスを入れて `Finding` の列を返す純関数。
- プロセス・ポート情報は `SystemInfo` プロトコル経由（本番 = psutil、テスト = 固定値）。
- VRChat の OSCQuery 探索は `Browser` プロトコル経由（本番 = zeroconf、テスト = 固定値 or 実 zeroconf）。
- 時計と sleep は注入可能にし、計測時間をテストで短縮する。

## フィクスチャ

| もの | 内容 | 由来 |
|---|---|---|
| テスト内生成の VRChat フォルダ | `OSC\usr_…\Avatars\*.json` を tmp に作る | コード内 |
| `shared/vrc_mock` 追加: `FakeVRChatQuery` | `VRChat-Client-XXXXXX` 名で `_oscjson._tcp` を広告し、`/?HOST_INFO`（NAME, OSC_IP, OSC_PORT, OSC_TRANSPORT）と `/`（`CONTENTS.avatar`）を返す HTTP サーバ。広告なしの HTTP だけモードも持つ | vrc-oscquery-lib `HostInfo.cs` の項目名 |
| `shared/vrc_mock` 既存: `FakeVRChat` | パラメータ・head pose の送信、`retarget(port)` | 既存 |

## ユニット

| 対象 | ケース |
|---|---|
| 起動引数の解析 | `--osc=9000:127.0.0.1:9001`／`--osc=9100:127.0.0.1:9101`／引数なし／壊れた値（無視）／他の引数と混在 |
| 判定 `judge` | 判定表の各行を 1 ケース以上。特に: VRChat 無し → RX/OQ/TRACKING を出さない／IN_PORT_FREE／RX_NONE_OQ／RX_ONLY_FIXED／TRACKING_MISSING は VRMode=0 で出ず TRACKING_DESKTOP／VRMode 不明なら TRACKING_MISSING／CACHE の `--fix-cache` 併記条件／OSC_PORT と in-port の不一致で情報 |
| 要約行 | NG・注意の件数、全部 OK のとき |
| 受信集計 | アドレス別件数・型タグ・経路・件数/秒、トラッキング成分の min/max、`/avatar/change` の値を保持しない、VRMode の最後の値 |
| 伏せ字 | `usr_` / `avtr_` / `wrld_` / `C:\Users\名前\`（大文字小文字、スラッシュ、日本語名） |
| レポート | UTF-8 BOM、各節の存在、伏せ字適用後に元の ID・ユーザー名が含まれない、末尾の案内 1 行 |
| キャッシュ集計 | フォルダなし／ユーザー 2 つ・JSON 複数／最新日時 |
| キャッシュ退避 | 移動先に中身がそろう・元が消える／確認で `n` なら何もしない／`--yes`／フォルダなし／移動失敗（読み取り専用などを模擬して例外）で元が残る |
| CLI | 引数検証（範囲外の秒数で終了コード 2）／`--version`／ダブルクリック判定（引数なしのときだけ Enter 待ち）／終了コード 0/1/2 |
| psutil 実装 | 自分で UDP をバインドしたポートの持ち主が自プロセス名で返る（Linux で実 psutil）／存在しないポートは None |

## 結合（`shared/vrc_mock` 使用）

| シナリオ | 検証 |
|---|---|
| 固定ポート受信 | FakeVRChat を固定ポートへ向けてパラメータと head pose を送る → RX_OK（経路=固定）、TRACKING_OK、件数/秒 |
| OSCQuery 受信 | 本ツールの広告 HTTP を OscQueryProbe で検査（`/avatar`・`/tracking/vrsystem`・OSC_PORT）→ FakeVRChat を OSC_PORT へ retarget して送る → 経路=OSCQuery |
| 固定ポート使用中 | 先にテストがバインド → 受信は OSCQuery だけで続行、OUT_PORT_OTHER |
| VRChat の OSCQuery 探索（HTTP） | FakeVRChatQuery の HTTP を直接指定して HOST_INFO を読む → OQ_FOUND、受信ポート |
| VRChat の OSCQuery 探索（mDNS） | FakeVRChatQuery を実 zeroconf で広告 → 実 Browser で発見。**この環境で mDNS が使えなければ skip**（skip 理由を表示） |
| 無受信 | 何も送らない → RX_NONE / RX_NONE_OQ（Facts の組み合わせで） |
| 送信テスト | `--send-test` で FakeVRChat（受信側）に `/chatbox/input` が 1 件届く |
| 通し | cli の main を `--no-pause --seconds 1 --browse-seconds 1 --out tmp` で実行（SystemInfo・Browser は偽物）→ 終了コード、画面出力、レポートファイル |
| Ctrl+C | 計測中に KeyboardInterrupt → その時点の結果で判定・保存 |

## Windows（CI）

- `build-windows.yml`: `--version` と `smoke.args`（`--no-pause --no-report --seconds 1 --browse-seconds 1`）で exe が最後まで走り、終了コードが 0 または 1。

## 手動確認（購入者・オーナーに頼る項目。README の「既知の制限」と一致させる）

- 実 VRChat が `VRChat-Client-*` で見つかる
- 実 VRChat が本ツールに OSCQuery で送ってくる
- Windows で UDP ポートの持ち主の名前が出る
- トラッキングの件数/秒と値の範囲（レポートから収集）
