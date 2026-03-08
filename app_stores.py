#!/usr/bin/env python3
"""Persistence stores for session and download records."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from app_logging import get_logger
from app_settings import DEFAULT_DOWNLOAD_DIR, UNKNOWN_SONG_NAME

logger = get_logger("music_fetch.stores")


@dataclass
class AppSession:
    cookie: str
    remember_login: bool
    last_download_dir: str


@dataclass
class DownloadRecord:
    song_id: str
    song_name: str
    output_path: str
    size_bytes: int
    downloaded_at: str


class SessionStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> AppSession:
        if not self.path.exists():
            logger.info("Session file not found. path=%s", self.path)
            return AppSession(cookie="", remember_login=True, last_download_dir=DEFAULT_DOWNLOAD_DIR)
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to parse session file, fallback to empty. path=%s", self.path)
            return AppSession(cookie="", remember_login=True, last_download_dir=DEFAULT_DOWNLOAD_DIR)

        return AppSession(
            cookie=str(raw.get("cookie") or ""),
            remember_login=bool(raw.get("remember_login", True)),
            last_download_dir=str(raw.get("last_download_dir") or DEFAULT_DOWNLOAD_DIR),
        )

    def save(self, session: AppSession) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # When "remember_login" is off, we intentionally avoid persisting cookie to disk.
        payload = {
            "cookie": session.cookie if session.remember_login else "",
            "remember_login": session.remember_login,
            "last_download_dir": session.last_download_dir,
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Session saved. path=%s remember_login=%s", self.path, session.remember_login)


class DownloadHistoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> list[DownloadRecord]:
        if not self.path.exists():
            return []
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            logger.warning("Failed to parse download history, fallback to empty. path=%s", self.path)
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
                    size_bytes=int(row.get("size_bytes") or 0),
                    downloaded_at=str(row.get("downloaded_at") or ""),
                )
            )
        return records

    def save(self, records: list[DownloadRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [
            {
                "song_id": r.song_id,
                "song_name": r.song_name,
                "output_path": r.output_path,
                "size_bytes": r.size_bytes,
                "downloaded_at": r.downloaded_at,
            }
            for r in records
        ]
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, record: DownloadRecord) -> None:
        records = self.load()
        # Keep the latest successful download at the top and dedupe by output path.
        filtered = [row for row in records if row.output_path != record.output_path]
        filtered.insert(0, record)
        self.save(filtered)
        logger.info("Download history appended. song_id=%s path=%s", record.song_id, record.output_path)

    def remove_by_path(self, output_path: str) -> None:
        records = self.load()
        new_records = [row for row in records if row.output_path != output_path]
        if len(new_records) != len(records):
            self.save(new_records)
            logger.info("Download history removed. path=%s", output_path)
