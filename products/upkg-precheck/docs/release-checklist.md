# 出品チェックリスト（オーナー向け）— 出品前チェッカー 0.1.0

## 1. Booth に登録するファイル

1. GitHub の Actions → build-windows の成功した最新の実行（コミット「Windows 実機確認の結果を反映」）を開き、
   Artifacts の `upkg-precheck-0.1.0-win64` をダウンロードする。
2. ダウンロードした zip は二重になっている。展開して出てくる **`upkg-precheck-0.1.0-win64.zip`（内側の zip）を Booth に登録する**。
   - 中身: `upkg-precheck-0.1.0-win64\` フォルダに `upkg-precheck.exe`、`_internal\`、README.md、EULA.md、CHANGELOG.md、THIRD_PARTY.md
   - `products/upkg-precheck/dist/upkg-precheck-0.1.0.zip`（Python のソース）は登録しない。

## 2. 商品ページ

- タイトル・本文は `booth.md` から貼る（見出しはそのまま Booth の本文で使える）。
- 価格: **0 円**（期間限定無料）。
- **値上げ日を決めて `booth.md` の「価格の理由」に書く**（企画では「例: 2 週間、値上げ日は最初から商品ページに書く」と決めた。今の文面は「一定期間」のまま）。
- 種別: ダウンロード商品。カテゴリは「ソフトウェア」系、タグ例: `VRChat` `unitypackage` `出品者向け` `検品` `Windows`
- サムネ・説明画像:
  - AI 生成画像は使わない。結果のページ（report.html）や黒い画面のスクリーンショット＋文字組みだけで作る。
  - 画像の文字は「出品前チェッカー」「unitypackage を Unity なしで検品」「Windows 専用・PC VR / デスクトップ用（Quest 単機非対応）」の 3 つだけ。
  - スクリーンショットには**自分の商品か lilToon の公式配布物**を使う。購入した他人の商品の名前やファイル名が写らないようにする。
    例: `lilToon_1.7.0.unitypackage` をドロップした画面（実機確認の W03 と同じ）。

## 3. チェック

- [ ] Windows でダウンロードした zip を展開し、exe が起動する（SmartScreen の警告は README の説明で対処できる）
- [ ] README の導入手順どおりに動く（zip をドロップ → 結果 → ドキュメント\UpkgPrecheck に保存）
- [ ] 商品説明に「Windows 専用」と「Quest 単機非対応」がある
- [ ] EULA と商品説明の「再配布はご遠慮ください」「出力は自由に編集・公開できる」が一致している
- [ ] 価格（無料 → 500 円予定）が `docs/market/unitypackage-inspector-2026-09.md` と `concept.md` の根拠と合っている
- [ ] CHANGELOG に日付とバージョンがある（0.1.0 - 2026-10-01）
- [ ] OSCドクター・V睡ログの商品ページに「同じ作者のツール」として出品前チェッカーを追記する（各 `booth.md` に文案あり）

## 4. 公開後

- 誤検知の報告（report.txt）が来たら、このリポジトリのセッションに貼る。辞書やルールを直して版を上げる。
- 正式リリースのタグを付けるなら `v0.1.0-upkg-precheck`（push するとビルドが走る）。
