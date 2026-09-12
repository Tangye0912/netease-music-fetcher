"""Compatibility batch adapter over the application queue."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from music_fetch.app_stores import DownloadHistoryStore
from music_fetch.app_settings import DEFAULT_GUI_TARGET_FORMAT
from music_fetch.batch_models import format_bytes
from music_fetch.batch_results import BatchResultRow, summarize_batch_rows
from music_fetch.download_queue import DownloadOptions, DownloadQueue, DownloadRequest
from music_fetch.download_runner import DownloadJob, DownloadProgressSnapshot
import music_fetch.ui_texts as T


@dataclass(frozen=True)
class BatchDownloadCounters:
    cursor: int
    total: int
    success: int
    failed: int
    canceled: int
    active: int
    paused: bool
    cancel_requested: bool

    @property
    def pending(self) -> int:
        return max(self.total - self.cursor, 0)


class BatchDownloadSession:
    def __init__(self, rows: Sequence[BatchResultRow], out_dir: Path, cookie: str,
                 history_store: DownloadHistoryStore, target_format: str = DEFAULT_GUI_TARGET_FORMAT,
                 timeout: int = 30, retry_count: int = 1, concurrency: int = 1,
                 download_lyric: bool = False, lyric_mode: str = "original") -> None:
        self._queue = list(rows)
        self._out_dir = out_dir
        self._driver = DownloadQueue(history_store, cookie, concurrency, timeout, retry_count, DownloadJob)
        options = DownloadOptions(str(out_dir), target_format, lyric_mode if download_lyric else "none")
        self._row_items = [(row, self._driver.enqueue(DownloadRequest(row.song_id, row.song_name, options))) for row in rows]
        self._total = len(rows)
        self._cursor = self._success = self._failed = self._canceled = 0
        self._stopped = self._auth_expired = self._cancel_requested = False

    @property
    def done(self) -> bool:
        return not self._driver.unfinished

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def auth_expired(self) -> bool:
        return self._auth_expired

    @property
    def _jobs(self) -> dict[int, DownloadJob]:
        return {id(item.job): item.job for item in self._driver.active if item.job is not None}

    def counters(self) -> BatchDownloadCounters:
        return BatchDownloadCounters(self._cursor, self._total, self._success, self._failed,
                                     self._canceled, len(self._driver.active), self._driver.paused,
                                     self._cancel_requested)

    def active_jobs(self) -> list[tuple[str, DownloadProgressSnapshot]]:
        return [(item.request.song_name, item.progress) for item in self._driver.active]

    def request_pause_all(self) -> None:
        self._driver.pause_all()
        self._sync()

    def request_resume_all(self) -> None:
        self._driver.resume_all()
        self._sync()

    def request_cancel_all(self) -> None:
        self._cancel_requested = self._stopped = True
        self._driver.cancel_all()
        self._sync()

    def poll(self) -> None:
        self._driver.poll()
        if self._driver.auth_required:
            self._auth_expired = True
            for item in self._driver.items:
                if item.error_code == "AUTH_EXPIRED":
                    item.state = "failed"
                    self._driver._record(item)
            self.request_cancel_all()
        self._sync()

    def _sync(self) -> None:
        states = {"pending": "ready", "running": "downloading", "paused": "download_paused",
                  "canceling": "downloading", "waiting_login": "ready", "success": "download_success",
                  "failed": "download_failed", "canceled": "download_canceled", "skipped": "download_success"}
        for row, item in self._row_items:
            row.status = states[item.state]
            row.message = T.code_message(item.error_code, item.message) if item.error_code else item.message
            if item.state in {"success", "failed", "canceled", "skipped"}:
                row.selected = False
            if item.size_bytes:
                row.media_size_bytes = item.size_bytes
        counts = self._driver.counts()
        self._success = counts["success"] + counts["skipped"]
        self._failed = counts["failed"]
        self._canceled = counts["canceled"]
        self._cursor = self._success + self._failed + self._canceled

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

    def summary_panel_rows(self) -> list[tuple[str, str]]:
        """Key-value rows for the end-of-run summary card in the TUI."""
        rows: list[tuple[str, str]] = []
        if self._stopped:
            rows.append(("状态", f"已停止（未开始 {max(self._total - self._cursor, 0)}）"))
        else:
            rows.append(("状态", "完成"))
        rows.extend(
            [
                ("成功", str(self._success)),
                ("失败", str(self._failed)),
                ("取消", str(self._canceled)),
                ("输出目录", str(self._out_dir)),
            ]
        )
        failure_reasons = summarize_batch_rows(self._queue).failure_reasons
        if failure_reasons:
            top_reasons = sorted(failure_reasons.items(), key=lambda item: (-item[1], item[0]))[:3]
            reasons_text = "；".join(f"{reason} x{count}" for reason, count in top_reasons)
            rows.append(("失败原因", reasons_text))
            rows.append(("提示", "失败项可在下载历史中重试"))
        return rows

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
