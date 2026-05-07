#!/usr/bin/env python3
"""
Facade / backward-compatibility layer.

Keeps `import music_fetch` working after the refactoring.  All public names
from the three submodules are re-exported so existing importers (main.py,
download_retry.py, tests) continue to resolve the same symbols.
"""

from __future__ import annotations

from _api import *      # constants, data classes, HTTP helpers, API functions
from _audio import *    # download, format conversion
from _cli import *      # CLI entry point (run_download, build_parser, main)


if __name__ == "__main__":
    raise SystemExit(main())
