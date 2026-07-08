#!/usr/bin/env python3
"""Persistence stores for session and download records."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

from music_fetch.app_logging import get_logger
from music_fetch.app_settings import (
    DEFAULT_UI_THEME,
    DEFAULT_DETECT_TIMEOUT_SEC,
    DEFAULT_DOWNLOAD_CONCURRENCY,
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_DOWNLOAD_RETRY_COUNT,
    DEFAULT_DOWNLOAD_TIMEOUT_SEC,
    DEFAULT_UI_FONT_SIZE,
    MAX_DETECT_TIMEOUT_SEC,
    MAX_DOWNLOAD_CONCURRENCY,
    MAX_DOWNLOAD_RETRY_COUNT,
    MAX_DOWNLOAD_TIMEOUT_SEC,
    MAX_UI_FONT_SIZE,
    MIN_DETECT_TIMEOUT_SEC,
    MIN_DOWNLOAD_CONCURRENCY,
    MIN_DOWNLOAD_RETRY_COUNT,
    MIN_DOWNLOAD_TIMEOUT_SEC,
    MIN_UI_FONT_SIZE,
    UNKNOWN_SONG_NAME,
    clamp,
)
from music_fetch.download_tasks import TASK_STATE_SUCCESS, is_valid_task_state

logger = get_logger("music_fetch.stores")


@dataclass
class AppSession:
    cookie: str = ""
    remember_login: bool = True
    last_download_dir: str = DEFAULT_DOWNLOAD_DIR
    ui_font_size: int = DEFAULT_UI_FONT_SIZE
    # v0.4.0: configurable detect/download parameters persisted in session store.
    detect_timeout_sec: int = DEFAULT_DETECT_TIMEOUT_SEC
    download_timeout_sec: int = DEFAULT_DOWNLOAD_TIMEOUT_SEC
    download_retry_count: int = DEFAULT_DOWNLOAD_RETRY_COUNT
    download_concurrency: int = DEFAULT_DOWNLOAD_CONCURRENCY
    ui_theme: str = DEFAULT_UI_THEME
    window_geometry: str = ""  # "x,y,w,h" serialized


@dataclass
class DownloadRecord:
    song_id: str
    song_name: str
    output_path: str
    size_bytes: int
    downloaded_at: str
    status: str = TASK_STATE_SUCCESS
    error_code: str = ""


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AppSession:
        if not self.path.exists():
            logger.info("Session file not found. path=%s", self.path)
            return AppSession()
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            logger.warning("Failed to parse session file, fallback to empty. path=%s", self.path)
            return AppSession()

        return AppSession(
            cookie=str(raw.get("cookie") or ""),
            remember_login=bool(raw.get("remember_login", True)),
            last_download_dir=str(raw.get("last_download_dir") or DEFAULT_DOWNLOAD_DIR),
            ui_font_size=self._safe_ui_font_size(raw.get("ui_font_size")),
            detect_timeout_sec=self._safe_detect_timeout(raw.get("detect_timeout_sec")),
            download_timeout_sec=self._safe_download_timeout(raw.get("download_timeout_sec")),
            download_retry_count=self._safe_download_retry_count(raw.get("download_retry_count")),
            download_concurrency=self._safe_download_concurrency(raw.get("download_concurrency")),
            ui_theme=self._safe_ui_theme(raw.get("ui_theme")),
            window_geometry=str(raw.get("window_geometry") or ""),
        )

    def save(self, session: AppSession) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # When "remember_login" is off, we intentionally avoid persisting cookie to disk.
        payload = {
            "cookie": session.cookie if session.remember_login else "",
            "remember_login": session.remember_login,
            "last_download_dir": session.last_download_dir,
            "ui_font_size": self._safe_ui_font_size(session.ui_font_size),
            "detect_timeout_sec": self._safe_detect_timeout(session.detect_timeout_sec),
            "download_timeout_sec": self._safe_download_timeout(session.download_timeout_sec),
            "download_retry_count": self._safe_download_retry_count(session.download_retry_count),
            "download_concurrency": self._safe_download_concurrency(session.download_concurrency),
            "ui_theme": self._safe_ui_theme(session.ui_theme),
            "window_geometry": session.window_geometry,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Session saved. path=%s remember_login=%s", self.path, session.remember_login)

    @staticmethod
    def _safe_ui_font_size(value: object) -> int:
        return clamp(value, DEFAULT_UI_FONT_SIZE, MIN_UI_FONT_SIZE, MAX_UI_FONT_SIZE)

    @staticmethod
    def _safe_detect_timeout(value: object) -> int:
        return clamp(value, DEFAULT_DETECT_TIMEOUT_SEC, MIN_DETECT_TIMEOUT_SEC, MAX_DETECT_TIMEOUT_SEC)

    @staticmethod
    def _safe_download_timeout(value: object) -> int:
        return clamp(value, DEFAULT_DOWNLOAD_TIMEOUT_SEC, MIN_DOWNLOAD_TIMEOUT_SEC, MAX_DOWNLOAD_TIMEOUT_SEC)

    @staticmethod
    def _safe_download_retry_count(value: object) -> int:
        return clamp(value, DEFAULT_DOWNLOAD_RETRY_COUNT, MIN_DOWNLOAD_RETRY_COUNT, MAX_DOWNLOAD_RETRY_COUNT)

    @staticmethod
    def _safe_ui_theme(value: object) -> str:
        from music_fetch.app_settings import UI_THEME_OPTIONS
        normalized = str(value or "").strip().lower()
        if normalized in UI_THEME_OPTIONS:
            return normalized
        return DEFAULT_UI_THEME

    @staticmethod
    def _safe_download_concurrency(value: object) -> int:
        return clamp(value, DEFAULT_DOWNLOAD_CONCURRENCY, MIN_DOWNLOAD_CONCURRENCY, MAX_DOWNLOAD_CONCURRENCY)


class DownloadHistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._cache: Optional[list[DownloadRecord]] = None
        self._lock = threading.RLock()

    def load(self) -> list[DownloadRecord]:
        with self._lock:
            if self._cache is not None:
                return list(self._cache)
            if not self.path.exists():
                self._cache = []
                return []
            try:
                rows = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                logger.warning("Failed to parse download history, fallback to empty. path=%s", self.path)
                self._cache = []
                return []

            records: list[DownloadRecord] = []
            for row in rows if isinstance(rows, list) else []:
                if not isinstance(row, dict):
                    continue
                records.append(
                    DownloadRecord(
                        song_id=str(row.get("song_id") or ""),
                        song_name=str(row.get("song_name") or UNKNOWN_SONG_NAME),
                        output_path=str(row.get("output_path") or ""),
                        size_bytes=self._safe_int(row.get("size_bytes")),
                        downloaded_at=str(row.get("downloaded_at") or ""),
                        status=self._safe_status(row.get("status")),
                        error_code=str(row.get("error_code") or ""),
                    )
                )
            self._cache = records
            return records

    def save(self, records: list[DownloadRecord]) -> None:
        with self._lock:
            self._cache = list(records)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = [
                {
                    "song_id": r.song_id,
                    "song_name": r.song_name,
                    "output_path": r.output_path,
                    "size_bytes": r.size_bytes,
                    "downloaded_at": r.downloaded_at,
                    "status": self._safe_status(r.status),
                    "error_code": r.error_code,
                }
                for r in records
            ]
            self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, record: DownloadRecord) -> None:
        with self._lock:
            records = self.load()
            # v0.4.0: keep the latest task result at the top and dedupe by output path.
            filtered = [row for row in records if row.output_path != record.output_path]
            record.status = self._safe_status(record.status)
            filtered.insert(0, record)
            self.save(filtered)
        logger.info(
            "Download history appended. song_id=%s path=%s status=%s",
            record.song_id,
            record.output_path,
            record.status,
        )

    def remove_by_path(self, output_path: str) -> None:
        with self._lock:
            records = self.load()
            new_records = [row for row in records if row.output_path != output_path]
            if len(new_records) != len(records):
                self.save(new_records)
                logger.info("Download history removed. path=%s", output_path)

    @staticmethod
    def _safe_int(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _safe_status(value: object) -> str:
        normalized = str(value or "").strip().lower()
        if is_valid_task_state(normalized):
            return normalized
        return TASK_STATE_SUCCESS
