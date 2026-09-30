# unitypackage 検品ツール（Booth 出品者向け）  (調査日: 2026-09-30)

対象: `system-tool-candidates-2026-09.md` の候補 2。Booth に 3D 衣装・アバター・ギミックを出品する人が、
書き出した unitypackage（と配布 zip）を Unity を開かずに検品し、同梱漏れ・他者アセット混入・参照切れ・
規約/README の不足を出品前に潰すための PC ツール。

## 結論（3行以内）
- **条件付きでやる。** 「書き出した後の実物（zip / unitypackage）を Unity 無しで検品する」ツールは Booth にも GitHub にも無い。ただし 2026 年 5 月に無料の Yan-K Smart Package（Unity 内で依存追跡＋参照切れ検出付き書き出し）が出ており、「同梱漏れ検出」単体では勝てない。
- 勝ち筋は **他者アセット混入判定（lilToon / Poiyomi / Modular Avatar / VRChat SDK を GUID とパスで検出し、各公式の「同梱しないで」ルールを日本語で案内）＋購入者目線の導入手順 / 同梱物一覧の自動生成＋危険物（.dll / .cs / 実行ファイル）検出**。書き出しツールでは代替できない「出品前の最終検品」に絞る。
- 価格は候補表の ¥1,500〜2,500 では高い。出品者向け Unity ツールの相場は ¥500〜1,000（KeyPoint ¥500、BOOTH Package Manager ¥1,000）。**¥1,000 前後、無料版（閲覧＋基本チェック）＋有料版（混入判定・レポート・複数パッケージ一括）** を推奨。

## 競合一覧
| 名前 | 種別 | 価格 | 強み | 弱み | URL |
|---|---|---|---|---|---|
| Yan-K Avatar Toolbox / Smart Package (YSP) | Unity エディタ拡張（無料・MIT） | 0 | AssetDatabase の依存から書き出しツリーを作る。**missing-reference detection**、拡張子/正規表現で除外、フォルダ整理モード。v1.4.0 (2026/05/21) 追加、最新 v1.8.0 (2026/07/17)。VCC 配布あり | Unity 内・書き出し前の道具。書き出した「実物」は見ない。他者アセット混入の判定・規約/README の有無・zip 全体の検品は無い。英語 UI。Star 11 | https://github.com/Yan-K/AvatarToolbox/ , https://yan-k.booth.pm/items/8191277 |
| UnityPackageの書き出しを補助するやつ (KeyPoint) | Unity エディタ拡張 | 無料版 ¥0 / 有料 ¥500 | 書き出し対象とパッケージ名を記録し、複数パッケージを一括書き出し | 検品機能なし。Unity 2018.4 以降向けで古い | https://booth.pm/ja/items/2548226 |
| BOOTH Package Manager | Unity エディタ拡張 | ¥1,000 | 購入した unitypackage を Unity 内で管理・一括インポート。v1.3.0 (2026/05) でタグ・関連リンク。日英韓中 | 購入者向け。検品なし | https://booth.pm/ja/items/7321369 |
| Unityを開かなくてもUnityPackageの中身が確認できる (prbl99) | PC ツール | 期間限定無料 → ¥300 予定 | Unity 無しで中身一覧。zip のままでも可。**2026 年の新作**（ID 8584952） | 「どこの店の無料配布か探す」用途。検品・判定なし | https://prbl99.booth.pm/items/8584952 |
| 【無料】unitypackage簡単解凍ツール (kennykenny) | PC ツール | 0 | ダブルクリック / D&D で一覧表示し必要なファイルだけ抽出 | 一覧と抽出のみ | https://booth.pm/ja/items/6668211 |
| UnityPackageUnPacker (CHIU SHOP) | PC ツール | — | 指定フォルダへ展開 | 展開のみ | https://booth.pm/ja/items/1037772 |
| 自分の持ってる.unitypackageファイルを管理するやつ | PC ツール | — | 購入品の管理（Booth URL からサムネ取得、対応アバター検索） | 購入者向け管理。検品なし | https://booth.pm/ja/items/7271059 |
| アバターアップロード事前チェックツール | Unity エディタ拡張（無料） | 0 | Missing Script、ポリゴン数、マテリアル数、VRAM、PhysBone、Quest 互換を自動チェック | **アバターのアップロード前**用。パッケージの中身は見ない | https://booth.pm/ja/items/8225246 |
| lilAvatarUtils (lilLab) | Unity エディタ拡張（無料） | 0 | テクスチャ/マテリアル/アニメーション一覧、Missing コンポーネント除去、シェーダー未適用時の見え方確認 | 改変・軽量化用。パッケージ検品ではない | https://booth.pm/ja/items/6532787 |
| Unity Asset Store Tools Validator / Asset Store Validation suite | 公式（Asset Store 出品者向け） | 0 | 22 項目（No Executables、No Symlinks、No Zip、Meta Files、Path Length、Documentation、Changelog…）の自動検証 | Asset Store の投稿規約用。Booth / VRChat の慣習（lilToon 同梱、MA、規約 txt）は対象外。Unity 内 | https://github.com/needle-mirror/com.unity.asset-store-validation/blob/master/Documentation~/index.md |

