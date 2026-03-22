#!/usr/bin/env python3
"""Helpers for retrying failed download tasks."""

from __future__ import annotations

from pathlib import Path

from app_settings import DEFAULT_GUI_TARGET_FORMAT
from download_tasks import TASK_STATE_FAILED
from music_fetch import SUPPORTED_GUI_AUDIO_FORMATS


def can_retry_status(status: str) -> bool:
    # v0.4.0: retry action is only available for failed tasks.
    return (status or "").strip().lower() == TASK_STATE_FAILED


def retry_target_format(output_path: Path) -> str:
    suffix = output_path.suffix.lower().lstrip(".")
    if suffix in SUPPORTED_GUI_AUDIO_FORMATS:
        return suffix
    return DEFAULT_GUI_TARGET_FORMAT
