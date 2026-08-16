#!/usr/bin/env python3
"""
Pure data models and formatting helpers shared by the batch detect/download
flow, the TUI, and tests.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib import error, request

from music_fetch.app_logging import get_logger
from music_fetch.network import open_url
import music_fetch.ui_texts as T

logger = get_logger("music_fetch.gui")



__all__ = ['BatchDetectRow', 'format_bytes', 'format_duration', 'probe_media_size_bytes']
def format_duration(duration_ms: Optional[int]) -> str:
    if duration_ms is None:
        return T.MSG_UNKNOWN
    seconds = max(int(duration_ms / 1000), 0)
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(max(value, 0))
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{size:.1f}{units[-1]}"  # unreachable, satisfies mypy


def probe_media_size_bytes(media_url: str, timeout: int = 8) -> int:
    """Best-effort remote media size probing for batch preview."""
    if not media_url:
        return 0
    headers = {"User-Agent": "Mozilla/5.0"}
    head_req = request.Request(media_url, headers=headers, method="HEAD")
    try:
        with open_url(head_req, timeout=timeout) as resp:
            content_length = str(getattr(resp, "headers", {}).get("Content-Length") or "").strip()
            if content_length.isdigit():
                return int(content_length)
    except (error.URLError, error.HTTPError, OSError):
        logger.debug("HEAD request failed for size probing. media_url=%s", media_url)

    # Fallback: parse total from Content-Range of a tiny range request.
    range_req = request.Request(
        media_url,
        headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-0"},
        method="GET",
    )
    try:
        with open_url(range_req, timeout=timeout) as resp:
            content_range = str(getattr(resp, "headers", {}).get("Content-Range") or "").strip()
            match = re.search(r"/(\d+)$", content_range)
            if match:
                return int(match.group(1))
    except (error.URLError, error.HTTPError, OSError):
        logger.debug("Range request failed for size probing. media_url=%s", media_url)
    return 0


@dataclass
class BatchDetectRow:
    raw_input: str
    source_type: str = "unknown"
    source_label: str = ""
    song_id: str = ""
    song_name: str = ""
    status: str = "failed"
    message: str = ""
    media_size_bytes: int = 0
    selected: bool = False
    _progress: float = 0.0  # 0.0–1.0, cached for progress bar aggregation
