# unitypackage 検品ツール（Booth 出品者向けの出品前チェック）  (調査日: 2026-10-05)

`system-tool-candidates-2026-09.md` の候補 #2 の深掘り。前回は「競合が見当たらない」としたが、
Unity 内で動く書き出し（エクスポート）補助ツールが ¥0〜500 で複数あることが分かった。

> booth.pm、note.com、knb-mayumi.com、lilxyzw.github.io は直接取得できなかった（egress ブロック）。
> Booth の商品情報と lilToon の配布ガイドは**検索結果の要約で代用**している。価格は要約に出た値。

## 結論（3行以内）
- **条件付きでやる。** 「Unity の中で書き出す」ツールは ¥0〜500 で飽和気味だが、**書き出した後の zip を Unity なしで検品する**ツールは見当たらない。
- 条件: **無料（＋任意のブースト）**で出し、出品者と購入者の両方が使える形にする。有料にしても相場は ¥500 が上限。
- ショップの入口商品をもう 1 つ増やす位置づけ。V睡ログ・OSCドクター（VRChat ユーザー向け）とは別の客層（出品者）に届く。

## 競合一覧
| 名前 | 種別 | 価格 | 強み | 弱み | URL |
|---|---|---|---|---|---|
| SmartBatchExporter | Unity エディタ拡張（出品者） | ¥500（体験版 ¥0） | フォルダ単位で一括書き出し、依存を自動追跡、「外部アセットの混入を防ぎたい人に」と明記 | Unity 内で動く。書き出した後の zip の中身・同梱物は見ない | https://booth.pm/ja/items/7882448 |
| Smart Exporter | Unity エディタ拡張（出品者） | 未確認 | AssetDatabase で依存を自動収集、拡張子・glob で除外（既定 .cs / .shader）、容量警告、依存が欠けたときの警告 | 同上。除外ルールを自分で書く必要がある | https://booth.pm/ja/items/8086173 |
| UnityPackage_Exporter（Re Work Ver.） | Unity エディタ拡張 | ¥0 | 無料 | 旧版はサポート終了 | https://booth.pm/ja/items/3906865 |
| PackageExporter【UnityGeneralTool】 | Unity エディタ拡張 | 未確認 | 書き出し補助 | 詳細は未確認 | https://booth.pm/ja/items/7447905 |
| Unity Package Security Tool | Unity エディタ拡張（購入者） | ¥100 | インポート時、スクリプトや DLL が入っていると警告。スクリプトを先に取り出して確認できる | 購入者向け。インポート画面を開くまで分からない | https://booth.pm/ko/items/8335990 |
| BIG Clean Package Importer | Unity エディタ拡張（購入者） | ¥500 | インポートで意図せず上書きされるのを防ぐ | 購入者向け。Unity が必要 | https://booth.pm/en/items/8316720 |
| KokonoAtelierUnityPackageManager / BoothItemManager / B-Manager / ALManager | 購入品の管理 | ¥0〜500（支援版 ¥700） | 購入した zip の整理・検索・インポート | 検品はしない | https://booth.pm/ja/items/7926537 ほか（検索要約） |
| Packyderm / Unity Assets Manager Pro | Unity なしのビューア（海外） | 未確認 | Unity なしで中身を一覧・取り出し | 見るだけ。出品ルールのチェックはない。日本語なし | https://isometric8.itch.io/packyderm-unitypackage-extractor |

## 無料の強豪
- **unitypackage_extractor**（Python、MIT、GitHub スター 682）: 取り出しだけ。仕組み（tar.gz の中に GUID 名のフォルダ、`asset` / `asset.meta` / `pathname` / `preview.png`）の確認に使える。 https://github.com/Cobertos/unitypackage_extractor
- UnityZip、UnityPackageUtil（C#）、upextract（Rust）: どれも取り出し・一覧まで。検品ルールはない。
- 結論: 「中身を見る」部分は無料でありふれている。**価値は検品ルール（何を危ないと判定するか）と日本語の説明**の側にある。

## トレンド・公式アップデートの影響
- BOOTH の 3D モデルカテゴリは 2025 年に取扱高 104 億円（前年比約 179%）、取扱商品数 774 万件、1 人あたり平均 27.4 注文。出品者・商品数とも増え続けている。 https://www.gamebusiness.jp/article/2026/02/07/26157.html ／ https://realsound.jp/tech/2026/02/post-2303955.html
- 衣装単体は ¥1,500〜3,000、アクセサリーは ¥500〜1,500 に集まっている（二次まとめ）。 https://atsoho.com/blog/3d-model-selling-on-booth
- VCC / VPM（VRChat 公式のパッケージ管理）のコミュニティリポジトリで配る方法もあるが、衣装・小物の主流は今も Booth の zip ＋ unitypackage。VPM へ移る動きは今回の検索では見つからなかった（未確認）。 https://vcc.docs.vrchat.com/vpm/packages
- 購入者側では「パッケージにスクリプト・DLL が入っていないか」を気にする流れがあり、警告ツールが ¥100〜500 で出ている（上表）。出品者側から見ると「スクリプトを入れていない」と示せることが安心材料になる。

