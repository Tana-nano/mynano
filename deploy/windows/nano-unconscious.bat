@echo off
rem nano の無意識デーモンを常駐させるためのバッチ。
rem タスクスケジューラから呼ばれる想定だが、手で叩いても動く。
rem
rem 使う前に NANO_HOME を自分の環境に書き換えること。

set NANO_HOME=C:\nano
set PYTHON=%NANO_HOME%\.venv\Scripts\python.exe

cd /d "%NANO_HOME%"

rem ログの日次ローテーションはデーモン自身が持っている
rem （soul\log\unconscious.log。既定で30日ぶん）。
rem
rem 以前はここで日付を組み立ててリダイレクトしていたが、常駐プロセスでは
rem 日付が「起動した日」で固定される。数週間動き続けると全部が1つのファイルに入り、
rem 際限なく太っていた。ローテーションは常駐している側が持たないと成立しない。
rem
rem ここに残すのは、デーモンが立ち上がる前に死んだとき用の保険だけ。
rem （import に失敗した、埋め込みモデルが変わっていて起動を止めた、など）
if not exist "%NANO_HOME%\soul\log" mkdir "%NANO_HOME%\soul\log"

"%PYTHON%" -m nano daemon >> "%NANO_HOME%\soul\log\stderr.log" 2>&1
