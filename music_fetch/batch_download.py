#!/usr/bin/env python3
"""Pure batch download scheduling extracted from the GUI-era batch_dialogs.py.

A BatchDownloadSession keeps a bounded number of DownloadJob workers running,
updates each row's status, writes download-history records, and supports
pause-all / resume-all / cancel-all.  A terminal UI drives it by polling
poll() every ~100 ms.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

from music_fetch.api import MusicFetchError
from music_fetch.app_logging import get_logger
from music_fetch.app_stores import DownloadHistoryStore, DownloadRecord
from music_fetch.app_settings import DEFAULT_GUI_TARGET_FORMAT
from music_fetch.audio import resolve_output_path
from music_fetch.batch_models import format_bytes
from music_fetch.batch_results import BatchResultRow, summarize_batch_rows
from music_fetch.download_runner import (
    DownloadJob,
    DownloadJobResult,
    DownloadProgressSnapshot,
    JOB_STATE_CANCELED,
    JOB_STATE_FAILED,
    JOB_STATE_SUCCESS,
)
from music_fetch.download_tasks import (
    TASK_STATE_CANCELED,
    TASK_STATE_FAILED,
    TASK_STATE_SUCCESS,
    build_task_id,
)
from music_fetch.error_texts import user_error_message
import music_fetch.ui_texts as T

logger = get_logger("music_fetch.batch_download")


@dataclass(frozen=True)
class BatchDownloadCounters:
    cursor: int  # finished rows (success + failed + canceled)
    total: int
    success: int
    failed: int
    canceled: int
    active: int  # currently running jobs
    paused: bool
    cancel_requested: bool

    @property
    def pending(self) -> int:
        return max(self.total - self.cursor, 0)


class BatchDownloadSession:
    """Drive concurrent downloads for a list of selected batch rows."""

    def __init__(
        self,
        rows: Sequence[BatchResultRow],
        out_dir: Path,
        cookie: str,
        history_store: DownloadHistoryStore,
        target_format: str = DEFAULT_GUI_TARGET_FORMAT,
        timeout: int = 30,
        retry_count: int = 1,
        concurrency: int = 1,
        download_lyric: bool = False,
        lyric_mode: str = "original",
    ) -> None:
        self._queue: list[BatchResultRow] = list(rows)
        self._total = len(self._queue)
        self._out_dir = out_dir
        self._cookie = cookie
        self._history_store = history_store
        self._format = (target_format or DEFAULT_GUI_TARGET_FORMAT).lower().strip()
        self._timeout = timeout
        self._retry_count = retry_count
        self._concurrency = max(1, int(concurrency))
        self._download_lyric = download_lyric
        self._lyric_mode = lyric_mode

        self._jobs: dict[int, DownloadJob] = {}
        self._job_rows: dict[int, BatchResultRow] = {}
        self._job_paths: dict[int, Path] = {}
        self._next_index = 0
        self._cursor = 0
        self._success = 0
        self._failed = 0
        self._canceled = 0
        self._paused = False
        self._cancel_requested = False
        self._done = False
        self._stopped = False
        self._auth_expired = False

    # ── state API ─────────────────────────────────────────────────

    @property
    def done(self) -> bool:
        return self._done

    @property
    def stopped(self) -> bool:
        """True when the flow ended early because of a cancel request."""
        return self._stopped

    @property
    def auth_expired(self) -> bool:
        """True when a worker rejected the app-owned login credential."""
        return self._auth_expired

    def counters(self) -> BatchDownloadCounters:
        return BatchDownloadCounters(
            cursor=self._cursor,
            total=self._total,
            success=self._success,
            failed=self._failed,
            canceled=self._canceled,
            active=len(self._jobs),
            paused=self._paused,
            cancel_requested=self._cancel_requested,
        )

    def active_jobs(self) -> list[tuple[str, DownloadProgressSnapshot]]:
        """Active jobs as (label, progress snapshot) for UI rendering."""
        result: list[tuple[str, DownloadProgressSnapshot]] = []
        for job in self._jobs.values():
            row = self._job_rows.get(id(job))
            label = (row.song_name or row.song_id) if row else job.song_id
            result.append((label, job.progress()))
        return result

    # ── control API ───────────────────────────────────────────────

    def request_pause_all(self) -> None:
        if self._paused:
            return
        self._paused = True
        for key, job in self._jobs.items():
            row = self._job_rows.get(key)
            if row and row.status == "downloading":
                row.status = "download_paused"
            job.request_pause()
        logger.info("Batch download paused. cursor=%s/%s", self._cursor, self._total)

    def request_resume_all(self) -> None:
        if not self._paused:
            return
        self._paused = False
        for key, job in self._jobs.items():
            row = self._job_rows.get(key)
            if row and row.status == "download_paused":
                row.status = "downloading"
            job.request_resume()
        logger.info("Batch download resumed. remaining=%s", self._total - self._cursor)

    def request_cancel_all(self) -> None:
        self._cancel_requested = True
        for job in self._jobs.values():
            job.request_cancel()
        logger.info("Batch download cancel requested. cursor=%s/%s", self._cursor, self._total)

    # ── driver API ────────────────────────────────────────────────

    def poll(self) -> None:
        """Advance the session: collect finished jobs, dispatch new ones."""
        if self._done:
            return

        for key in list(self._jobs):
            if self._jobs[key].state() in (JOB_STATE_SUCCESS, JOB_STATE_FAILED, JOB_STATE_CANCELED):
                self._finish_job(key)

        if self._cancel_requested and not self._jobs:
            self._done = True
            self._stopped = self._cursor < self._total
            return

        while (
            len(self._jobs) < self._concurrency
            and self._next_index < self._total
            and not self._cancel_requested
            and not self._paused
        ):
            self._dispatch_next()

        if self._cursor >= self._total and not self._jobs:
            self._done = True
            self._stopped = self._cancel_requested

    # ── internals ─────────────────────────────────────────────────

    def _dispatch_next(self) -> None:
        row = self._queue[self._next_index]
        self._next_index += 1
        try:
            output_path = resolve_output_path(
                out_dir=self._out_dir,
                song_id=row.song_id,
                song_name=row.song_name or None,
                rename=None,
                out_format=self._format,
            )
        except MusicFetchError as err:
            row.status = "download_failed"
            row.message = T.code_message(err.code, user_error_message(err.code, err.message))
            row.selected = False
            self._history_store.add(
                self._make_record(
                    row, TASK_STATE_FAILED, 0,
                    str(self._out_dir / f"song-{row.song_id}.{self._format}"), err.code,
                )
            )
            self._failed += 1
            self._cursor += 1
            if err.code == "AUTH_EXPIRED":
                self._auth_expired = True
                self.request_cancel_all()
            return

        row.status = "downloading"
        row.message = ""
        job = DownloadJob(
            task_id=build_task_id(row.song_id),
            song_id=row.song_id,
            output_path=output_path,
            cookie=self._cookie,
            target_format=self._format,
            timeout=self._timeout,
            retry_count=self._retry_count,
            tags={"title": row.song_name or "", "artist": None, "album": None, "cover_url": None},
            download_lyric=self._download_lyric,
            lyric_mode=self._lyric_mode,
        )
        job.start()
        key = id(job)
        self._jobs[key] = job
        self._job_rows[key] = row
        self._job_paths[key] = output_path

    def _finish_job(self, key: int) -> None:
        job = self._jobs.pop(key)
        row = self._job_rows.pop(key, None)
        output_path = self._job_paths.pop(key, None)
        if row is None:
            return
        result = job.result()
        if result is None:  # pragma: no cover - defensive
            result = DownloadJobResult(state=JOB_STATE_FAILED, output_path=output_path or Path())
        if result.state == JOB_STATE_SUCCESS:
            row.status = "download_success"
            row.selected = False
            row.media_size_bytes = result.file_size if result.file_size > 0 else row.media_size_bytes
            row.message = Path(result.output_path).name
            self._history_store.add(
                self._make_record(row, TASK_STATE_SUCCESS, result.file_size, str(result.output_path))
            )
            self._success += 1
        elif result.state == JOB_STATE_FAILED:
            row.status = "download_failed"
            row.selected = False
            row.message = T.code_message(
                result.error_code, user_error_message(result.error_code, result.error_message)
            )
            self._history_store.add(
                self._make_record(
                    row, TASK_STATE_FAILED, 0,
                    str(output_path) if output_path else "", result.error_code,
                )
            )
            self._failed += 1
            if result.error_code == "AUTH_EXPIRED":
                self._auth_expired = True
                self.request_cancel_all()
        else:
            row.status = "download_canceled"
            row.selected = False
            row.message = T.MSG_DOWNLOAD_CANCELED
            self._history_store.add(
                self._make_record(
                    row, TASK_STATE_CANCELED, 0,
                    str(output_path) if output_path else "",
                )
            )
            self._canceled += 1
        self._cursor += 1

    @staticmethod
    def _make_record(
        row: BatchResultRow,
        status: str,
        size_bytes: int = 0,
        output_path: str = "",
        error_code: str = "",
    ) -> DownloadRecord:
        return DownloadRecord(
            song_id=row.song_id,
            song_name=row.song_name or f"song-{row.song_id}",
            output_path=output_path,
            size_bytes=size_bytes,
            downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            status=status,
            error_code=error_code,
        )

    # ── summary ───────────────────────────────────────────────────

    def summary_text(self) -> str:
        """One-line final summary, including aggregated failure reasons."""
        if self._stopped:
            summary = T.BATCH_DOWNLOAD_STOPPED.format(
                processed=self._cursor,
                total=self._total,
                success=self._success,
                failed=self._failed,
                canceled=self._canceled,
                pending=max(self._total - self._cursor, 0),
            )
        else:
            summary = T.BATCH_DOWNLOAD_SUMMARY.format(
                success=self._success,
                failed=self._failed,
                canceled=self._canceled,
            )
        reasons = self._failure_reason_summary()
        if reasons:
            return f"{summary} {T.BATCH_FAILURE_REASON_SUMMARY.format(reasons=reasons)}"
        return summary

    def _failure_reason_summary(self) -> str:
        failure_reasons = summarize_batch_rows(self._queue).failure_reasons
        if not failure_reasons:
            return ""
        parts = [f"{reason} x{count}" for reason, count in sorted(failure_reasons.items())]
        return "；".join(parts)


def format_speed(speed: float) -> str:
    return f"{format_bytes(int(speed))}/s"


__all__ = [
    "BatchDownloadCounters",
    "BatchDownloadSession",
    "format_speed",
]
