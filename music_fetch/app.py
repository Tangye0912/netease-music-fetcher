#!/usr/bin/env python3
"""Application entry point.

Bare `music-fetch` opens the interactive terminal UI; passing arguments
runs the script-mode CLI (music_fetch.cli) unchanged.
"""

from __future__ import annotations

import sys
from typing import Optional

__all__ = ["main"]


def main(argv: Optional[list[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    if args:
        from music_fetch.cli import main as cli_main

        return cli_main(args)
    from music_fetch.tui import main as tui_main

    return tui_main()


if __name__ == "__main__":
    raise SystemExit(main())
