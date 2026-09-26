#!/usr/bin/env python3
"""
Download pipeline — pure-logic download orchestration used by the background
download queue (music_fetch.download_queue, driven by download_runner).

Encapsulates the retry loop, candidate fallback, format conversion, and
cancel/pause checkers.  No UI dependency.
"""

from __future__ import annotations

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
    SUPPORTED_AUDIO_FORMATS,
    convert_audio_file,
    download_song_with_fallback,
    infer_audio_format_from_url,
    is_ffmpeg_available,
    is_path_too_long_error,
)
from music_fetch.network import open_url
from music_fetch.app_logging import get_logger
from music_fetch.app_settings import DEFAULT_TARGET_FORMAT

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
    target_format: str = DEFAULT_TARGET_FORMAT,
    timeout: int = 30,
    retry_count: int = 1,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_checker: Optional[CancelChecker] = None,
    pause_checker: Optional[PauseChecker] = None,
    tags: Optional[dict[str, Optional[str]]] = None,
    download_lyric: bool = False,
    lyric_mode: str = "original",
    stage_callback: Optional[Callable[[str], None]] = None,
) -> DownloadPipelineResult:
    """Execute the full download pipeline: retry loop, fallback, conversion.

    *stage_callback* (optional) reports coarse progress phases — "resolving",
    "downloading", "converting", "tagging", "lyrics" — for UI display.

    Raises DownloadCanceled or MusicFetchError.
    """

    def emit_stage(stage: str) -> None:
        if stage_callback is None:
            return
        try:
            stage_callback(stage)
        except Exception:  # a UI callback must never break the download
            logger.debug("stage callback failed. stage=%s", stage, exc_info=True)

    logger.info(
        "Download pipeline started. song_id=%s output=%s format=%s timeout=%s retry=%s",
        song_id, output_path, target_format, timeout, retry_count,
    )

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError as err:
        raise MusicFetchError(ErrorCode.DOWNLOAD_FAILED, f"Cannot write to output directory: {output_path.parent}") from err
    except OSError as err:
        if is_path_too_long_error(err):
            raise MusicFetchError(ErrorCode.PATH_TOO_LONG, f"Output path is too long: {output_path}") from err
        raise

    temp_source_path = output_path.with_name(f"{output_path.name}.source")
    if temp_source_path.exists():
        temp_source_path.unlink(missing_ok=True)

    # ── Retry loop ──────────────────────────────────────────────
    selected: Optional[PlayableCandidate] = None
    for attempt in range(1, retry_count + 2):
        emit_stage("resolving" if attempt == 1 else "retrying")
        try:
            emit_stage("downloading")
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
        except DownloadCanceled:
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
        raise MusicFetchError(ErrorCode.DOWNLOAD_FAILED, "Retry loop ended without a playable candidate.")

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
    emit_stage("converting")
    if source_format == target_format:
        temp_source_path.replace(output_path)
        if cancel_checker and cancel_checker():
            _cleanup_paths(output_path)
            raise DownloadCanceled()
    else:
        if not is_ffmpeg_available() and source_format in SUPPORTED_AUDIO_FORMATS:
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
        try:
            convert_audio_file(
                temp_source_path, output_path, target_format,
                timeout=max(240, timeout * 8),
            )
        except Exception:
            _cleanup_paths(temp_source_path, output_path)
            raise
        temp_source_path.unlink(missing_ok=True)
        if cancel_checker and cancel_checker():
            _cleanup_paths(output_path)
            raise DownloadCanceled()

    emit_stage("tagging")
    if tags:
        # Tag writing must never fail an already-completed download.
        try:
            write_audio_tags(
                output_path,
                title=tags.get("title") or "",
                artist=tags.get("artist"),
                album=tags.get("album"),
                cover_url=tags.get("cover_url"),
            )
        except Exception:
            logger.warning("Failed to write audio tags. song_id=%s", song_id, exc_info=True)
    if download_lyric:
        emit_stage("lyrics")
        from music_fetch.api import fetch_lyric
        from music_fetch.audio import merge_bilingual_lyric, save_lyric_file, embed_lyric_tag
        try:
            lyric_result = fetch_lyric(song_id, timeout=timeout)
            if lyric_result.lyric:
                if lyric_mode == "translation" and lyric_result.translated_lyric:
                    lyric_text = lyric_result.translated_lyric
                elif lyric_mode == "bilingual":
                    lyric_text = merge_bilingual_lyric(lyric_result.lyric, lyric_result.translated_lyric)
                else:
                    lyric_text = lyric_result.lyric
                save_lyric_file(output_path, lyric_text)
                embed_lyric_tag(output_path, lyric_text)
        except Exception:
            logger.warning("Failed to download lyric. song_id=%s", song_id, exc_info=True)
    file_size = output_path.stat().st_size if output_path.exists() else 0
    logger.info(
        "Download pipeline completed. song_id=%s output=%s size=%s",
        song_id, output_path, file_size,
    )
    return DownloadPipelineResult(
        output_path=output_path, file_size=file_size,
        candidate=selected, source_format=source_format,
    )


