# Windows 実機確認 2 回目（コワーク用の依頼文）

1 回目（`cowork-check.md`、結果は `spec.md` の「Windows 実機確認の記録」）で残った項目と、1 回目の結果を受けて直したところを確かめる。
下の「依頼文」をそのままコワークに貼る。結果ファイルをこのリポジトリの作業セッションに貼り戻すと、修正に反映する。

1 回目からの変更:
- テスト用のフォルダ・ファイルの名前は**英数字だけ**にした（1 回目の日本語の名前は Unity で文字化けした。日本語を含むパスでのツールの動作は 1 回目で確認済み）。
- 本物のドラッグ＆ドロップと Enter での終了は、操作できなければ「未実施」でよいことにした。
- exe をダブルクリックするとブラウザで開く「検品の画面」を足した（R07）。結果の見た目も作り直した。

準備（オーナー）:
1. https://github.com/Tana-nano/mynano/actions/runs/36994235214 の Artifacts から `upkg-precheck-0.1.0-win64` をダウンロードする
   （1 回目と同じ名前なので、ブラウザが `upkg-precheck-0.1.0-win64 (1).zip` のように名前を変えることがある）。
2. ダウンロードした zip を `ダウンロード` フォルダに置いたまま、コワークに依頼文を貼る。

---

## 依頼文

Windows 用のツール「出品前チェッカー（upkg-precheck.exe）」の動作確認、2 回目をお願いします。Booth に出す unitypackage や zip を検品するコマンドラインのツールです。
**ファイルの削除・アップロード・外部への送信はしないでください。** 調べたファイルの中身や、購入した商品のファイルを外部に送ることもしないでください。
**作るフォルダとファイルの名前は、すべて英数字にしてください**（日本語の名前は Unity で文字化けするため）。
unitypackage をダブルクリックすると Unity が開くので、ダブルクリックはしないでください。

### 準備

1. `C:\Users\<ユーザー名>\Downloads\upkg-test\` フォルダを作ってください。
2. `Downloads` にある、いちばん新しい `upkg-precheck-0.1.0-win64*.zip` を `upkg-test\tool\` に展開してください。
   zip が二重・三重になっていたら、`upkg-precheck.exe` が入ったフォルダまで展開して、そのフォルダを使ってください。
3. `upkg-test\material\` フォルダを作り、`lilToon_1.7.0.unitypackage` を置いてください。1 回目の `Downloads\検品テスト\素材\` にあればそれをコピーし、無ければ次からダウンロードしてください（lilToon の公式配布物、MIT ライセンス）。
   https://github.com/lilxyzw/lilToon/releases/download/1.7.0/lilToon_1.7.0.unitypackage
4. `upkg-test\material\TestProduct\` フォルダを作り、中に `lilToon_1.7.0.unitypackage` のコピーと `readme.txt`（中身は何でも可）を置いてください。
5. エクスプローラーで `TestProduct` フォルダから `TestProduct.zip` を作り、`upkg-test\material\` に置いてください（「ZIP ファイルに圧縮する」）。

できあがりの形:
```
upkg-test\
  tool\…\upkg-precheck.exe
  material\
    lilToon_1.7.0.unitypackage
    TestProduct.zip
    TestProduct\
      lilToon_1.7.0.unitypackage
      readme.txt
