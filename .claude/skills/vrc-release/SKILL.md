---
name: vrc-release
description: Booth 出品準備。README・利用規約・商品説明文・zip 生成・Windows ビルド確認・出品前チェックを行う。実装が全テスト green になった後に使う。
---

# 出品 (/vrc-release)

目的: 購入者が README だけで導入でき、権利・対応環境で事故が起きない配布物を作る。

## 手順

1. `product.toml` の `version` を上げ、`CHANGELOG.md` に変更点を書く。
2. `README.md` を `templates/README_booth.md` の構成で仕上げる（日本語・丁寧語）。
3. `EULA.md` を `templates/EULA_software.md` からコピーし、商品名・作者名・日付を埋める。
4. `booth.md` に商品ページ用の文章を書く（下の構成）。
5. `python scripts/release_check.py <name>` を通す。
6. `python scripts/package.py <name>` で `dist/<name>-<version>.zip` を作る（Linux 上では Python ソース配布のみ）。
7. Windows exe は GitHub Actions（`build-windows.yml`）で生成する。タグ `v<version>-<name>` を push すると
   Artifacts に zip が上がる。オーナーはそれをダウンロードして Booth に登録する。
8. オーナーに「出品チェックリスト」を渡す（下記）。

## booth.md の構成

```
# タイトル（40字以内。何ができるかを名詞で）
## キャッチ（1行）
## できること（箇条書き 3〜6）
## 対応環境（PC VR / デスクトップ。Quest 単機非対応と明記）
## 前提ソフト（バージョン付き）
## 導入手順（3〜5ステップ）
## 既知の制限
## 価格の理由（任意）
## 更新方針
## 利用規約の要約 / 問い合わせ先
```

## サムネ・画像

- AI 生成画像は使わない。UI のスクリーンショット＋文字組みで作る。
- 画像の文字は「商品名」「できること 1 行」「対応環境」の 3 つだけ。
- スクリーンショットに他人の表示名・ID が写らないよう、フィクスチャ名で撮る。

## 出品チェックリスト（オーナー向け）

- [ ] Windows でダウンロードした zip を展開し、exe が起動する（Defender の警告が出たら README の説明で対処できる）
- [ ] README の導入手順どおりに動く
- [ ] 商品説明に「Quest 単機非対応」がある
- [ ] EULA と商品説明の再配布禁止・改変可否が一致している
- [ ] 価格が `docs/market/` の根拠と合っている
- [ ] 更新履歴に日付とバージョンがある
