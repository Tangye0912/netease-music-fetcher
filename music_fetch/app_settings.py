#!/usr/bin/env python3
"""Global app settings and shared constants."""

from __future__ import annotations

import re
from pathlib import Path

APP_NAME = "music-fetch"
APP_VERSION = "1.0.7"
PROJECT_GITHUB_URL = "https://github.com/Tangye0912/netease-music-fetcher"
PROJECT_RELEASE_API = "https://api.github.com/repos/Tangye0912/netease-music-fetcher/releases/latest"
PROJECT_TAGS_API = "https://api.github.com/repos/Tangye0912/netease-music-fetcher/tags?per_page=1"
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
DEFAULT_UI_THEME = "light"
UI_THEME_OPTIONS = ("light", "dark")
DETECT_TIMEOUT_OPTIONS = (1, 3, 5)
DOWNLOAD_TIMEOUT_OPTIONS = (3, 5, 10)
DEFAULT_DETECT_TIMEOUT_SEC = 5
MIN_DETECT_TIMEOUT_SEC = 1
MAX_DETECT_TIMEOUT_SEC = 5
DEFAULT_DOWNLOAD_TIMEOUT_SEC = 10
MIN_DOWNLOAD_TIMEOUT_SEC = 3
MAX_DOWNLOAD_TIMEOUT_SEC = 10
DEFAULT_DOWNLOAD_RETRY_COUNT = 1
MIN_DOWNLOAD_RETRY_COUNT = 0
MAX_DOWNLOAD_RETRY_COUNT = 5
DEFAULT_DOWNLOAD_CONCURRENCY = 1
MIN_DOWNLOAD_CONCURRENCY = 1
MAX_DOWNLOAD_CONCURRENCY = 3

NETEASE_LOGIN_URL = "https://music.163.com/#/login"
UNKNOWN_SONG_NAME = "未知歌曲"

# Shared text pattern constants
URL_IN_TEXT_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
TRAILING_URL_PUNCTUATION = ")]}>,.;!?\"'，。；：、）】》"
SHORT_LINK_HOSTS: set[str] = {"163cn.tv", "www.163cn.tv"}


def clamp(value: object, default: int, min_val: int, max_val: int) -> int:
    """Safely parse value as int and clamp to [min_val, max_val]."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_val, min(max_val, parsed))


def clamp_download_settings(
    detect_timeout_sec: object,
    download_timeout_sec: object,
    download_retry_count: object,
    download_concurrency: object,
) -> tuple[int, int, int, int]:
    """Clamp all four download settings to their valid ranges at once."""
    return (
        clamp(detect_timeout_sec, DEFAULT_DETECT_TIMEOUT_SEC, MIN_DETECT_TIMEOUT_SEC, MAX_DETECT_TIMEOUT_SEC),
        clamp(download_timeout_sec, DEFAULT_DOWNLOAD_TIMEOUT_SEC, MIN_DOWNLOAD_TIMEOUT_SEC, MAX_DOWNLOAD_TIMEOUT_SEC),
        clamp(download_retry_count, DEFAULT_DOWNLOAD_RETRY_COUNT, MIN_DOWNLOAD_RETRY_COUNT, MAX_DOWNLOAD_RETRY_COUNT),
        clamp(download_concurrency, DEFAULT_DOWNLOAD_CONCURRENCY, MIN_DOWNLOAD_CONCURRENCY, MAX_DOWNLOAD_CONCURRENCY),
    )
