# products

商品ごとに 1 ディレクトリ。`/vrc-concept` で作成する。

```
products/<name>/
  product.toml     templates/product.toml をコピー
  docs/concept.md  企画（/vrc-concept）
  docs/spec.md     仕様（/vrc-spec）
  docs/test-plan.md
  src/<package>/   実装（/vrc-build）
  tests/
  README.md, EULA.md, CHANGELOG.md, booth.md   出品物（/vrc-release）
  requirements.txt 実行時依存
```