Booth ページ (booth.pm) は egress ブロックのため、価格・機能は検索結果の要約から。いいね数・販売数は取得できず（未確認）。

## 無料の強豪
- **GitHub の抽出/閲覧ツール**は多数あるがすべて「展開・閲覧」止まり。EasyExtractUnitypackage（Star 124、Win/mac/Linux、Discord webhook / 怪しいリンク / DLL パターンの**マルウェアスキャン**とプレビュー付き。Web 版は有料枠あり）、Cobertos/unitypackage_extractor（Python、Star 683、MIT）、m35/UnityPackageViewer（Java、GUID 検索、AGPL）、ShinuToki（Rust、path traversal 対策）。日本語 UI・出品者向けの判定は無い。
  - https://github.com/HakuSystems/EasyExtractUnitypackage
  - https://github.com/Cobertos/unitypackage_extractor
  - https://github.com/m35/UnityPackageViewer
  - https://github.com/ShinuToki/unitypackage_extractor
- **Yan-K Smart Package**（上表）が最大の無料の強豪。「同梱漏れ」の一次対策は Unity 内で無料化された、と見るべき。
- **VN3 ライセンス**（利用規約テンプレ＋ジェネレータ）が普及済み（2022 年 5 月時点で 3D キャラクター人気上位 50 の 46% が採用）。規約の「生成」は作らず、「規約ファイルが同梱されているか」「README に必須項目があるか」の**検査**に留める。
  - https://www.moguravr.com/vn3-license/ , https://panora.tokyo/archives/49448

## トレンド・公式アップデートの影響
- **配布形式は当面 unitypackage のまま**: 衣装・アバターは Unity にドラッグ＆ドロップで導入する形が主流。VPM 配布はエディタ拡張向けに広がっているが、衣装には向かない（https://kxn4t.hatenablog.com/entry/2025/04/20/174352 は egress ブロック、検索要約）。
- **VRChat 公式アバターマーケットプレイス**（2026/03/18 開始）と **VRChat × pixiv の資本業務提携**（2026/09 発表）。公式マーケットは「買って終わり」型で、着せ替え（衣装）は BOOTH 側が継続する構造と論じられている。衣装出品者の unitypackage 需要は減らない見込み（https://panora.tokyo/archives/157287 , https://www.gamebusiness.jp/article/2026/09/29/28164.html いずれも egress ブロック、検索要約）。
- **VRChat SDK は 2023 年から VCC 配布のみ**で、SDK License は「limited, personal, … non-sublicensable, non-transferable」。SDK を unitypackage に同梱するのは規約違反（https://hello.vrchat.com/legal/sdk は egress ブロック、検索要約）。→ 検出項目として価値あり。
- **各外部アセットの「同梱するな」ルール（一次情報）**:
  - lilToon: MIT。「シェーダー本体と制作物を 1 つの unitypackage にまとめる方法は、古いバージョンで上書きしてしまう問題が起きるため非推奨」。ショートカット同梱か、配布そのままの unitypackage を別添が推奨（https://lilxyzw.github.io/lilToon/ja_JP/first.html は egress ブロック、検索要約。GitHub は MIT・Star 1.6k を確認）。
  - Poiyomi: MIT。README に「do not include the `_PoiyomiShaders` folder in your asset's package」（https://github.com/poiyomi/PoiyomiToonShader 直接確認）。
  - Modular Avatar: 同梱は許可されるが非推奨。「ユーザーが非常に古いバージョンをインストールするか、誤ってダウングレードして他のプレハブを破損する可能性がある」ため公式配布元へ誘導すること。MA 非使用者向けに nested prefab で本体と MA 設定を分ける提案（https://github.com/bdunderscore/modular-avatar/blob/main/docs~/docs/distributing-prefabs/index.md 直接確認）。
