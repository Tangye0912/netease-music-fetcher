#!/usr/bin/env python3
"""Persistence stores for session and download records."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from music_fetch.app_logging import get_logger
from music_fetch.app_settings import (
    DEFAULT_UI_THEME,
    DEFAULT_DETECT_TIMEOUT_SEC,
    DEFAULT_DOWNLOAD_CONCURRENCY,
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_DOWNLOAD_RETRY_COUNT,
    DEFAULT_DOWNLOAD_TIMEOUT_SEC,
    DEFAULT_EXISTING_FILE_POLICY,
    EXISTING_FILE_POLICIES,
    MAX_DETECT_TIMEOUT_SEC,
    MAX_DOWNLOAD_HISTORY_RECORDS,
    MAX_DOWNLOAD_RETRY_COUNT,
    MAX_DOWNLOAD_TIMEOUT_SEC,
    MAX_SAVED_BATCHES,
    MAX_UI_CONCURRENCY,
    MIN_DETECT_TIMEOUT_SEC,
    MIN_DOWNLOAD_CONCURRENCY,
    MIN_DOWNLOAD_RETRY_COUNT,
    MIN_DOWNLOAD_TIMEOUT_SEC,
    UNKNOWN_SONG_NAME,
    clamp,
)
from music_fetch.download_tasks import TASK_STATE_FAILED, TASK_STATE_SUCCESS, is_valid_task_state

logger = get_logger("music_fetch.stores")


def _write_private_json(path: Path, payload: object) -> None:
    """Atomically replace a credential-bearing JSON file with private permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            if os.name != "nt":
                os.chmod(temp_path, 0o600)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
        if os.name != "nt":
            os.chmod(path, 0o600)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _quarantine_file(path: Path) -> None:
    """Move an unreadable store aside instead of silently discarding it.

    Callers treat a broken file as empty and then rewrite it, so the original
    bytes are preserved for manual recovery.
    """
    backup = path.with_name(path.name + ".corrupt")
    try:
        path.replace(backup)
        logger.warning("Store file unreadable; moved aside. src=%s backup=%s", path, backup)
    except OSError as err:
        logger.warning("Store file unreadable and could not be moved aside. path=%s reason=%s", path, err)


