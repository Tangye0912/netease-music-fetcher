#!/usr/bin/env python3
"""Pure helpers for filtering and exporting download history."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path
from typing import Iterable

from music_fetch.app_stores import DownloadRecord
from music_fetch.csv_utils import safe_csv_text
import music_fetch.ui_texts as T

HISTORY_CSV_FIELDS = (
    "song_id",
    "song_name",
    "filename",
    "output_path",
    "size_bytes",
    "downloaded_at",
    "status",
    "status_text",
    "error_code",
)


def filter_download_history(
    records: Iterable[DownloadRecord],
    *,
    status_filter: str = "all",
    query: str = "",
) -> list[DownloadRecord]:
    """Filter history by task state and case-insensitive search terms."""
    normalized_status = (status_filter or "all").strip().lower()
    terms = [term for term in (query or "").casefold().split() if term]
    filtered: list[DownloadRecord] = []
    for record in records:
        if normalized_status not in {"", "all"} and record.status != normalized_status:
            continue
        if terms:
            searchable = "\n".join(
                (
                    record.song_id,
                    record.song_name,
                    Path(record.output_path).name,
                    record.output_path,
                    record.status,
                    T.manager_status_text(record.status),
                    record.error_code,
                )
            ).casefold()
            if not all(term in searchable for term in terms):
                continue
        filtered.append(record)
    return filtered


def build_download_history_csv(records: Iterable[DownloadRecord]) -> str:
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=HISTORY_CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for record in records:
        writer.writerow(
            {
                "song_id": safe_csv_text(record.song_id),
                "song_name": safe_csv_text(record.song_name),
                "filename": safe_csv_text(Path(record.output_path).name),
                "output_path": safe_csv_text(record.output_path),
                "size_bytes": record.size_bytes,
                "downloaded_at": safe_csv_text(record.downloaded_at),
                "status": safe_csv_text(record.status),
                "status_text": safe_csv_text(T.manager_status_text(record.status)),
                "error_code": safe_csv_text(record.error_code),
            }
        )
    return output.getvalue()


__all__ = [
    "HISTORY_CSV_FIELDS",
    "build_download_history_csv",
    "filter_download_history",
]