- **セキュリティ**: unitypackage は C# スクリプトや DLL を運べ、`InitializeOnLoad` でインポート時に実行される。preview.png の偽装も可能。GitHub 上の Unity 公式パッケージにもマルウェア混入例（GHSA-xq92-f676-63w4）。購入者側の警戒は高まっており、「スクリプト・DLL・実行ファイルを含まない」ことをレポートで示せるのは出品者の安心材料になる（https://blog.fa.nta.sy/posts/2025-08-01-weaponizing-unity-packages/ は egress ブロック、検索要約 / https://github.com/advisories/GHSA-xq92-f676-63w4）。
- **unitypackage の内部形式**（実装可能性）: gzip 圧縮 tar。ルートに GUID 名のディレクトリ、各ディレクトリに `pathname`（Assets/… のパス）、`asset.meta`、`asset`（フォルダの場合は無し）、任意の `preview.png`。アセット間参照は YAML 内の `{fileID: …, guid: <32hex>, type: …}`。→ Python `tarfile` ＋ YAML の GUID 抽出で Unity 無しに「パッケージ外参照」を列挙できる（https://github.com/m35/UnityPackageViewer , https://pkg.go.dev/github.com/r74tech/unitypackage）。`pathname` に絶対パスや `..` が入る攻撃があるため、検査時も sanitize が必要（https://github.com/Cobertos/unitypackage_extractor/issues/14）。

## ユーザー層と需要の根拠
- **市場規模**: BOOTH 3D モデルカテゴリの 2025 年取扱高 約 104 億円（前年比約 179%）、注文 約 774 万件、注文者 28.1 万人（取引白書 2026。https://www.pixiv.co.jp/2026/02/06/110000 , https://inside.pixiv.blog/2026/02/06/110000 は egress ブロック、複数ニュースの検索要約）。**出品者数は白書の二次報道に見当たらず未確認**。
- **出品点数**: BOOTH「3D衣装」56,856 点、うち VRChat タグ 48,803 点、無料 6,735 点（https://booth.pm/ja/browse/3D%E8%A1%A3%E8%A3%85 検索要約）。「Unityエディタ拡張 × VRChat」713 点、「エディタ拡張」587 点で、作者向けツール市場は成立している。
- **出品前チェックが個人の記事頼み**: 「Booth 出品前にチェックしておくこと」（不要データの残留、MA 依存で Missing script が出る）、「販売用 VRC アバターの UnityPackage の内容、作り方」（Include dependencies で lilToon が勝手にチェックされるので外す）、「[ショップ名] フォルダ問題」（インポート先が Assets 直下のショップ名フォルダになり購入者が迷子になる問題提起）など、チェックリストは note に散在し道具化されていない（https://note.com/to_ottotto/n/n4d93b44adaf5 , https://note.com/suzu_3d/n/n83017d1b4cdb , https://note.com/efk/n/n45ff5ccb5e88 いずれも egress ブロック、検索要約）。
- **購入者側の定番トラブル = 出品者のサポート負担**: 「ピンク（シェーダー未導入）」「Missing (Script)（MA 未導入）」「マテリアル別配布で入れ忘れ」は初心者向け記事・知恵袋・ask.vrchat.com に繰り返し出る（https://ask.vrchat.com/t/cant-upload-an-avatar-i-bought-on-booth-missing-script/47270 , https://vrnavi.jp/shader-texture-material/ , https://note.com/yuyuq/n/ncdbefa7ee029）。出品者が「前提ツール」「同梱物」「導入順」を README に正確に書くことで減らせる種類のもので、検品ツールがその文面を自動生成できる。
- **出品者向けツールの価格帯**: ¥100（Folder Preview）〜 ¥500（KeyPoint）〜 ¥1,000（BOOTH Package Manager）。無料版＋有料版の二段構えが多い。
- 販売数の一次データは Booth が egress ブロックのため取得できず（未確認）。

## 差別化の仮説
1. **「書き出した後の実物」を検品する唯一のツール**: zip をそのまま放り込むと、中の unitypackage / README / 規約 / 画像を全部読んで結果を出す。Unity 不要。Yan-K は書き出し前、抽出ツールは閲覧のみ。
2. **他者アセット混入判定**: lilToon / Poiyomi / Modular Avatar / VRChat SDK の GUID・パス辞書（GitHub の `.meta` から生成。lilToon・MA・Poiyomi は `.meta` が公開されていることを確認済み）で「混入」「参照のみ（購入者に別途導入させる）」を区別し、各公式の文言を添えて案内する。
3. **パッケージ外参照の列挙**: YAML の `guid:` を全部集め、パッケージ内 / 既知外部 / 不明 に分類。不明 = 入れ忘れ候補。「Unity で開かないと確定できない」旨は明記する。
4. **購入者目線の成果物を自動生成**: 同梱物一覧、前提ツール一覧（バージョン欄付き）、導入順、対応アバター別パッケージの一覧を README 雛形（日本語）として出力。商品説明に貼れる「同梱していないもの」文も出す。
5. **安全レポート**: `.cs` / `.dll` / `.exe` / `.bat` などの有無、`InitializeOnLoad` の文字列、preview.png と実体の拡張子不一致、`pathname` の異常（絶対パス・`..`）、日本語ファイル名・長すぎるパスを検出。
6. **一括検品**: 対応アバター 10 種 × unitypackage 10 個の商品で、全パッケージが同じテクスチャ/規約を含むか、バージョン表記が揃っているかを比較する（多アバター対応衣装は常態化: 例「【12アバター対応】」「✧14アバター✧」）。
7. **AI 製ビジュアル不要**: UI は表と文字だけ。サムネは UI スクリーンショットと文字組みで足りる。
8. **この環境で全テスト可能**: `tarfile` で作った合成 unitypackage（正常 / 混入 / 参照切れ / 攻撃パス）を fixtures に置き、Unity 無しで全判定をテストできる。実 unitypackage は Booth からの取得不可のため、GitHub 上の lilToon / MA のリリース unitypackage で GUID 辞書と解析を検証する。

