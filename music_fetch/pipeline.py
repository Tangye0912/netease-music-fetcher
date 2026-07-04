#!/usr/bin/env python3
"""
Download pipeline — pure-logic download orchestration shared by GUI and CLI.

Encapsulates the retry loop, candidate fallback, format conversion, and
cancel/pause checkers.  No Qt dependency.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from music_fetch.api import (
    DownloadCanceled,
    DownloadPaused,
    MusicFetchError,
    PlayableCandidate,
    CancelChecker,
    PauseChecker,
    ProgressCallback,
)
from music_fetch.audio import (
    SUPPORTED_GUI_AUDIO_FORMATS,
    convert_audio_file,
    download_song_with_fallback,
    infer_audio_format_from_url,
    is_ffmpeg_available,
)
from music_fetch.app_logging import get_logger
from music_fetch.app_settings import DEFAULT_GUI_TARGET_FORMAT

logger = get_logger("music_fetch.pipeline")


@dataclass
class DownloadPipelineResult:
    """Result of a DownloadPipeline run."""
    output_path: Path
    file_size: int
    candidate: PlayableCandidate
    source_format: str


def run_download_pipeline(
    *,
    song_id: str,
    cookie: str,
    output_path: Path,
    target_format: str = DEFAULT_GUI_TARGET_FORMAT,
    timeout: int = 30,
    retry_count: int = 1,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_checker: Optional[CancelChecker] = None,
    pause_checker: Optional[PauseChecker] = None,
) -> DownloadPipelineResult:
    """Execute the full download pipeline: retry loop, fallback, conversion.

    Raises DownloadCanceled, DownloadPaused, or MusicFetchError.
    """
    logger.info(
        "Download pipeline started. song_id=%s output=%s format=%s timeout=%s retry=%s",
        song_id, output_path, target_format, timeout, retry_count,
    )

    temp_source_path = output_path.with_name(f"{output_path.name}.source")
    if temp_source_path.exists():
        temp_source_path.unlink(missing_ok=True)

    # ── Retry loop ──────────────────────────────────────────────
    selected: Optional[PlayableCandidate] = None
    for attempt in range(1, retry_count + 2):
        try:
            selected = download_song_with_fallback(
                song_id=song_id,
                cookie=cookie,
                output_path=temp_source_path,
                timeout=timeout,
                prefer_format=target_format,
                progress_callback=progress_callback,
                cancel_checker=cancel_checker,
                pause_checker=pause_checker,
            )
            break
        except (DownloadCanceled, DownloadPaused):
            raise
        except MusicFetchError as err:
            is_last_attempt = attempt >= retry_count + 1
            retriable = err.code in {"DOWNLOAD_FAILED", "NETWORK_ERROR"}
            if not retriable or is_last_attempt:
                raise
            logger.warning(
                "Download attempt failed and will retry. song_id=%s attempt=%s/%s code=%s",
                song_id, attempt, retry_count + 1, err.code,
            )

    if selected is None:
        raise MusicFetchError("DOWNLOAD_FAILED", "Retry loop ended without a playable candidate.")

    source_format = infer_audio_format_from_url(selected.media_url) or "unknown"
    logger.info(
        "Download source completed. song_id=%s source_format=%s target_format=%s",
        song_id, source_format, target_format,
    )

    # ── Cancel check after download ─────────────────────────────
    if cancel_checker and cancel_checker():
        _cleanup_paths(temp_source_path, output_path)
        raise DownloadCanceled()

    # ── Format conversion / move ────────────────────────────────
    if source_format == target_format:
        temp_source_path.replace(output_path)
        if cancel_checker and cancel_checker():
            _cleanup_paths(output_path)
            raise DownloadCanceled()
    else:
        if not is_ffmpeg_available() and source_format in SUPPORTED_GUI_AUDIO_FORMATS:
            fallback_output = output_path.with_suffix(f".{source_format}")
            if fallback_output.exists():
                fallback_output = fallback_output.with_name(
                    f"{fallback_output.stem}_{int(time.time())}{fallback_output.suffix}"
                )
            if cancel_checker and cancel_checker():
                _cleanup_paths(temp_source_path, fallback_output)
                raise DownloadCanceled()
            temp_source_path.replace(fallback_output)
            if cancel_checker and cancel_checker():
                _cleanup_paths(fallback_output)
                raise DownloadCanceled()
            file_size = fallback_output.stat().st_size if fallback_output.exists() else 0
            logger.warning(
                "ffmpeg missing. song_id=%s saved source format directly. requested=%s source=%s output=%s",
                song_id, target_format, source_format, fallback_output,
            )
            return DownloadPipelineResult(
                output_path=fallback_output, file_size=file_size,
                candidate=selected, source_format=source_format,
            )

        if cancel_checker and cancel_checker():
            _cleanup_paths(temp_source_path, output_path)
            raise DownloadCanceled()
        convert_audio_file(
            temp_source_path, output_path, target_format,
            timeout=max(240, timeout * 8),
        )
        temp_source_path.unlink(missing_ok=True)
        if cancel_checker and cancel_checker():
            _cleanup_paths(output_path)
            raise DownloadCanceled()

    file_size = output_path.stat().st_size if output_path.exists() else 0
    logger.info(
        "Download pipeline completed. song_id=%s output=%s size=%s",
        song_id, output_path, file_size,
    )
    return DownloadPipelineResult(
        output_path=output_path, file_size=file_size,
        candidate=selected, source_format=source_format,
    )


def _cleanup_paths(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink(missing_ok=True)