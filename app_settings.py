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
DEFAULT_UI_FONT_SIZE = 14
MIN_UI_FONT_SIZE = 12
MAX_UI_FONT_SIZE = 20
DEFAULT_DETECT_TIMEOUT_SEC = 20
MIN_DETECT_TIMEOUT_SEC = 5
MAX_DETECT_TIMEOUT_SEC = 60
DEFAULT_DOWNLOAD_TIMEOUT_SEC = 30
MIN_DOWNLOAD_TIMEOUT_SEC = 10
MAX_DOWNLOAD_TIMEOUT_SEC = 120
DEFAULT_DOWNLOAD_RETRY_COUNT = 1
MIN_DOWNLOAD_RETRY_COUNT = 0
MAX_DOWNLOAD_RETRY_COUNT = 5
DEFAULT_DOWNLOAD_CONCURRENCY = 1
MIN_DOWNLOAD_CONCURRENCY = 1
MAX_DOWNLOAD_CONCURRENCY = 3

URL_EXAMPLE_LONG = "https://music.163.com/song?id=33894312"
NETEASE_LOGIN_URL = "https://music.163.com/#/login"
UNKNOWN_SONG_NAME = "未知歌曲"