## 未確認事項
- Booth 出品者（3D モデルカテゴリ）の人数・新規出品者数（白書本文が読めない）。
- Booth 上の各競合の DL 数・いいね数、prbl99 ツール（8584952）の現在価格。
- VRChat SDK の GUID 一覧の入手方法（SDK は VCC 配布のみ。packages.vrchat.com からの取得可否は未確認。取れなければ `Packages/com.vrchat.*` パスと `VRC` 名前空間のスクリプト名で代替）。
- lilToon 公式ドキュメントの配布ガイド原文（検索要約のみ。仕様書に載せる際は原文再確認）。
- Yan-K Smart Package の missing-reference detection の精度と、書き出し後の unitypackage に対してどこまで補完できるか（実機 Unity が無いので試せない）。
- 「同梱漏れ」がどの程度の頻度で起きているかの定量データ（更新履歴での「入れ忘れ修正」件数は検索で拾えず）。
- Unity の YAML アセットで GUID 参照が現れる場所の網羅（.prefab / .mat / .controller / .anim / .asset / .meta 以外にバイナリ形式のケースがあるか）。

## 出典
- https://github.com/Yan-K/AvatarToolbox/
- https://yan-k.booth.pm/items/8191277
- https://booth.pm/ja/items/2548226
- https://booth.pm/ja/items/7321369
- https://prbl99.booth.pm/items/8584952
- https://booth.pm/ja/items/6668211
- https://booth.pm/ja/items/1037772
- https://booth.pm/ja/items/7271059
- https://booth.pm/ja/items/8225246
- https://booth.pm/ja/items/6532787
- https://booth.pm/ja/items/7526535
- https://github.com/needle-mirror/com.unity.asset-store-validation/blob/master/Documentation~/index.md
- https://github.com/HakuSystems/EasyExtractUnitypackage
- https://github.com/Cobertos/unitypackage_extractor
- https://github.com/Cobertos/unitypackage_extractor/issues/14
- https://github.com/m35/UnityPackageViewer
- https://github.com/ShinuToki/unitypackage_extractor
- https://pkg.go.dev/github.com/r74tech/unitypackage
- https://github.com/lilxyzw/lilToon
- https://lilxyzw.github.io/lilToon/ja_JP/first.html
- https://github.com/poiyomi/PoiyomiToonShader
- https://github.com/bdunderscore/modular-avatar/blob/main/docs~/docs/distributing-prefabs/index.md
- https://modular-avatar.nadena.dev/docs/distributing-prefabs/for-outfit-creators
- https://hello.vrchat.com/legal/sdk
- https://github.com/advisories/GHSA-xq92-f676-63w4
- https://blog.fa.nta.sy/posts/2025-08-01-weaponizing-unity-packages/
- https://www.pixiv.co.jp/2026/02/06/110000
- https://inside.pixiv.blog/2026/02/06/110000
- https://panora.tokyo/archives/157287
- https://www.gamebusiness.jp/article/2026/09/29/28164.html
- https://kxn4t.hatenablog.com/entry/2025/04/20/174352
- https://note.com/to_ottotto/n/n4d93b44adaf5
- https://note.com/suzu_3d/n/n83017d1b4cdb
- https://note.com/efk/n/n45ff5ccb5e88
- https://ask.vrchat.com/t/cant-upload-an-avatar-i-bought-on-booth-missing-script/47270
- https://vrnavi.jp/shader-texture-material/
- https://note.com/yuyuq/n/ncdbefa7ee029
- https://www.moguravr.com/vn3-license/
- https://panora.tokyo/archives/49448
- https://booth.pm/ja/browse/3D%E8%A1%A3%E8%A3%85
- https://booth.pm/ja/search/Unity%E3%82%A8%E3%83%87%E3%82%A3%E3%82%BF%E6%8B%A1%E5%BC%B5?tags%5B%5D=VRChat
