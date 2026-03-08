@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
  py -3 main.py
) else (
  python main.py
)

if errorlevel 1 (
  echo.
  echo 启动失败，请确认已安装 Python 3 和 PySide6。
  pause
)

endlocal
