# 開発用ツール（配布物には入れません）

## build_known_assets.py — 既知アセット辞書の作成

`src/upkg_precheck/data/known_assets.json` を作り直します。各配布元の git リポジトリを浅く取得し、
指定したタグの `.meta` から GUID とパスだけを集めます（他者のコードやシェーダーは保存しません）。

```
python tools/build_known_assets.py --work <作業フォルダ> --date YYYY-MM-DD
```

- 取得するタグ: lilToon・Modular Avatar・NDMF は各 `x.y.0` と最新、Poiyomi は 8.x・9.x・10.x の各最終版と最新、VRCFury は main の最新。
- Unity が無視するフォルダ（名前が `~` で終わる・`.` で始まる）は除きます。Modular Avatar・NDMF の古いタグにある
  開発用プロジェクトの `Assets/`（テスト用のアセット、配布されていない）も除きます。
- 異なる配布元で GUID が重複したらエラーで止まります。
- VRChat SDK は取得できないため、アバター向け DLL 6 個の GUID をスクリプト内に固定値で持っています。

### 実行記録

| 日付 | 件数 |
|---|---|
| 2026-09-30 | lilToon 439（14 タグ）、Poiyomi 1,571（3 タグ）、Modular Avatar 465（29 タグ）、NDMF 301（20 タグ）、VRCFury 749（main 8c9f0b9）、VRChat SDK 6。合計 3,531 |

## 本物の書き出しでの確認

```
UPKG_REAL_FIXTURE_DIR=<フォルダ> python -m pytest products/upkg-precheck/tests/test_real_fixture.py
```

フォルダに `lilToon_1.7.0.unitypackage`（https://github.com/lilxyzw/lilToon/releases/download/1.7.0/lilToon_1.7.0.unitypackage 、MIT）を置きます。リポジトリには入れません。

| 日付 | 結果 |
|---|---|
| 2026-09-30 | 合格。エントリ 370（フォルダ 18）、全ファイルが辞書の GUID に一致、出た項目は P07・P19・P21（緑）だけ |
