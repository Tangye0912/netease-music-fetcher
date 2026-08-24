#!/usr/bin/env python3
"""Pure batch detection logic extracted from the GUI-era workers.py.

Parses mixed pasted text (links / IDs / share messages), expands playlists,
dedupes song ids, and detects every unique song concurrently with a bounded
worker pool.  Cancellation keeps already-completed rows and stops launching
new network work.
"""

from __future__ import annotations

import threading
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Callable, Optional

from music_fetch.api import MusicFetchError, detect_song, fetch_playlist_song_ids, parse_input_resource
from music_fetch.app_logging import get_logger
from music_fetch.batch_inputs import collect_batch_candidates, source_hint_map
from music_fetch.batch_models import BatchDetectRow, probe_media_size_bytes
from music_fetch.error_texts import user_error_message
import music_fetch.ui_texts as T

logger = get_logger("music_fetch.batch_inspect")

BatchDetectProgressCallback = Callable[[int, int, str], None]


def run_batch_detect(
    raw_input_text: str,
    cookie: str,
    timeout: int,
    detect_concurrency: int = 5,
    cancel_event: Optional[threading.Event] = None,
    on_progress: Optional[BatchDetectProgressCallback] = None,
) -> list[BatchDetectRow]:
    """Detect every candidate song in mixed pasted text and return row results.

    Duplicate rows are appended to the tail; the remaining rows keep input
    order.  When *cancel_event* fires, detection stops early and the rows
    completed so far are returned.
    """
    cancel = cancel_event if cancel_event is not None else threading.Event()
    concurrency = max(1, min(10, int(detect_concurrency)))

    candidates = collect_batch_candidates(raw_input_text)
    hint_map = source_hint_map(raw_input_text)
    if not candidates:
        return []
    logger.info("Batch detect started. deduped_count=%s", len(candidates))
    rows: list[BatchDetectRow] = []
    expanded: list[tuple[str, str, str, str]] = []
    for value in candidates:
        if cancel.is_set():
            break
        source_hint = hint_map.get(value, "")
        try:
            resource_type, resource_id = parse_input_resource(value)
            if resource_type == "playlist":
                playlist_label = source_hint or f"{T.BATCH_SOURCE_PLAYLIST}-{resource_id}"
                song_ids = fetch_playlist_song_ids(resource_id, cookie, timeout=timeout)
                if cancel.is_set():
                    break
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
    if not expanded:
        return rows

    # Build a deduplicated list while preserving order; duplicates are
    # collected separately and appended to the tail at the end.
    duplicate_rows: list[BatchDetectRow] = []
    unique_expanded: list[tuple[str, str, str, str]] = []
    for source_type, source_value, song_id, source_label in expanded:
        if song_id in seen_song_ids:
            duplicate_rows.append(
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

    # Keep only a small bounded set of futures alive so cancellation does not
    # leave a large queue of network requests waiting to start.
    completed_count = 0
    total_unique = len(unique_expanded)
    results_by_index: dict[int, BatchDetectRow] = {}

    def _detect_one(
        index: int,
        source_type: str,
        source_value: str,
        song_id: str,
        source_label: str,
    ) -> tuple[int, Optional[BatchDetectRow]]:
        if cancel.is_set():
            return (index, None)
        try:
            result = detect_song(song_id, cookie, timeout=timeout)
            size_bytes = 0
            if result.can_download and result.media_url and not cancel.is_set():
                size_bytes = probe_media_size_bytes(result.media_url, timeout=min(10, timeout))
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

    next_index = 0
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        pending: dict[Future[tuple[int, Optional[BatchDetectRow]]], int] = {}

        def _fill_pending() -> None:
            nonlocal next_index
            while (
                len(pending) < concurrency
                and next_index < total_unique
                and not cancel.is_set()
            ):
                source_type, source_value, song_id, source_label = unique_expanded[next_index]
                future = executor.submit(
                    _detect_one,
                    next_index,
                    source_type,
                    source_value,
                    song_id,
                    source_label,
                )
                pending[future] = next_index
                next_index += 1

        _fill_pending()
        while pending:
            finished, _unfinished = wait(
                tuple(pending),
                timeout=0.1,
                return_when=FIRST_COMPLETED,
            )
            for future in finished:
                pending.pop(future)
                idx, row = future.result()
                if row is None:
                    continue
                results_by_index[idx] = row
                completed_count += 1
                if on_progress is not None:
                    on_progress(completed_count, total_unique, unique_expanded[idx][2])
            if cancel.is_set():
                for future in pending:
                    future.cancel()
                break
            _fill_pending()

    # Reconstruct results in original order, then append duplicates after.
    for idx in range(total_unique):
        if idx in results_by_index:
            rows.append(results_by_index[idx])
    rows.extend(duplicate_rows)
    logger.info(
        "Batch detect completed. total=%s ready=%s duplicate=%s failed_or_unavailable=%s",
        len(rows),
        len([row for row in rows if row.status == "ready"]),
        len([row for row in rows if row.status == "duplicate"]),
        len([row for row in rows if row.status in {"failed", "unavailable"}]),
    )
    return rows


__all__ = ["run_batch_detect", "BatchDetectProgressCallback"]