## ユーザー層と需要の根拠
- **出品者（衣装・小物・ギミック）**: Unity の書き出しで「依存を含める」にチェックすると、シーンやプレハブが参照するものが全部入る（Unity 公式マニュアル）。シェーダーや他人のアセットが混ざる原因になる。 https://docs.unity3d.com/jp/2020.3/Manual/AssetPackagesCreate.html
- **lilToon の同梱は非推奨**: 作品とシェーダーを 1 つの unitypackage にまとめる方法は「インポート時に古い版で上書きされる」などの問題から非推奨になっており、配布ページへの案内か別ファイルにするよう推奨されている（lilToon の配布ガイド。直接は読めず、検索要約で確認）。 https://github.com/lilxyzw/lilToon
- 出品前のチェック項目をまとめた note 記事がある（FBX のインポート設定、マテリアル、Prefab、不要データが残っていないか）。手作業で確認している人がいる根拠になる。本文は読めていない。 https://note.com/to_ottotto/n/n4d93b44adaf5
- 書き出し補助ツールが ¥500 で複数売られていて、説明に「外部アセットの混入を防ぎたい人」とある → 出品者がこの問題にお金を払う前例がある。
- 販売数・レビュー数は Booth を直接読めないため**未確認**。

## 差別化の仮説
1. **書き出した後の最終成果物を見る**: Booth に上げる zip（または unitypackage）をそのまま入れると、購入者が受け取る中身を Unity なしで検品する。Unity 内の書き出しツールと競合せず、併用できる。
2. **VRChat 出品の定番ミスを名指しで検出**（チェック内容は spec で確定）:
   - 他者アセットの混入: lilToon / Poiyomi / Modular Avatar / VRChat SDK などのフォルダ・既知の GUID（GUID 一覧は未確認、spec で一次情報を取る）
   - スクリプト・DLL の有無（購入者の安心材料として「含まれていません」と表示できる）
   - 参照切れ: テキスト形式のアセット（.prefab / .mat / .anim / .controller）が参照する GUID が、パッケージにも既知の外部アセットにもない
   - `.meta` の欠け、`Assets/` 以外へのパス、Windows のユーザー名などを含むパス、巨大ファイル、同じ GUID の重複
   - zip に README・利用規約（VN3 ライセンスなど）が入っているか、文字化けしやすいファイル名がないか
3. **購入者モードを同じ実装で無料提供**: 「このパッケージを入れると何が上書きされるか・スクリプトは入っているか」を Unity を開く前に確認できる。出品者向けより客層が広く、ショップへの流入口になる。
4. 日本語の結果レポート（HTML / テキスト）を出し、購入者への「既知の注意」として booth.md に貼れる文面も作る。

## 既存候補との比較
| | V睡ログ | OSCドクター | unitypackage 検品 |
|---|---|---|---|
| 客層 | VR 睡眠勢 | OSC を使う VRChat ユーザー | 出品者（＋購入者） |
| VR 機器が要る検証 | 多い（テスター必須） | 一部（デスクトップで大半） | **不要** |
| ここでの検証 | 模擬 OSC＋ログ | 模擬 OSC＋OSCQuery | **ほぼ完全**（tarfile で模擬パッケージを生成してテスト） |
| 競合 | なし | 汎用ツールのみ | Unity 内の書き出しツール ¥0〜500 が多数 |
| 価格 | ¥800 | ¥0 | ¥0（＋ブースト）推奨 |

## 未確認事項
- 競合各品の販売数・レビュー数（Booth を直接読めない）。Smart Exporter / PackageExporter の価格。
- lilToon 配布ガイドの原文（lilxyzw.github.io が読めない）。spec 作成時に GitHub のリポジトリ内のドキュメントから確認する。
- lilToon / Poiyomi / Modular Avatar / VRChat SDK の代表的な GUID とフォルダ構成（spec で各リポジトリから取る）。
- バイナリ形式で保存されたアセットの参照は読めない（Unity の既定はテキスト形式。バイナリの場合は「未検査」と表示する想定）。
- 出品者が「Unity の外で最終チェックしたい」と思っているかの直接の声（X・Discord は今回調べていない）。

## 出典
- https://booth.pm/ja/items/7882448 （SmartBatchExporter、検索要約）
- https://booth.pm/ja/items/8086173 （Smart Exporter、検索要約）
- https://booth.pm/ja/items/3906865 （UnityPackage_Exporter、検索要約）
- https://booth.pm/ja/items/7447905 （PackageExporter、検索要約）
- https://booth.pm/ko/items/8335990 （Unity Package Security Tool ¥100、検索要約）
- https://booth.pm/en/items/8316720 （BIG Clean Package Importer ¥500、検索要約）
- https://booth.pm/en/items/7926537 （B-Manager、検索要約）
- https://isometric8.itch.io/packyderm-unitypackage-extractor
- https://github.com/Cobertos/unitypackage_extractor
- https://github.com/lilxyzw/lilToon （配布ガイドへのリンク。ガイド本文は検索要約）
- https://docs.unity3d.com/jp/2020.3/Manual/AssetPackagesCreate.html
- https://www.gamebusiness.jp/article/2026/02/07/26157.html
- https://realsound.jp/tech/2026/02/post-2303955.html
- https://atsoho.com/blog/3d-model-selling-on-booth
- https://vcc.docs.vrchat.com/vpm/packages
- https://note.com/to_ottotto/n/n4d93b44adaf5 （本文未読、検索要約）
