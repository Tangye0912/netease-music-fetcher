#!/usr/bin/env python3
"""Thread-based download job runner.

Replaces the GUI-era QThread DownloadWorker: one background thread per
download, with a thread-safe snapshot API that a terminal UI can poll
(progress / state / result) and control (pause / resume / cancel).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from music_fetch.api import DownloadCanceled, MusicFetchError
from music_fetch.app_logging import get_logger
from music_fetch.app_settings import (
    DEFAULT_DOWNLOAD_RETRY_COUNT,
    DEFAULT_GUI_TARGET_FORMAT,
    clamp_download_settings,
)
from music_fetch.error_texts import UNKNOWN_ERROR
from music_fetch.pipeline import run_download_pipeline

logger = get_logger("music_fetch.runner")

JOB_STATE_PENDING = "pending"
JOB_STATE_RUNNING = "running"
JOB_STATE_SUCCESS = "success"
JOB_STATE_FAILED = "failed"
JOB_STATE_CANCELED = "canceled"
JOB_RUNNING_STATES = (JOB_STATE_PENDING, JOB_STATE_RUNNING)


@dataclass(frozen=True)
class DownloadProgressSnapshot:
    downloaded: int
    total: int  # -1 when the server did not report a total size
    speed: float  # bytes per second, averaged over the whole run


@dataclass(frozen=True)
class DownloadJobResult:
    state: str  # success | failed | canceled
    output_path: Path
    file_size: int = 0
    error_code: str = ""
    error_message: str = ""


class DownloadJob:
    """Run one download pipeline in a background thread.

    The UI thread drives the job by polling progress()/state()/result() and
    calling request_pause()/request_resume()/request_cancel().
    """

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
        download_lyric: bool = False,
    ) -> None:
        self.task_id = task_id
        self.song_id = song_id
        self.output_path = output_path
        self.cookie = cookie
        self.target_format = (target_format or DEFAULT_GUI_TARGET_FORMAT).lower().strip()
        # Keep timeout/retry bounded and predictable, like the old worker did.
        _, self.timeout, self.retry_count, _ = clamp_download_settings(0, timeout, retry_count, 0)
        self._tags = tags
        self.download_lyric = download_lyric

        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._lock = threading.Lock()
        self._downloaded = 0
        self._total = -1
        self._speed = 0.0
        self._started_at: Optional[float] = None
        self._state = JOB_STATE_PENDING
        self._result: Optional[DownloadJobResult] = None
        self._thread: Optional[threading.Thread] = None

    # ── control API ───────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name=f"download-{self.task_id}", daemon=True)
        self._thread.start()

    def request_pause(self) -> None:
        self._pause_event.set()

    def request_resume(self) -> None:
        self._pause_event.clear()

    def request_cancel(self) -> None:
        self._cancel_event.set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until the job finishes; returns True when finished."""
        if self._thread is None:
            return self._state not in JOB_RUNNING_STATES
        self._thread.join(timeout)
        return self._state not in JOB_RUNNING_STATES

    # ── status API (thread-safe) ──────────────────────────────────

    def state(self) -> str:
        with self._lock:
            return self._state

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    def progress(self) -> DownloadProgressSnapshot:
        with self._lock:
            return DownloadProgressSnapshot(
                downloaded=self._downloaded,
                total=self._total,
                speed=self._speed,
            )

    def result(self) -> Optional[DownloadJobResult]:
        with self._lock:
            return self._result

    # ── internals ─────────────────────────────────────────────────

    def _set_progress(self, downloaded: int, total: Optional[int], speed: float) -> None:
        with self._lock:
            self._downloaded = downloaded
            self._total = total if total is not None else -1
            self._speed = speed

    def _finish(self, result: DownloadJobResult) -> None:
        with self._lock:
            self._result = result
            self._state = result.state

    def _run(self) -> None:
        started_at = time.time()
        with self._lock:
            self._state = JOB_STATE_RUNNING
        logger.info(
            "DownloadJob started. task_id=%s output=%s timeout=%ss retry_count=%s",
            self.task_id, self.output_path, self.timeout, self.retry_count,
        )

        def on_progress(downloaded: int, total: Optional[int]) -> None:
            elapsed = max(time.time() - started_at, 0.001)
            self._set_progress(downloaded, total, downloaded / elapsed)

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
                download_lyric=self.download_lyric,
            )
            self._finish(
                DownloadJobResult(
                    state=JOB_STATE_SUCCESS,
                    output_path=result.output_path,
                    file_size=result.file_size,
                )
            )
            logger.info(
                "DownloadJob succeeded. task_id=%s output=%s size=%s",
                self.task_id, result.output_path, result.file_size,
            )
        except DownloadCanceled:
            self._finish(DownloadJobResult(state=JOB_STATE_CANCELED, output_path=self.output_path))
            logger.info("DownloadJob canceled. task_id=%s output=%s", self.task_id, self.output_path)
        except MusicFetchError as err:
            self._finish(
                DownloadJobResult(
                    state=JOB_STATE_FAILED,
                    output_path=self.output_path,
                    error_code=err.code,
                    error_message=err.message,
                )
            )
            logger.warning(
                "DownloadJob failed. task_id=%s code=%s message=%s",
                self.task_id, err.code, err.message,
            )
        except Exception as err:  # pragma: no cover - defensive
            self._finish(
                DownloadJobResult(
                    state=JOB_STATE_FAILED,
                    output_path=self.output_path,
                    error_code=UNKNOWN_ERROR,
                    error_message=str(err),
                )
            )
            logger.exception("DownloadJob unexpected error. task_id=%s", self.task_id)
        finally:
            for suffix in (".source", ".part", ".source.part", ".part.src", ".source.part.src"):
                stale = self.output_path.with_name(f"{self.output_path.name}{suffix}")
                if stale.exists():
                    stale.unlink(missing_ok=True)


__all__ = [
    "DownloadJob",
    "DownloadJobResult",
    "DownloadProgressSnapshot",
    "JOB_STATE_PENDING",
    "JOB_STATE_RUNNING",
    "JOB_STATE_SUCCESS",
    "JOB_STATE_FAILED",
    "JOB_STATE_CANCELED",
    "JOB_RUNNING_STATES",
]
