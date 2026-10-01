# 出品前チェッカー（unitypackage 検品）— 開発メモ

利用者向けの説明は `README.md`。

- 対応環境: Windows 10 / 11 用（PC 用のツール。Unity・VRChat は不要。Quest 単機では動きません）
- 仕様: `docs/spec.md`、テスト計画: `docs/test-plan.md`
- 実行: `PYTHONPATH=src python -m upkg_precheck <zip か unitypackage か フォルダ>`
- テスト: リポジトリ直下で `python -m pytest products/upkg-precheck`
- 辞書の作り直し: `tools/README.md`

## モジュール

| ファイル | 役割 |
|---|---|
| `unitypackage.py` | unitypackage をストリームで 1 回読み、エントリと異常（P01〜P03・P14）を集める |
| `refs.py` | YAML・.meta・asmdef から参照を抜き出す |
| `known.py` | 既知アセット辞書（GUID とパス接頭辞） |
| `classify.py` | 参照先の分類（内部・別パッケージ・組み込み・既知・DLL・見つからない） |
| `archive.py` | 引数の展開、zip の読み取り（Shift_JIS の名前、入れ子、読み取り量の上限） |
| `checks.py` | 検品項目の判定（入出力なしの純粋関数） |
| `report.py` / `draft.py` | 画面表示・report.txt・readme-draft.md |
| `cli.py` | コマンドライン |

## 既知の制限（未検証）

- 本物の書き出しで確かめたのは lilToon 1.7.0 の unitypackage 1 個だけ。`./` 付きの書き出し、`.icon.png` 付きの書き出しは未検証。
- 日本語版 Windows の zip ツールで作った zip（Shift_JIS の名前）は、テスト内で作った zip でしか確かめていない。Windows 11 25H2 のエクスプローラーの zip は UTF-8 の名前だった（2026-10-01）。
- VRChat SDK の判別はアバター向け DLL 6 個の GUID とパス接頭辞だけ。ワールド向け SDK の部品は「辞書に無い DLL の部品」になる。
- Poiyomi の「ロック」で作られたシェーダーの置き場所は `_PoiyomiShaders/` の下と想定（P22）。実際のフォルダ名は未確認。
- X02・X03 の状況を Unity で実際にインポートしたときの動作は未検証。
- 実際の Booth 商品で試したのは 3 個（明らかな誤検知なし）。誤検知の率は未検証。
- Windows 実機確認（2026-10-01、Windows 11 25H2）の結果は `spec.md` の「Windows 実機確認の記録」。本物のドラッグ＆ドロップ、Enter で閉じる動作、OneDrive のドキュメントフォルダは未確認。
