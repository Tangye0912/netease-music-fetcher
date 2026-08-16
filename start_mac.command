#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON_BIN=""
if command -v python3.13 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3.13)"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "未检测到 python3，请先安装 Python 3。"
  read -r -p "按回车键退出..."
  exit 1
fi

if ! "$PYTHON_BIN" -m music_fetch.app; then
  echo
  echo "启动失败，请检查依赖后重试（例如：$PYTHON_BIN -m pip install -e .）。"
  read -r -p "按回车键退出..."
fi
