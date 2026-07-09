#!/usr/bin/env python3
"""Build script for PyInstaller packaging.

Usage:
    python build.py          # Build standalone executable
    python build.py --clean   # Clean build artifacts and rebuild
"""

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
BUILD_DIR = ROOT / "build"
DIST_DIR = ROOT / "dist"
SPEC_FILE = ROOT / "music-fetch.spec"


def clean() -> None:
    for d in (BUILD_DIR, DIST_DIR):
        if d.exists():
            shutil.rmtree(d)
            print(f"Cleaned: {d}")
    pycache = ROOT / "__pycache__"
    if pycache.exists():
        shutil.rmtree(pycache)
    for d in ROOT.rglob("__pycache__"):
        if d.exists():
            shutil.rmtree(d)


def build() -> int:
    if not SPEC_FILE.exists():
        print("ERROR: music-fetch.spec not found")
        return 1

    print("Building with PyInstaller...")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        str(SPEC_FILE),
        "--noconfirm",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
    ]
    result = subprocess.run(cmd, cwd=str(ROOT))
    if result.returncode != 0:
        print("Build failed!")
        return result.returncode

    exe_name = "music-fetch.exe" if sys.platform == "win32" else "music-fetch"
    exe_path = DIST_DIR / exe_name
    if exe_path.exists():
        print(f"\nBuild successful!")
        print(f"Executable: {exe_path}")
    else:
        print(f"\nBuild failed: executable not found at {exe_path}")
        return 1
    return 0


def main() -> int:
    if "--clean" in sys.argv:
        clean()
    return build()


if __name__ == "__main__":
    raise SystemExit(main())