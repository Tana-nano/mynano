# アップロードドクター for VRChat（開発メモ）

> 出品用の README は `/vrc-release` で仕上げる。今は開発者向けのメモ。

Unity を開かずに、VRChat 用 Unity プロジェクトのフォルダと `Editor.log` を読み取り専用で点検し、
アバターのアップロードや SDK パネルを妨げている原因の候補を、確からしさの順に日本語で表示する。

- PC（Windows 10 / 11）用。**PC VR / デスクトップ用ツールと同じく、Quest 単機では動きません**（Unity は PC で動かすため）。
- 仕様: `docs/spec.md` ／ テスト計画: `docs/test-plan.md` ／ 判定の規則表: `src/upload_doctor/rules.json`

## 開発

```
python -m pytest products/upload-doctor               # リポジトリ直下で
python -m upload_doctor --self-check                   # src/ で。同梱の規則表で診断が最後まで通るか
python -m upload_doctor <プロジェクト> --editor-log <Editor.log> --no-pause --no-report
```

## 既知の制限（未検証を含む。出品用 README に転記する）

- **実際の Unity の `Editor.log` では一度も確認していません**（未検証）。ログの規則は公開質問の文言から作ったもので、網羅的ではなく、実ログで一致しないことがあります。テストは合成したログで行っています。
- `Editor.log` の先頭にコマンドライン引数（`-projectPath`）が書かれるかは未検証です。書かれていなければ「対象プロジェクト: 不明」と表示され、別のプロジェクトのログかどうかを判定できません。
- `Editor.log` の既定の場所（`%LOCALAPPDATA%\Unity\Editor\Editor.log`）は Unity マニュアルの検索要約によります（未検証）。
- Unity を起動したまま `Editor.log` を読めるかは未検証です。読めなければ「Unity を終了してから再実行」と案内します。
- `ProjectVersion.txt` の `m_EditorVersion` 行、`vpm-manifest.json` の `dependencies` / `locked`、パッケージの `vpmDependencies` の形は、実物ではなく資料の要約で確認したものです（未検証）。
- VPM の依存バージョンの書き方は `>=X`、`X.Y.x`、完全一致だけを判定し、それ以外は判定しません。
- 推奨 Unity 版と SDK の条件は変わります。規則表の日付から 90 日を過ぎると「古い可能性があります」と表示します。
- 確からしさ「低」の候補は解説記事などにもとづく推測で、外れることがあります。
- シーン・プレハブ・アニメーターの中身（Avatar Descriptor、ボーン、ポリゴン数、パラメータ容量）は見ません。
- VRChat アカウント側の問題（信頼ランク、ログインしているアカウントの種類）は診断できません。
- ドラッグ＆ドロップでの起動、日本語を含むパス、PyInstaller で作った exe での規則表の読み込みは、Windows 実機では未検証です（CI で `--self-check` による起動確認のみ予定）。
