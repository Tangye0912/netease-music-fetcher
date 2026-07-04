#!/usr/bin/env python3
"""
QThread worker classes extracted from the original main.py.

Contains BatchInspectWorker (batch song detection), InspectWorker (single
song detection), and DownloadWorker (single-song download with retry logic).
Also re-exports format_bytes, format_duration, and probe_media_size_bytes
which are shared by both workers and dialogs.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from music_fetch.batch_models import (
    BatchDetectRow,
    format_bytes,
    format_duration,
    probe_media_size_bytes,
)
from music_fetch.pipeline import run_download_pipeline
from music_fetch.app_logging import get_logger
from music_fetch.app_settings import (
    clamp_download_settings,
    DEFAULT_DOWNLOAD_RETRY_COUNT,
    DEFAULT_DOWNLOAD_TIMEOUT_SEC,
    DEFAULT_GUI_TARGET_FORMAT,
    MAX_DOWNLOAD_RETRY_COUNT,
    MAX_DOWNLOAD_TIMEOUT_SEC,
    MIN_DOWNLOAD_RETRY_COUNT,
    MIN_DOWNLOAD_TIMEOUT_SEC,
    clamp,
)
from music_fetch.batch_inputs import collect_batch_candidates, source_hint_map
from music_fetch.error_texts import UNKNOWN_ERROR, user_error_message
from music_fetch.api import DownloadCanceled, DownloadPaused, MusicFetchError, SUPPORTED_GUI_AUDIO_FORMATS, detect_song, fetch_playlist_song_ids, parse_input_resource
from music_fetch.audio import convert_audio_file, download_song_with_fallback, infer_audio_format_from_url, is_ffmpeg_available
import music_fetch.ui_texts as T

try:
    from PySide6.QtCore import QThread, Signal
except ImportError as err:
    raise SystemExit(
        "Missing dependency: PySide6. Install it with `python3 -m pip install PySide6` before running main.py."
    ) from err

logger = get_logger("music_fetch.gui")

# Re-exported from music_fetch.batch_models.py for backward compatibility.
# New code should import directly from music_fetch.batch_models.
__all__ = [
    "BatchDetectRow",
    "BatchInspectWorker",
    "DownloadWorker",
    "InspectWorker",
    "format_bytes",
    "format_duration",
    "probe_media_size_bytes",
]


class BatchInspectWorker(QThread):
    progress = Signal(int, int, str)
    completed = Signal(object)
    failed = Signal(str, str)

    def __init__(self, raw_input_text: str, cookie: str, timeout: int, detect_concurrency: int = 5) -> None:
        super().__init__()
        self.raw_input_text = raw_input_text
        self.cookie = cookie
        self.timeout = timeout
        self.detect_concurrency = max(1, min(10, int(detect_concurrency)))

    def run(self) -> None:
        try:
            rows = self._detect_rows()
            self.completed.emit(rows)
        except MusicFetchError as err:
            self.failed.emit(err.code, err.message)
        except Exception as err:  # pragma: no cover
            logger.exception("BatchInspectWorker unexpected error.")
            self.failed.emit(UNKNOWN_ERROR, str(err))

    def _detect_rows(self) -> list[BatchDetectRow]:
        # v0.5.0: parse mixed pasted text into normalized batch candidates.
        candidates = collect_batch_candidates(self.raw_input_text)
        hint_map = source_hint_map(self.raw_input_text)
        if not candidates:
            return []
        logger.info(
            "Batch detect started. deduped_count=%s",
            len(candidates),
        )
        rows: list[BatchDetectRow] = []
        expanded: list[tuple[str, str, str, str]] = []
        for value in candidates:
            source_hint = hint_map.get(value, "")
            try:
                resource_type, resource_id = parse_input_resource(value)
                if resource_type == "playlist":
                    playlist_label = source_hint or f"{T.BATCH_SOURCE_PLAYLIST}-{resource_id}"
                    song_ids = fetch_playlist_song_ids(resource_id, self.cookie, timeout=self.timeout)
                    for song_id in song_ids:
                        expanded.append(("playlist", value, song_id, playlist_label))
                else:
                    expanded.append(("song", value, resource_id, source_hint))
            except MusicFetchError as err:
                rows.append(
                    BatchDetectRow(
                        raw_input=value,
                        source_type="unknown",
                        source_label=source_hint,
                        status="failed",
                        message=f"{err.code}: {user_error_message(err.code, err.message)}",
                    )
                )

        seen_song_ids: set[str] = set()
        total = len(expanded)
        if not expanded:
            return rows

        # Build a deduplicated list while preserving order
        unique_expanded: list[tuple[str, str, str, str]] = []
        for source_type, source_value, song_id, source_label in expanded:
            if song_id in seen_song_ids:
                rows.append(
                    BatchDetectRow(
                        raw_input=source_value,
                        source_type=source_type,
                        source_label=source_label,
                        song_id=song_id,
                        status="duplicate",
                        message=T.MSG_BATCH_DUPLICATE_SONG.format(song_id=song_id),
                    )
                )
                continue
            seen_song_ids.add(song_id)
            unique_expanded.append((source_type, source_value, song_id, source_label))

        # Parallel detect: submit all unique songs to a thread pool
        completed_count = 0
        total_unique = len(unique_expanded)
        results_by_index: dict[int, BatchDetectRow] = {}

        def _detect_one(index: int, source_type: str, source_value: str, song_id: str, source_label: str) -> tuple[int, BatchDetectRow]:
            try:
                result = detect_song(song_id, self.cookie, timeout=self.timeout)
                size_bytes = 0
                if result.can_download and result.media_url:
                    size_bytes = probe_media_size_bytes(result.media_url, timeout=min(10, self.timeout))
                final_source_label = source_label
                if source_type == "song" and not final_source_label:
                    if result.song_name:
                        final_source_label = f"{T.BATCH_SOURCE_SONG}-{result.song_name}"
                    else:
                        final_source_label = f"{T.BATCH_SOURCE_SONG}-{result.song_id}"
                return (index, BatchDetectRow(
                    raw_input=source_value,
                    source_type=source_type,
                    source_label=final_source_label,
                    song_id=result.song_id,
                    song_name=result.song_name or "",
                    status="ready" if result.can_download else "unavailable",
                    message=result.unavailable_reason or "",
                    media_size_bytes=size_bytes,
                    selected=bool(result.can_download),
                ))
            except MusicFetchError as err:
                return (index, BatchDetectRow(
                    raw_input=source_value,
                    source_type=source_type,
                    source_label=source_label,
                    song_id=song_id,
                    status="failed",
                    message=f"{err.code}: {user_error_message(err.code, err.message)}",
                    selected=False,
                ))

        with ThreadPoolExecutor(max_workers=self.detect_concurrency) as executor:
            future_to_index = {}
            for idx, (source_type, source_value, song_id, source_label) in enumerate(unique_expanded):
                future = executor.submit(_detect_one, idx, source_type, source_value, song_id, source_label)
                future_to_index[future] = idx

            for future in as_completed(future_to_index):
                idx, row = future.result()
                results_by_index[idx] = row
                completed_count += 1
                self.progress.emit(completed_count, total_unique, unique_expanded[idx][2])

        # Reconstruct results in original order, then append duplicates after
        for idx in range(total_unique):
            if idx in results_by_index:
                rows.append(results_by_index[idx])
        logger.info(
            "Batch detect completed. total=%s ready=%s duplicate=%s failed_or_unavailable=%s",
            len(rows),
            len([row for row in rows if row.status == "ready"]),
            len([row for row in rows if row.status == "duplicate"]),
            len([row for row in rows if row.status in {"failed", "unavailable"}]),
        )
        return rows


class InspectWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, song_url: str, cookie: str, timeout: int = 20) -> None:
        super().__init__()
        self.song_url = song_url
        self.cookie = cookie
        self.timeout = timeout

    def run(self) -> None:
        try:
            logger.info("InspectWorker started.")
            result = detect_song(self.song_url, self.cookie, timeout=self.timeout)
            self.succeeded.emit(result)
            logger.info("InspectWorker succeeded. song_id=%s can_download=%s", result.song_id, result.can_download)
        except MusicFetchError as err:
            logger.warning("InspectWorker failed. code=%s message=%s", err.code, err.message)
            self.failed.emit(err.code, err.message)
        except Exception as err:  # pragma: no cover
            logger.exception("InspectWorker unexpected error.")
            self.failed.emit(UNKNOWN_ERROR, str(err))


class DownloadWorker(QThread):
    progress = Signal(int, int, float)
    succeeded = Signal(str, int)
    failed = Signal(str, str)
    canceled = Signal()
    paused = Signal()

    def __init__(
        self,
        task_id: str,
        song_id: str,
        output_path: Path,
        cookie: str,
        target_format: str = DEFAULT_GUI_TARGET_FORMAT,
        timeout: int = 30,
        retry_count: int = DEFAULT_DOWNLOAD_RETRY_COUNT,
        tags: Optional[dict[str, Optional[str]]] = None,
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.song_id = song_id
        self.output_path = output_path
        self.cookie = cookie
        self.target_format = target_format.lower().strip()
        # v0.4.0: keep timeout bounded so retry/download behavior is predictable.
        _, self.timeout, self.retry_count, _ = clamp_download_settings(
            0, timeout, retry_count, 0,
        )
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._tags = tags

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def request_pause(self) -> None:
        self._pause_event.set()

    def request_resume(self) -> None:
        self._pause_event.clear()

    def _cleanup_paths(self, *paths: Path) -> None:
        for path in paths:
            if path.exists():
                path.unlink(missing_ok=True)

    def _finish_if_canceled(self, *paths: Path) -> bool:
        if not self._cancel_event.is_set():
            return False
        self._cleanup_paths(*paths)
        logger.info("DownloadWorker canceled by user. task_id=%s output=%s", self.task_id, self.output_path)
        self.canceled.emit()
        return True

    def run(self) -> None:
        started_at = time.time()
        logger.info(
            "DownloadWorker started. task_id=%s output=%s timeout=%ss retry_count=%s",
            self.task_id, self.output_path, self.timeout, self.retry_count,
        )

        def on_progress(downloaded: int, total: Optional[int]) -> None:
            elapsed = max(time.time() - started_at, 0.001)
            speed = downloaded / elapsed
            self.progress.emit(downloaded, total if total is not None else -1, speed)

        def should_cancel() -> bool:
            return self._cancel_event.is_set()

        def should_pause() -> bool:
            return self._pause_event.is_set()

        try:
            result = run_download_pipeline(
                song_id=self.song_id,
                cookie=self.cookie,
                output_path=self.output_path,
                target_format=self.target_format,
                timeout=self.timeout,
                retry_count=self.retry_count,
                progress_callback=on_progress,
                cancel_checker=should_cancel,
                pause_checker=should_pause,
                tags=self._tags,
            )
            self.succeeded.emit(str(result.output_path.resolve()), result.file_size)
            logger.info(
                "DownloadWorker succeeded. task_id=%s output=%s size=%s",
                self.task_id, result.output_path, result.file_size,
            )
        except DownloadCanceled:
            logger.info("DownloadWorker canceled by user. task_id=%s output=%s", self.task_id, self.output_path)
            self.canceled.emit()
        except DownloadPaused:
            logger.info("DownloadWorker paused by user. task_id=%s output=%s", self.task_id, self.output_path)
            self.paused.emit()
            stale_source = self.output_path.with_name(f"{self.output_path.name}.source")
            if stale_source.exists():
                stale_source.unlink(missing_ok=True)
        except MusicFetchError as err:
            logger.warning("DownloadWorker failed. task_id=%s code=%s message=%s", self.task_id, err.code, err.message)
            self.failed.emit(err.code, err.message)
        except Exception as err:  # pragma: no cover
            logger.exception("DownloadWorker unexpected error. task_id=%s", self.task_id)
            self.failed.emit(UNKNOWN_ERROR, str(err))
        finally:
            stale_source = self.output_path.with_name(f"{self.output_path.name}.source")
            if stale_source.exists():
                stale_source.unlink(missing_ok=True)
            stale_part = self.output_path.with_name(f"{self.output_path.name}.part")
            if stale_part.exists():
                stale_part.unlink(missing_ok=True)
