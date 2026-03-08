#!/usr/bin/env python3
"""Global app settings and shared constants."""

from __future__ import annotations

from pathlib import Path

APP_NAME = "music-fetch"
# Keep all generated runtime files under a single user-scoped config directory.
CONFIG_DIR = Path.home() / ".config" / APP_NAME
SESSION_FILE = CONFIG_DIR / "session.json"
DOWNLOAD_HISTORY_FILE = CONFIG_DIR / "downloads.json"
DEFAULT_DOWNLOAD_DIR = str(Path.home() / "Downloads")

DEFAULT_GUI_TARGET_FORMAT = "mp3"
SUPPORTED_AUDIO_FORMATS = ("mp3", "m4a", "wav", "flac", "aac")

URL_EXAMPLE_LONG = "https://music.163.com/song?id=33894312"
NETEASE_LOGIN_URL = "https://music.163.com/#/login"
UNKNOWN_SONG_NAME = "未知歌曲"
