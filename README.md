# mynano

VRChat 向けソフトウェア商品（Booth 販売）の制作リポジトリ。
運用ルールは `CLAUDE.md`、フェーズ別の手順は `.claude/skills/vrc-*`。

## セットアップ

```
pip install -r requirements-dev.txt
python -m pytest
```

## フロー

`/vrc-research` → `/vrc-concept` → `/vrc-spec` → `/vrc-build` → `/vrc-release`

Windows 実行ファイルは GitHub Actions（`build-windows.yml`）が作る。
タグ `v<version>-<product>` を push するか、Actions から手動実行して Artifacts を取得する。
