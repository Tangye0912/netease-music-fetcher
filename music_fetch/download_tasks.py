#!/usr/bin/env python3
"""Download task state model shared by GUI flow."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# v0.4.0: unify download flow around explicit task states.
TASK_STATE_PENDING = "pending"
TASK_STATE_DOWNLOADING = "downloading"
TASK_STATE_SUCCESS = "success"
TASK_STATE_FAILED = "failed"
TASK_STATE_CANCELED = "canceled"

TASK_STATES = (
    TASK_STATE_PENDING,
    TASK_STATE_DOWNLOADING,
    TASK_STATE_SUCCESS,
    TASK_STATE_FAILED,
    TASK_STATE_CANCELED,
)

FINAL_TASK_STATES = (
    TASK_STATE_SUCCESS,
    TASK_STATE_FAILED,
    TASK_STATE_CANCELED,
)


@dataclass
class DownloadTaskSnapshot:
    task_id: str
    song_id: str
    output_path: str
    state: str
    error_code: str = ""


def is_valid_task_state(state: str) -> bool:
    return state in TASK_STATES


def normalize_task_state(state: str) -> str:
    normalized = (state or "").strip().lower()
    if not is_valid_task_state(normalized):
        raise ValueError(f"Unsupported task state: {state}")
    return normalized


def build_task_id(song_id: str, now_ms: int | None = None) -> str:
    timestamp = now_ms if now_ms is not None else int(time.time() * 1000)
    return f"{song_id}-{timestamp}"


def next_task_snapshot(
    previous: Optional[DownloadTaskSnapshot],
    *,
    song_id: str,
    output_path: Path,
    state: str,
    error_code: str = "",
    now_ms: Optional[int] = None,
) -> DownloadTaskSnapshot:
    normalized_state = normalize_task_state(state)
    if previous is None or previous.song_id != song_id:
        task_id = build_task_id(song_id, now_ms=now_ms)
    else:
        task_id = previous.task_id
    return DownloadTaskSnapshot(
        task_id=task_id,
        song_id=song_id,
        output_path=str(output_path),
        state=normalized_state,
        error_code=(error_code or "").strip(),
    )