@dataclass
class AppSession:
    cookie: str = ""
    remember_login: bool = True
    last_download_dir: str = DEFAULT_DOWNLOAD_DIR
    # v0.4.0: configurable detect/download parameters persisted in session store.
    detect_timeout_sec: int = DEFAULT_DETECT_TIMEOUT_SEC
    download_timeout_sec: int = DEFAULT_DOWNLOAD_TIMEOUT_SEC
    download_retry_count: int = DEFAULT_DOWNLOAD_RETRY_COUNT
    download_concurrency: int = DEFAULT_DOWNLOAD_CONCURRENCY
    existing_file_policy: str = DEFAULT_EXISTING_FILE_POLICY
    ui_theme: str = DEFAULT_UI_THEME
    proxy_type: str = ""  # "http", "socks5", or "" for direct
    proxy_host: str = ""
    proxy_port: int = 0
    proxy_username: str = ""
    proxy_password: str = ""


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
        if not isinstance(raw, dict):
            # Valid JSON of the wrong shape (e.g. a hand-edited "[]") used to
            # raise AttributeError from TuiApp.__init__, i.e. at startup.
            logger.warning("Session file is not a JSON object, fallback to empty. path=%s", self.path)
            return AppSession()

        return AppSession(
            cookie=str(raw.get("cookie") or ""),
            remember_login=bool(raw.get("remember_login", True)),
            last_download_dir=str(raw.get("last_download_dir") or "").strip() or DEFAULT_DOWNLOAD_DIR,
            detect_timeout_sec=self._safe_detect_timeout(raw.get("detect_timeout_sec")),
            download_timeout_sec=self._safe_download_timeout(raw.get("download_timeout_sec")),
            download_retry_count=self._safe_download_retry_count(raw.get("download_retry_count")),
            download_concurrency=self._safe_download_concurrency(raw.get("download_concurrency")),
            existing_file_policy=self._safe_existing_file_policy(raw.get("existing_file_policy")),
            ui_theme=self._safe_ui_theme(raw.get("ui_theme")),
            proxy_type=self._safe_proxy_type(raw.get("proxy_type")),
            proxy_host=str(raw.get("proxy_host") or "").strip(),
            proxy_port=self._safe_proxy_port(raw.get("proxy_port")),
            proxy_username=str(raw.get("proxy_username") or "").strip(),
            proxy_password=str(raw.get("proxy_password") or ""),
        )

    def save(self, session: AppSession) -> None:
        # When "remember_login" is off, we intentionally avoid persisting cookie to disk.
        payload = {
            "cookie": session.cookie if session.remember_login else "",
            "remember_login": session.remember_login,
            "last_download_dir": str(session.last_download_dir or "").strip() or DEFAULT_DOWNLOAD_DIR,
            "detect_timeout_sec": self._safe_detect_timeout(session.detect_timeout_sec),
            "download_timeout_sec": self._safe_download_timeout(session.download_timeout_sec),
            "download_retry_count": self._safe_download_retry_count(session.download_retry_count),
            "download_concurrency": self._safe_download_concurrency(session.download_concurrency),
            "existing_file_policy": self._safe_existing_file_policy(session.existing_file_policy),
            "ui_theme": self._safe_ui_theme(session.ui_theme),
            "proxy_type": self._safe_proxy_type(session.proxy_type),
            "proxy_host": str(session.proxy_host or "").strip(),
            "proxy_port": self._safe_proxy_port(session.proxy_port),
            "proxy_username": str(session.proxy_username or "").strip(),
            "proxy_password": session.proxy_password,
        }
        _write_private_json(self.path, payload)
        logger.info("Session saved. path=%s remember_login=%s", self.path, session.remember_login)

    @staticmethod
    def _safe_existing_file_policy(value: object) -> str:
        normalized = str(value or "").strip().lower()
        if normalized in EXISTING_FILE_POLICIES:
            return normalized
        return DEFAULT_EXISTING_FILE_POLICY

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
        # The settings screen offers up to MAX_UI_CONCURRENCY and the queue
        # honours it; clamping to the smaller legacy ceiling here made a saved
        # value of 4-8 silently revert to 3 on the next start.
        return clamp(value, DEFAULT_DOWNLOAD_CONCURRENCY, MIN_DOWNLOAD_CONCURRENCY, MAX_UI_CONCURRENCY)

    @staticmethod
    def _safe_int(value: object) -> int:
        try:
            return int(value)
        except (TypeError, ValueError, OverflowError):
            # json.loads accepts 1e999, and int(inf) raises OverflowError.
            return 0

    @staticmethod
    def _safe_proxy_type(value: object) -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized in {"http", "socks5"} else ""

    @classmethod
    def _safe_proxy_port(cls, value: object) -> int:
        port = cls._safe_int(value)
        return port if 1 <= port <= 65535 else 0


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
                # Keep the original bytes: the next save() rewrites the file and
                # would otherwise destroy the whole history silently.
                _quarantine_file(self.path)
                # Don't cache the failure — allow next load() to retry reading.
                return []
            if not isinstance(rows, list):
                logger.warning("Download history is not a list, moving it aside. path=%s", self.path)
                _quarantine_file(self.path)
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
            # Keep only the most recent records to avoid unbounded memory growth.
            if len(records) > MAX_DOWNLOAD_HISTORY_RECORDS:
                records = records[:MAX_DOWNLOAD_HISTORY_RECORDS]
            self._cache = records
            return records

    def save(self, records: list[DownloadRecord]) -> None:
        with self._lock:
            limited_records = list(records[:MAX_DOWNLOAD_HISTORY_RECORDS])
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
                for r in limited_records
            ]
            # Atomic write (temp file + fsync + replace), like the session and
            # queue stores: a crash mid-write used to leave a torn JSON file that
            # the next load discarded, losing the entire history.
            _write_private_json(self.path, payload)
            self._cache = limited_records

    def add(self, record: DownloadRecord) -> None:
        with self._lock:
            # Re-read from disk first: a second running instance may have
            # appended since this one cached the file, and rewriting from the
            # stale cache silently dropped its rows.
            self._cache = None
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
        except (TypeError, ValueError, OverflowError):
            # json.loads accepts 1e999, and int(inf) raises OverflowError.
            return 0

    @staticmethod
    def _safe_status(value: object) -> str:
        normalized = str(value or "").strip().lower()
        if not normalized:
            # Legacy records predate the status field; they were all successes.
            return TASK_STATE_SUCCESS
        if is_valid_task_state(normalized):
            return normalized
        # An unrecognised status (hand-edited file, or written by a newer
        # version) must never be presented as a successful download.
        return TASK_STATE_FAILED


