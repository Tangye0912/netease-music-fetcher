#!/usr/bin/env python3
"""
Download pipeline — pure-logic download orchestration shared by GUI and CLI.

Encapsulates the retry loop, candidate fallback, format conversion, and
cancel/pause checkers.  No Qt dependency.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from music_fetch.api import (
    DownloadCanceled,
    ErrorCode,
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
from music_fetch.network import open_url
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
    *, song_id: str, cookie: str, output_path: Path,
    target_format: str = DEFAULT_GUI_TARGET_FORMAT, timeout: int = 30,
    retry_count: int = 1, progress_callback: Optional[ProgressCallback] = None,
    cancel_checker: Optional[CancelChecker] = None,
    pause_checker: Optional[PauseChecker] = None,
    tags: Optional[dict[str, Optional[str]]] = None,
    download_lyric: bool = False, lyric_mode: str = "original",
    stage_callback: Optional[Callable[[str], None]] = None,
) -> DownloadPipelineResult:
    """Download into an owned staging directory; publish only complete files."""
    def checkpoint(stage: str) -> None:
        if stage_callback:
            stage_callback(stage)
        while pause_checker and pause_checker():
            if cancel_checker and cancel_checker():
                raise DownloadCanceled()
            time.sleep(0.05)
        if cancel_checker and cancel_checker():
            raise DownloadCanceled()

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        raise MusicFetchError(ErrorCode.DOWNLOAD_FAILED, f"Cannot write to output directory: {output_path.parent}") from err

    # Cancellation only cleans this task's directory, never a previous file.
    with tempfile.TemporaryDirectory(prefix=".music-fetch-", dir=output_path.parent) as staging:
        source = Path(staging) / "source"
        selected: Optional[PlayableCandidate] = None
        for attempt in range(retry_count + 1):
            checkpoint("resolving")
            try:
                def progress(downloaded: int, total: Optional[int]) -> None:
                    if stage_callback:
                        stage_callback("downloading")
                    if progress_callback:
                        progress_callback(downloaded, total)
                selected = download_song_with_fallback(
                    song_id=song_id, cookie=cookie, output_path=source, timeout=timeout,
                    prefer_format=target_format, progress_callback=progress,
                    cancel_checker=cancel_checker, pause_checker=pause_checker,
                )
                break
            except DownloadCanceled:
                raise
            except MusicFetchError as err:
                if attempt >= retry_count or err.code not in {"DOWNLOAD_FAILED", "NETWORK_ERROR"}:
                    raise
                logger.warning("Retrying download. song_id=%s attempt=%s code=%s", song_id, attempt + 1, err.code)
        if selected is None:
            raise MusicFetchError(ErrorCode.DOWNLOAD_FAILED, "No playable candidate.")
        source_format = infer_audio_format_from_url(selected.media_url) or selected.encode_type or "unknown"
        checkpoint("converting")
        actual_format = target_format
        if source_format != target_format and not is_ffmpeg_available() and source_format in SUPPORTED_GUI_AUDIO_FORMATS:
            actual_format = source_format
        prepared = Path(staging) / f"audio.{actual_format}"
        if source_format == actual_format:
            source.replace(prepared)
        else:
            convert_audio_file(source, prepared, target_format, timeout=max(240, timeout * 8),
                               cancel_checker=cancel_checker)
        checkpoint("tagging")
        if tags:
            try:
                write_audio_tags(prepared, title=tags.get("title") or "", artist=tags.get("artist"),
                                 album=tags.get("album"), cover_url=tags.get("cover_url"))
            except Exception:
                logger.warning("Failed to write audio tags. song_id=%s", song_id, exc_info=True)
        checkpoint("lyrics")
        if download_lyric:
            from music_fetch.api import fetch_lyric
            from music_fetch.audio import merge_bilingual_lyric, save_lyric_file, embed_lyric_tag
            try:
                lyric = fetch_lyric(song_id, timeout=timeout)
                text = lyric.lyric
                if lyric_mode == "translation":
                    text = lyric.translated_lyric or lyric.lyric
                elif lyric_mode == "bilingual":
                    text = merge_bilingual_lyric(lyric.lyric, lyric.translated_lyric)
                if text:
                    save_lyric_file(prepared, text)
                    embed_lyric_tag(prepared, text)
            except Exception:
                logger.warning("Failed to download lyric. song_id=%s", song_id, exc_info=True)
        checkpoint("finishing")
        final_path = _publish_file(prepared, output_path.with_suffix(f".{actual_format}"))
        lyric_path = prepared.with_suffix(".lrc")
        if lyric_path.exists():
            try:
                _publish_file(lyric_path, final_path.with_suffix(".lrc"))
            except OSError:
                logger.warning("Failed to save lyric sidecar. song_id=%s", song_id, exc_info=True)
        return DownloadPipelineResult(final_path, final_path.stat().st_size, selected, source_format)


def _publish_file(source: Path, target: Path) -> Path:
    """Claim an output name without overwriting a file, including concurrent writes."""
    for index in range(10000):
        candidate = target if index == 0 else target.with_name(f"{target.stem}_{index}{target.suffix}")
        try:
            os.link(source, candidate)
            return candidate
        except FileExistsError:
            continue
        except OSError:
            # External drives may not support hard links. Exclusive creation
            # keeps the same no-overwrite guarantee on those filesystems.
            try:
                handle = candidate.open("xb")
            except FileExistsError:
                continue
            try:
                with handle, source.open("rb") as reader:
                    shutil.copyfileobj(reader, handle)
            except BaseException:
                candidate.unlink(missing_ok=True)
                raise
            return candidate
    raise MusicFetchError(ErrorCode.DOWNLOAD_FAILED, "Could not allocate an output filename.")


def write_audio_tags(
    output_path: Path,
    title: str,
    artist: Optional[str] = None,
    album: Optional[str] = None,
    cover_url: Optional[str] = None,
) -> None:
    """Write ID3/Vorbis tags to the downloaded audio file using mutagen."""
    try:
        from mutagen import File as MutagenFile
        from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB
        from mutagen.mp3 import MP3
        from mutagen.mp4 import MP4
    except ImportError:
        logger.debug("mutagen not installed, skipping tag writing.")
        return

    try:
        audio = MutagenFile(str(output_path))
        if audio is None:
            logger.debug("Unsupported audio format for tagging: %s", output_path.suffix)
            return

        # Set basic tags — format-specific to avoid writing invalid frames
        if hasattr(audio, 'tags') and audio.tags is not None:
            if isinstance(audio, MP4):
                # MP4 uses 4-char atom codes
                if title:
                    audio.tags['\xa9nam'] = title
                if artist:
                    audio.tags['\xa9ART'] = artist
                if album:
                    audio.tags['\xa9alb'] = album
            elif isinstance(audio, MP3):
                # MP3 uses ID3 frame classes
                if title:
                    audio.tags.add(TIT2(encoding=3, text=title))
                if artist:
                    audio.tags.add(TPE1(encoding=3, text=artist))
                if album:
                    audio.tags.add(TALB(encoding=3, text=album))
            else:
                # FLAC, Ogg Vorbis, etc. use Vorbis comment keys
                if title:
                    audio.tags['title'] = title
                if artist:
                    audio.tags['artist'] = artist
                if album:
                    audio.tags['album'] = album
            audio.save()

        # Embed cover art for MP3 files
        if cover_url and output_path.suffix.lower() == '.mp3':
            try:
                from urllib import request
                req = request.Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
                with open_url(req, timeout=10) as resp:
                    cover_data = resp.read()
                if cover_data:
                    audio = MP3(str(output_path), ID3=ID3)
                    audio.tags.add(
                        APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,  # front cover
                            desc='Cover',
                            data=cover_data,
                        )
                    )
                    audio.save()
                    logger.info("Cover art embedded. output=%s", output_path)
            except Exception:
                logger.debug("Failed to embed cover art. output=%s", output_path, exc_info=True)

    except Exception:
        logger.debug("Failed to write audio tags. output=%s", output_path, exc_info=True)


def _cleanup_paths(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink(missing_ok=True)
