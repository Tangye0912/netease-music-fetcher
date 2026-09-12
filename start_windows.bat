@echo off
setlocal
cd /d "%~dp0"

set "PY_CMD="
if exist "%~dp0.venv\Scripts\python.exe" set PY_CMD="%~dp0.venv\Scripts\python.exe"
if not defined PY_CMD where py >nul 2>nul && py -3 -c "import sys" >nul 2>nul && set "PY_CMD=py -3"

if not defined PY_CMD (
  where python >nul 2>nul && set "PY_CMD=python"
)

if not defined PY_CMD (
  echo.
  echo 未检测到 Python 3，请先安装 Python 3。
  pause
  exit /b 1
)

%PY_CMD% -m music_fetch.app

if errorlevel 1 (
  echo.
  echo 启动失败，请确认已安装 Python 3 和项目依赖。
  pause
)

endlocal