```

### 確認すること

ドラッグ＆ドロップやキー入力ができない場合は、1 回目と同じく、同じ引数で exe を起動する .bat（`start "" upkg-precheck.exe <ファイル>`）で代わりに行い、そのことを記録してください。
画面の内容は、毎回テキストでそのまま記録してください。

| # | 操作 | 期待する結果 |
|---|---|---|
| R01 | `upkg-precheck.exe --version` | `出品前チェッカー 0.1.0（辞書 2026-09-30）` と表示される |
| R02 | `material\lilToon_1.7.0.unitypackage` を、エクスプローラーで exe のアイコンに**本物のドラッグ＆ドロップ**で重ねる。表示後に **Enter キー**を押す | 結果が表示され、Enter で窓が閉じる。どちらかが操作できなければ「未実施」とし、理由を書く |
| R02b | R02 のとき | ブラウザで「検品結果」のページが自動で開く（アドレスが `http://127.0.0.1:` で始まる）。黒い画面の `[緑]` などに色が付いている（Windows ターミナルか、従来の黒いコンソールかも記録）。ページの見やすさの感想。Enter で黒い画面を閉じたあと、ページの「ファイルを選ぶ」で何か選ぶと「黒い窓が閉じられたため、調べられません」と出る |
| R03 | `material` フォルダごと exe に渡す | 調べたものが `lilToon_1.7.0.unitypackage`、`TestProduct.zip`、`TestProduct\lilToon_1.7.0.unitypackage` と表示される。結果の行では zip の中のものが `TestProduct.zip/TestProduct/lilToon_1.7.0.unitypackage` と表示される。`(2)` が付いた名前が**出ない** |
| R04 | `TestProduct.zip` と `material\lilToon_1.7.0.unitypackage` を同時に exe に渡す | 両方を調べる。「全パッケージに共通のアセット」（X04）の行が**出ない**（中身が lilToon だけのため） |
| R05 | （Unity Hub がある場合）Unity Hub で新しいプロジェクトを作る。名前 `UpkgTest`、保存先 `upkg-test\unity\`、テンプレートは 3D（Built-in）。`Assets\Test\` フォルダを作り、その中にマテリアル `TestMat` と、Cube に `TestMat` を付けたプレハブ `TestCube` を作る。`Assets\Test` を右クリック →「Export Package…」→ 全部チェックのまま「Export…」で `upkg-test\material\test-export.unitypackage` に保存。その unitypackage を exe に渡す | 出た項目のコードと 1 行目をすべて記録。赤が 0 であること。黄が出たら全文を記録 |
| R07 | `upkg-precheck.exe` を**ダブルクリック**する。開いたブラウザの画面に、`material\TestProduct.zip` を**ドラッグ＆ドロップ**する（できなければ「ファイルを選ぶ」ボタンから選ぶ）。結果が出たら `material` フォルダを画面にドロップする（できなければ「フォルダを選ぶ」から `material` を選ぶ。ブラウザが「アップロードしますか」と聞いたら、アドレスが `http://127.0.0.1:` で始まる画面であることを確かめてから「アップロード」を押してよい。これはパソコンの中のツールに渡すだけで、外部への送信には当たらない）。最後に結果の画面の「フォルダを開く」を押す | ブラウザで「出品前の検品」の画面が開く（どのブラウザか記録）。ドロップ後、数秒で結果の画面に変わり、`TestProduct.zip` の結果が出る。フォルダでは R03 と同じ名前が並ぶ。「フォルダを開く」で `ドキュメント\UpkgPrecheck\…` がエクスプローラーで開く。ドロップとボタンのどちらで行ったかを記録。黒い画面の表示もテキストで記録 |
| R06 | （任意）1 回目と別の Booth 商品 zip（自分の商品、または購入した商品）が PC にあれば、2〜3 個を exe に渡す | 出た項目のコードと 1 行目を記録。明らかな誤検知に印を付ける。ファイル名・商品名は記録してよいが、中身や画像は外部に送らない |

### 結果のまとめ方

`Downloads\upkg-test\result.md` に、次の形でまとめてください。

```
# 出品前チェッカー Windows 確認結果（2 回目）
- 日付:
- Windows の版:

| # | 結果（OK / NG / 未実施） | 画面の内容・気づいたこと |
|---|---|---|
| R01 | | |
...

## 画面の記録
（R03・R05・R06・R07 の画面のテキストをそのまま。R02b・R07 のブラウザの画面はスクリーンショットがあれば添える）
```

最後に、`result.md` の中身を全文そのまま表示してください（作業セッションに貼り戻すため）。
