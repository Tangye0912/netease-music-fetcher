#!/usr/bin/env python3
"""Small terminal-app entry point; help/version work without a TTY or login."""
from __future__ import annotations

import argparse
import sys

from music_fetch.app_settings import APP_VERSION


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    parser = argparse.ArgumentParser(prog="music-fetch", description="网易云音乐全屏终端应用。无参数启动交互界面。")
    parser.add_argument("--version", action="version", version=f"music-fetch {APP_VERSION}")
    if any(arg not in {"-h", "--help", "--version"} for arg in args):
        parser.print_usage(sys.stderr)
        print("参数式下载已移除，请直接运行 music-fetch，在终端界面中添加下载。", file=sys.stderr)
        return 2
    try:
        parser.parse_args(args)
    except SystemExit as result:
        return int(result.code or 0)
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("需要交互式终端。请在终端中直接运行 music-fetch；帮助请用 --help。", file=sys.stderr)
        return 2
    from music_fetch.tui import main as tui_main
    return tui_main()


if __name__ == "__main__":
    raise SystemExit(main())
