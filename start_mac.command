#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "未检测到 python3，请先安装 Python 3。"
  read -r -p "按回车键退出..."
  exit 1
fi

if ! python3 main.py; then
  echo
  echo "启动失败，请检查依赖后重试（例如：python3 -m pip install PySide6）。"
  read -r -p "按回车键退出..."
fi
