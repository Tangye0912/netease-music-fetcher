#!/usr/bin/env python3
"""Centralized logging utilities for music-fetch."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_DEFAULT_LOG_PATH = Path.home() / ".config" / "music-fetch" / "logs" / "music-fetch.log"
_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUP_COUNT = 3

_base_logger = logging.getLogger("music_fetch")
if not _base_logger.handlers:
    _base_logger.addHandler(logging.NullHandler())


def default_log_path() -> Path:
    return _DEFAULT_LOG_PATH


def setup_logging(log_path: Path | None = None, level: int = logging.INFO) -> Path:
    target = (log_path or _DEFAULT_LOG_PATH).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("music_fetch")
    root.setLevel(level)
    root.propagate = False

    wanted = str(target.resolve())
    for handler in root.handlers:
        if isinstance(handler, RotatingFileHandler) and handler.baseFilename == wanted:
            return target

    file_handler = RotatingFileHandler(
        wanted,
        maxBytes=_MAX_BYTES,
        backupCount=_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(file_handler)
    return target


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def mask_value(value: str, keep_prefix: int = 4, keep_suffix: int = 4) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if len(value) <= keep_prefix + keep_suffix:
        return "*" * len(value)
    return f"{value[:keep_prefix]}***{value[-keep_suffix:]}"
