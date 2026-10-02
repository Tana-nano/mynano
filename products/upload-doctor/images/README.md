# 商品画像

Booth の商品画像（1000×1000 の正方形）を、Windows で撮った本物のスクリーンショットから作る。
AI で生成した絵は使わない。画像に入れる文字は、1 枚目の「商品名」「できること 1 行」「対応環境」だけにする。

1. `screens/` に `ng.png`・`report.png`・`clean.png` を置く（撮り方は `docs/cowork-finish-0.1.2.md` の F4）。
2. `python products/upload-doctor/images/make_images.py` を実行する。
   - `out/01-thumbnail.png`〜`04-clean.png` ができる。
   - 初回はフォント（Noto Sans JP、SIL Open Font License）を `.fonts/` に取得する。`.fonts/` はコミットしない。
3. `out/` の画像を Booth に登録する。1 枚目がサムネイルになる。

正方形 1000 px は、Booth の一覧で画像が 1:1 に切り抜かれて表示されるという解説記事にもとづく。
booth.pm を直接は確認できていない（取得がブロックされるため、検索結果の要約で代用）。
