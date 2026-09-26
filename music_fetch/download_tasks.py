#!/usr/bin/env python3
"""Download task state model shared by the download runner and the TUI."""

from __future__ import annotations

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


def is_valid_task_state(state: str) -> bool:
    return state in TASK_STATES
