---
name: vrc-build
description: 仕様に基づく実装。spec.md と test-plan.md がある商品の src/tests を書き、全テストを通す。実装中は確認待ちで止まらず、仕様の範囲で自律的に進める。
---

# 実装 (/vrc-build)

目的: `products/<name>/docs/spec.md` を、テストが証明する形で実装する。

## 進め方

1. `spec.md` / `test-plan.md` を読む。無ければ `/vrc-spec` へ戻る。
2. **テストを先に書く。** `shared/vrc_mock` と `shared/fixtures` を使い、test-plan の項目を pytest にする。
3. 実装する。仕様に無いことはしない。迷ったら仕様に書いてある既定値に従う。
4. `python -m pytest` をリポジトリ直下で実行し、全部 green にする。赤のまま止めない。
5. 自分の diff を読み直す（Windows で壊れる箇所: パス区切り、文字コード、`%LOCALAPPDATA%`、コンソールの cp932）。
6. 区切りごとにコミットする。メッセージは「何を・なぜ」。

## 構成（products/<name>/）

```
product.toml
src/<pkg>/__init__.py, __main__.py, cli.py, config.py, ...
tests/test_*.py
docs/concept.md, spec.md, test-plan.md
README.md          （/vrc-release で仕上げる。実装中は開発者向けメモで可）
requirements.txt   （実行時依存のみ。開発依存はリポジトリ直下の requirements-dev.txt）
```

## コーディング規約

- Python 3.11、型ヒントあり、標準ライブラリ優先。GUI は最後、まず CLI で全機能が動くこと。
- 設定は `config.py` に集約し、ファイル（TOML）→ 環境変数 → CLI 引数の順で上書き。
- ログ出力は `logging`。ユーザー向けメッセージは日本語、開発ログは英語。
- 他人の表示名など個人データは、仕様で決めた場所以外に書き出さない。
- 外部プロセス（OBS、OyasumiVR）が無くても起動でき、「未接続」と表示して待てること。
- Windows 前提の処理（パス、起動時の自動検出）は関数に隔離し、Linux でもテストできるよう引数で注入する。

## 「未検証」の扱い

模擬環境で再現できない挙動（実機 VRChat のログの微妙な差、SteamVR 連携）は、
コードにコメントで `# UNVERIFIED: <理由>` を付け、README の「既知の制限」に転記する。
