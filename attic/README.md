# attic

このプロジェクトを始める前から `mynano` リポジトリに置かれていたファイルの置き場。
内容は変えていない。不要なら削除して構わない。

## simple_sketch/

Blender アドオン "Simple Sketch"（作者: Chipp Walters）。
元はリポジトリのルートに `__init__.py` として置かれていた。

**なぜ移動したか**: ルートに `__init__.py` があると、Python と pytest が
リポジトリ全体を1つのパッケージとして扱おうとする。その結果 pytest が
このファイルを import しようとし、Blender 外では存在しない `bpy` が
見つからずにテストが1件も走らなくなっていた。

アドオンとしての体裁（フォルダ＋`__init__.py`）は保ったままなので、
このフォルダごと zip すれば Blender に入れられる。
