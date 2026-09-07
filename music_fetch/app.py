#!/usr/bin/env python3
"""Application entry point.

Bare `music-fetch` opens the interactive terminal UI.  Script mode (CLI) was
removed in v3.4 — passing arguments prints a short notice and exits.
"""

from __future__ import annotations

import sys
from typing import Optional

__all__ = ["main"]


def main(argv: Optional[list[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args:
        print(
            "脚本模式已在 v3.4 移除：music-fetch 现在只提供交互界面（TUI）。"
            "请直接运行 music-fetch（不带参数）进入主菜单。",
            file=sys.stderr,
        )
        return 2
    from music_fetch.tui import main as tui_main

    return tui_main()


if __name__ == "__main__":
    raise SystemExit(main())