class QueueStore:
    """Persisted pending-download list (atomic private JSON).

    Entries are opaque dicts shaped by download_queue._request_to_dict;
    this store only handles durable load/save.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[dict[str, object]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            self._quarantine()
            return []
        if not isinstance(data, list):
            self._quarantine()
            return []
        return data

    def _quarantine(self) -> None:
        """Move an unreadable queue file aside instead of silently discarding it."""
        _quarantine_file(self.path)

    def save(self, entries: list[dict[str, object]]) -> None:
        _write_private_json(self.path, entries)


@dataclass
class SavedBatch:
    """A detection batch kept on disk so its result stays exportable later.

    Rows stay plain dicts here: the store owns persistence, while the TUI owns the
    ``BatchDetectRow`` type it rebuilds them into.
    """

    created_at: str
    rows: list[dict[str, object]]
    task_ids: dict[str, str]


class BatchStore:
    """The most recent detection batches (newest last)."""

    def __init__(self, path: Path, max_batches: int = MAX_SAVED_BATCHES) -> None:
        self.path = path
        self.max_batches = max(1, int(max_batches))
        self._lock = threading.RLock()

    def load(self) -> list[SavedBatch]:
        """Read the saved batches, dropping anything that is not a usable entry."""
        with self._lock:
            if not self.path.exists():
                return []
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError):
                logger.warning("Failed to parse saved batches, moving them aside. path=%s", self.path)
                _quarantine_file(self.path)
                return []
            if not isinstance(data, list):
                logger.warning("Saved batches are not a list, moving them aside. path=%s", self.path)
                _quarantine_file(self.path)
                return []
            batches: list[SavedBatch] = []
            for entry in data:
                batch = self._parse_entry(entry)
                if batch is not None:
                    batches.append(batch)
            return batches[-self.max_batches:]

    @staticmethod
    def _parse_entry(entry: object) -> Optional[SavedBatch]:
        if not isinstance(entry, dict):
            return None
        rows = entry.get("rows")
        task_ids = entry.get("task_ids")
        if not isinstance(rows, list) or not isinstance(task_ids, dict):
            return None
        clean_rows = [row for row in rows if isinstance(row, dict)]
        if not clean_rows:
            return None
        clean_ids = {
            str(index): str(task_id)
            for index, task_id in task_ids.items()
            if task_id not in (None, "")
        }
        return SavedBatch(
            created_at=str(entry.get("created_at") or ""),
            rows=clean_rows,
            task_ids=clean_ids,
        )

    def save(self, batches: Sequence[SavedBatch]) -> None:
        """Persist the newest *max_batches* batches (caller handles OSError)."""
        with self._lock:
            kept = list(batches)[-self.max_batches:]
            payload = [
                {"created_at": batch.created_at, "rows": batch.rows, "task_ids": batch.task_ids}
                for batch in kept
            ]
            _write_private_json(self.path, payload)