# Containers that can hold artwork; anything else skips the cover download.
COVER_SUPPORTED_SUFFIXES = (".mp3", ".m4a", ".mp4", ".flac")


def _detect_image_mime(data: bytes) -> str:
    """Sniff the image container so players get a truthful MIME type."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _download_cover(cover_url: str, timeout: int = 10) -> tuple[bytes, str]:
    from urllib import request

    req = request.Request(cover_url, headers={"User-Agent": "Mozilla/5.0"})
    with open_url(req, timeout=timeout) as resp:
        data = resp.read()
    return data, _detect_image_mime(data)


def _embed_cover(output_path: Path, cover_data: bytes, mime: str) -> bool:
    """Attach cover art to MP3/M4A/FLAC; False when the target cannot hold it."""
    suffix = output_path.suffix.lower()
    if suffix == ".mp3":
        from mutagen.id3 import APIC, ID3
        from mutagen.mp3 import MP3

        mp3 = MP3(str(output_path), ID3=ID3)
        if mp3.tags is None:  # pragma: no cover - ID3=ID3 always builds tags
            mp3.add_tags()
        for key in [key for key in mp3.tags.keys() if key.startswith("APIC")]:
            del mp3.tags[key]  # never stack duplicates across retries
        mp3.tags.add(APIC(encoding=3, mime=mime, type=3, desc="Cover", data=cover_data))
        mp3.save()
        return True
    if suffix in (".m4a", ".mp4"):
        from mutagen.mp4 import MP4, MP4Cover

        if mime == "image/png":
            image_format = MP4Cover.FORMAT_PNG
        elif mime == "image/jpeg":
            image_format = MP4Cover.FORMAT_JPEG
        else:
            # MP4Cover carries JPEG or PNG only.
            logger.debug("Unsupported cover MIME for MP4. mime=%s path=%s", mime, output_path)
            return False
        mp4 = MP4(str(output_path))
        if mp4.tags is None:
            mp4.add_tags()
        mp4_tags = mp4.tags
        if mp4_tags is None:  # pragma: no cover - add_tags always creates the dict
            return False
        mp4_tags["covr"] = [MP4Cover(cover_data, imageformat=image_format)]
        mp4.save()
        return True
    if suffix == ".flac":
        from mutagen.flac import FLAC, Picture

        flac = FLAC(str(output_path))
        picture = Picture()
        picture.type = 3  # front cover
        picture.mime = mime
        picture.desc = "Cover"
        picture.data = cover_data
        flac.clear_pictures()  # a re-download must not stack duplicates
        flac.add_picture(picture)
        flac.save()
        return True
    return False


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
        from mutagen.id3 import TIT2, TPE1, TALB
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

        # Embed cover art where the container supports it.
        if cover_url and output_path.suffix.lower() in COVER_SUPPORTED_SUFFIXES:
            try:
                cover_data, mime = _download_cover(cover_url)
                if cover_data and _embed_cover(output_path, cover_data, mime):
                    logger.info(
                        "Cover art embedded. output=%s mime=%s bytes=%s",
                        output_path, mime, len(cover_data),
                    )
            except Exception:
                logger.debug("Failed to embed cover art. output=%s", output_path, exc_info=True)

    except Exception:
        logger.debug("Failed to write audio tags. output=%s", output_path, exc_info=True)


def _cleanup_paths(*paths: Path) -> None:
    for path in paths:
        if path.exists():
            path.unlink(missing_ok=True)
