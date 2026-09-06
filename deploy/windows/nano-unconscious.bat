@echo off
rem nano の無意識デーモンを常駐させるためのバッチ。
rem タスクスケジューラから呼ばれる想定だが、手で叩いても動く。
rem
rem 使う前に NANO_HOME を自分の環境に書き換えること。

set NANO_HOME=C:\nano
set PYTHON=%NANO_HOME%\.venv\Scripts\python.exe

cd /d "%NANO_HOME%"

rem ログは日ごとに分ける。無意識が何を考えていたかは、ここに残る。
for /f "tokens=1-3 delims=/ " %%a in ("%date%") do set TODAY=%%a%%b%%c
if not exist "%NANO_HOME%\soul\log" mkdir "%NANO_HOME%\soul\log"

"%PYTHON%" -m nano daemon >> "%NANO_HOME%\soul\log\unconscious-%TODAY%.log" 2>&1
