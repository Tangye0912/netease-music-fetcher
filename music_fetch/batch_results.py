"""Pure helpers for batch download result handling."""

from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from io import StringIO
from typing import Iterable, Protocol

import music_fetch.ui_texts as T


BATCH_CSV_FIELDS = (
    "source_type",
    "source_label",
    "raw_input",
    "song_id",
    "song_name",
    "status",
    "status_text",
    "message",
    "media_size_bytes",
    "selected",
)
UNKNOWN_FAILURE_REASON = "未知原因"



__all__ = ['BATCH_CSV_FIELDS', 'UNKNOWN_FAILURE_REASON', 'build_batch_results_csv', 'retryable_failed_rows', 'summarize_batch_rows']
class BatchResultRow(Protocol):
    raw_input: str
    source_type: str
    source_label: str
    song_id: str
    song_name: str
    status: str
    message: str
    media_size_bytes: int
    selected: bool


@dataclass(frozen=True)
class BatchSummary:
    total: int
    ready: int
    duplicate: int
    failed: int
    unavailable: int
    download_success: int
    download_failed: int
    download_canceled: int
    failure_reasons: dict[str, int]

    @property
    def bad(self) -> int:
        return self.failed + self.unavailable


def retryable_failed_rows(rows: Iterable[BatchResultRow]) -> list[BatchResultRow]:
    return [row for row in rows if _normalized_status(row) == "download_failed"]


def summarize_batch_rows(rows: Iterable[BatchResultRow]) -> BatchSummary:
    materialized = list(rows)
    counts = Counter(_normalized_status(row) for row in materialized)
    failure_reasons: Counter[str] = Counter()
    for row in materialized:
        if _normalized_status(row) != "download_failed":
            continue
        reason = (row.message or "").strip() or UNKNOWN_FAILURE_REASON
        failure_reasons[reason] += 1
    return BatchSummary(
        total=len(materialized),
        ready=counts["ready"],
        duplicate=counts["duplicate"],
        failed=counts["failed"],
        unavailable=counts["unavailable"],
        download_success=counts["download_success"],
        download_failed=counts["download_failed"],
        download_canceled=counts["download_canceled"],
        failure_reasons=dict(failure_reasons),
    )


def build_batch_results_csv(rows: Iterable[BatchResultRow]) -> str:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=BATCH_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "source_type": row.source_type,
                "source_label": row.source_label,
                "raw_input": row.raw_input,
                "song_id": row.song_id,
                "song_name": row.song_name,
                "status": row.status,
                "status_text": T.batch_detect_status_text(row.status),
                "message": row.message,
                "media_size_bytes": row.media_size_bytes,
                "selected": str(bool(row.selected)).lower(),
            }
        )
    return output.getvalue()


def _normalized_status(row: BatchResultRow) -> str:
    return (row.status or "").strip().lower()
