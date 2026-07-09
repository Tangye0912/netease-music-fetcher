"""
Audio download and format conversion.

Orchestrates the actual media stream download (with retry, header rotation,
outer-URL fallback) and ffmpeg-based audio transcoding.  Depends only on
_api for data classes and API functions — no GUI dependency.
"""

from __future__ import annotations

__all__ = [
    "sanitize_filename", "dedupe_path", "resolve_output_path",
    "infer_audio_format_from_url", "is_ffmpeg_available", "convert_audio_file",
    "download_audio", "download_audio_with_progress", "download_song_with_fallback",
    "prioritize_candidates_by_format", "fetch_outer_media_url",
    "SUPPORTED_GUI_AUDIO_FORMATS",
]

import re
import shutil
import time
import functools
import subprocess
from pathlib import Path
from typing import Optional
from urllib import error, parse, request

from music_fetch.api import (
    DownloadCanceled,
    ErrorCode,
    MusicFetchError,
    OUTER_MEDIA_URL_API,
    USER_AGENT,
    CancelChecker,
    PauseChecker,
    PlayableCandidate,
    ProgressCallback,
    SUPPORTED_GUI_AUDIO_FORMATS,
    fetch_playable_candidates,
    logger,
    normalize_media_url,
)


INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')


# ── Filename helpers ─────────────────────────────────────────────

def sanitize_filename(name: str) -> str:
    cleaned = INVALID_FILENAME_CHARS.sub("_", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "song"


def dedupe_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for idx in range(1, 10000):
        candidate = parent / f"{stem}_{idx}{suffix}"
        if not candidate.exists():
            return candidate
    raise MusicFetchError(ErrorCode.DOWNLOAD_FAILED, "Could not allocate an output filename.")


def resolve_output_path(out_dir: Path, song_id: str, song_name: Optional[str] = None, rename: Optional[str] = None, out_format: str = "mp3") -> Path:
    raw_name = rename if rename else (f"{song_name}-{song_id}" if song_name else f"song-{song_id}")
    final_name = sanitize_filename(raw_name)
    return dedupe_path(out_dir / f"{final_name}.{out_format}")


# ── Format detection / conversion ────────────────────────────────

def infer_audio_format_from_url(media_url: str) -> Optional[str]:
    suffix = Path(parse.urlparse(media_url).path).suffix.lower().lstrip(".")
    if suffix in SUPPORTED_GUI_AUDIO_FORMATS:
        return suffix
    if suffix == "mp4":
        return "m4a"
    return None


@functools.lru_cache(maxsize=1)
def is_ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def invalidate_ffmpeg_cache() -> None:
    """Clear the cached ffmpeg availability check (e.g. after install)."""
    is_ffmpeg_available.cache_clear()


def convert_audio_file(input_path: Path, output_path: Path, target_format: str, timeout: int = 240) -> None:
    fmt = target_format.lower().strip()
    if fmt not in SUPPORTED_GUI_AUDIO_FORMATS:
        raise MusicFetchError(ErrorCode.UNSUPPORTED_FORMAT, f"Unsupported output format: {fmt}")
    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise MusicFetchError(ErrorCode.CONVERT_TOOL_MISSING, "ffmpeg is not installed. Please install ffmpeg first.")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    base_cmd = [ffmpeg_bin, "-y", "-i", str(input_path), "-vn"]
    if fmt == "mp3":
        cmd = base_cmd + ["-codec:a", "libmp3lame", "-q:a", "2", str(output_path)]
    elif fmt == "m4a":
        cmd = base_cmd + ["-codec:a", "aac", "-b:a", "192k", str(output_path)]
    elif fmt == "aac":
        cmd = base_cmd + ["-codec:a", "aac", "-b:a", "192k", str(output_path)]
    elif fmt == "wav":
        cmd = base_cmd + ["-codec:a", "pcm_s16le", str(output_path)]
    elif fmt == "flac":
        cmd = base_cmd + ["-codec:a", "flac", str(output_path)]
    else:
        raise MusicFetchError(ErrorCode.UNSUPPORTED_FORMAT, f"Unsupported output format: {fmt}")
    logger.info("Start audio conversion. input=%s output=%s format=%s", input_path, output_path, fmt)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        raise MusicFetchError(ErrorCode.CONVERT_FAILED, f"Audio conversion timed out after {timeout}s.")
    if proc.returncode != 0:
        stderr_preview = (proc.stderr or "").strip().splitlines()
        preview = stderr_preview[-1] if stderr_preview else "unknown conversion error"
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        raise MusicFetchError(ErrorCode.CONVERT_FAILED, f"Failed to convert audio to {fmt}: {preview}")
    logger.info("Audio conversion completed. output=%s format=%s", output_path, fmt)


# ── Download ─────────────────────────────────────────────────────

def download_audio(media_url: str, output_path: Path, timeout: int) -> None:
    _download_audio_stream(media_url, output_path, timeout, progress_callback=None, cancel_checker=None, cookie="")


def download_audio_with_progress(media_url: str, output_path: Path, timeout: int, progress_callback: Optional[ProgressCallback] = None, cancel_checker: Optional[CancelChecker] = None, pause_checker: Optional[PauseChecker] = None, cookie: str = "") -> None:
    _download_audio_stream(media_url, output_path, timeout, progress_callback=progress_callback, cancel_checker=cancel_checker, pause_checker=pause_checker, cookie=cookie)


def download_song_with_fallback(song_id: str, cookie: str, output_path: Path, timeout: int, prefer_format: Optional[str] = None, progress_callback: Optional[ProgressCallback] = None, cancel_checker: Optional[CancelChecker] = None, pause_checker: Optional[PauseChecker] = None) -> PlayableCandidate:
    candidates = fetch_playable_candidates(song_id, cookie, timeout=timeout)
    if prefer_format:
        candidates = prioritize_candidates_by_format(candidates, prefer_format=prefer_format)
    last_403: Optional[MusicFetchError] = None
    outer_available = False
    for idx, candidate in enumerate(candidates, start=1):
        logger.info("Trying candidate download. song_id=%s candidate=%s/%s level=%s encode=%s", song_id, idx, len(candidates), candidate.level, candidate.encode_type)
        try:
            _download_audio_stream(candidate.media_url, output_path, timeout, progress_callback=progress_callback, cancel_checker=cancel_checker, pause_checker=pause_checker, cookie=cookie)
            return candidate
        except DownloadCanceled:
            raise
        except MusicFetchError as err:
            if err.code == "DOWNLOAD_FAILED" and "HTTP 403" in err.message:
                last_403 = err
                logger.warning("Candidate rejected by CDN with 403. song_id=%s level=%s encode=%s", song_id, candidate.level, candidate.encode_type)
                continue
            raise
    logger.info("Trying outer-url fallback download. song_id=%s", song_id)
    outer_url = fetch_outer_media_url(song_id, timeout=timeout)
    if outer_url:
        outer_available = True
        try:
            _download_audio_stream(outer_url, output_path, timeout, progress_callback=progress_callback, cancel_checker=cancel_checker, pause_checker=pause_checker, cookie="")
            logger.info("Outer-url fallback download succeeded. song_id=%s", song_id)
            return PlayableCandidate(media_url=outer_url, duration_ms=None, level="outer", encode_type=(infer_audio_format_from_url(outer_url) or "unknown"))
        except MusicFetchError as err:
            logger.warning("Outer-url fallback failed. song_id=%s code=%s message=%s", song_id, err.code, err.message)
            last_403 = err
    else:
        logger.warning("Outer-url fallback is unavailable for song. song_id=%s", song_id)
    if last_403:
        if not outer_available:
            raise MusicFetchError(ErrorCode.SONG_UNAVAILABLE, "Playable resources are blocked by CDN, and outer-url fallback is unavailable.") from last_403
        raise MusicFetchError(ErrorCode.DOWNLOAD_FAILED, "All playable candidates were rejected with HTTP 403 (including outer-url fallback).") from last_403
    raise MusicFetchError(ErrorCode.DOWNLOAD_FAILED, "Failed to download all playable candidates.")


def prioritize_candidates_by_format(candidates: list[PlayableCandidate], prefer_format: str) -> list[PlayableCandidate]:
    normalized = (prefer_format or "").strip().lower()
    if not normalized:
        return candidates
    preferred: tuple[str, ...]
    if normalized == "m4a":
        preferred = ("m4a", "aac")
    elif normalized == "aac":
        preferred = ("aac", "m4a")
    else:
        preferred = (normalized,)

    def candidate_key(candidate: PlayableCandidate) -> tuple[int, int]:
        fmt = infer_audio_format_from_url(candidate.media_url)
        if not fmt:
            encode = (candidate.encode_type or "").strip().lower()
            if encode in {"aac", "mp4"}:
                fmt = "m4a"
            elif encode in {"mp3", "wav", "flac", "m4a"}:
                fmt = encode
        if fmt in preferred:
            return (0, preferred.index(fmt))
        return (1, 0)

    sorted_candidates = sorted(candidates, key=candidate_key)
    logger.info("Candidates reordered by preferred format. prefer=%s order=%s", normalized, [f"{c.level}:{c.encode_type}" for c in sorted_candidates])
    return sorted_candidates


def fetch_outer_media_url(song_id: str, timeout: int = 20) -> Optional[str]:
    url = OUTER_MEDIA_URL_API.format(song_id=song_id)
    req = request.Request(url, headers={"User-Agent": USER_AGENT, "Referer": "https://music.163.com/", "Accept": "*/*"}, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            final_url = resp.geturl()
            parsed = parse.urlparse(final_url)
            if parsed.netloc.lower().endswith(".music.126.net"):
                logger.info("Outer-url resolved. song_id=%s media_host=%s", song_id, parsed.netloc)
                return normalize_media_url(final_url)
            logger.warning("Outer-url did not redirect to CDN host. song_id=%s final=%s", song_id, final_url)
            return None
    except error.HTTPError as http_err:
        logger.warning("Outer-url request failed. song_id=%s status=%s", song_id, http_err.code)
        return None
    except error.URLError as url_err:
        logger.warning("Outer-url network error. song_id=%s reason=%s", song_id, url_err.reason)
        return None


def _build_download_attempt_headers(cookie: str) -> list[dict[str, str]]:
    base_user_agent = USER_AGENT
    attempts: list[dict[str, str]] = [
        {"User-Agent": base_user_agent, "Referer": "https://music.163.com/", "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8", "Range": "bytes=0-", "Sec-Fetch-Dest": "audio", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Site": "cross-site"},
        {"User-Agent": base_user_agent, "Referer": "https://y.music.163.com/", "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8", "Range": "bytes=0-", "Sec-Fetch-Dest": "audio", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Site": "cross-site"},
        {"User-Agent": base_user_agent, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8", "Range": "bytes=0-"},
    ]
    if cookie:
        attempts.append({"User-Agent": base_user_agent, "Referer": "https://music.163.com/", "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8", "Range": "bytes=0-", "Cookie": cookie, "Sec-Fetch-Dest": "audio", "Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Site": "cross-site"})
    return attempts


def _url_for_log(url: str) -> str:
    parsed = parse.urlparse(url)
    safe_query = []
    for part in parsed.query.split("&"):
        if not part:
            continue
        key = part.split("=", 1)[0]
        if key.lower() in {"token", "authsecret"}:
            safe_query.append(f"{key}=***")
        else:
            safe_query.append(part)
    query = "&".join(safe_query)
    return parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, query, parsed.fragment))


def _candidate_media_urls(url: str) -> list[str]:
    normalized = normalize_media_url(url)
    candidates = [normalized]
    parsed = parse.urlparse(normalized)
    if parsed.scheme == "https" and parsed.netloc.lower().endswith(".music.126.net"):
        fallback_http = parse.urlunparse(("http", parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
        candidates.append(fallback_http)
    return candidates


def _download_audio_stream(media_url: str, output_path: Path, timeout: int, progress_callback: Optional[ProgressCallback], cancel_checker: Optional[CancelChecker], pause_checker: Optional[PauseChecker] = None, cookie: str = "") -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_name(f"{output_path.name}.part")

    # Resume from partial download if .part file exists
    resume_offset = 0
    if tmp_path.exists():
        resume_offset = tmp_path.stat().st_size
        if resume_offset > 0:
            logger.info("Resuming partial download. output=%s offset=%s", output_path, resume_offset)

    attempts = _build_download_attempt_headers(cookie)
    media_urls = _candidate_media_urls(media_url)
    media_host = parse.urlparse(media_urls[0]).netloc
    logger.info("Starting media download. output=%s media_host=%s attempts=%s media_url=%s variants=%s resume_offset=%s", output_path, media_host, len(attempts), _url_for_log(media_urls[0]), len(media_urls), resume_offset)
    last_403_error: Optional[error.HTTPError] = None
    last_network_error: Optional[error.URLError] = None
    total_attempts = len(attempts) * len(media_urls)
    attempt_no = 0
    for candidate_url in media_urls:
        for headers in attempts:
            attempt_no += 1
            downloaded = resume_offset
            total_bytes: Optional[int] = None

            # Apply Range header for resume
            if resume_offset > 0:
                headers = dict(headers)
                headers["Range"] = f"bytes={resume_offset}-"
                logger.info("Resume Range header set. offset=%s", resume_offset)
            else:
                headers = dict(headers)

            if progress_callback:
                progress_callback(downloaded, None)
            req = request.Request(candidate_url, headers=headers, method="GET")
            logger.info("Download attempt started. attempt=%s/%s scheme=%s referer=%s cookie=%s offset=%s", attempt_no, total_attempts, parse.urlparse(candidate_url).scheme, headers.get("Referer", "none"), "yes" if "Cookie" in headers else "no", resume_offset)
            try:
                with request.urlopen(req, timeout=timeout) as resp:
                    # If we requested a Range but server returns 200 (full content),
                    # don't append — overwrite from the beginning.
                    status_code = getattr(resp, "status", None) or getattr(resp, "code", 0)
                    if resume_offset > 0 and status_code != 206:
                        logger.warning("Server ignored Range request (status=%s), restarting from scratch. output=%s", status_code, output_path)
                        resume_offset = 0
                        downloaded = 0
                    content_length = getattr(resp, "headers", {}).get("Content-Length")
                    if content_length and content_length.isdigit():
                        total_bytes = int(content_length) + resume_offset
                    file_mode = "ab" if resume_offset > 0 else "wb"
                    with tmp_path.open(file_mode) as file_obj:
                        while True:
                            if cancel_checker and cancel_checker():
                                raise DownloadCanceled()
                            if pause_checker and pause_checker():
                                # Block until resumed or canceled
                                while pause_checker is not None and pause_checker():
                                    time.sleep(0.1)
                                    if cancel_checker and cancel_checker():
                                        raise DownloadCanceled()
                            chunk = resp.read(64 * 1024)
                            if not chunk:
                                break
                            file_obj.write(chunk)
                            downloaded += len(chunk)
                            if progress_callback:
                                progress_callback(downloaded, total_bytes)
                tmp_path.replace(output_path)
                if progress_callback:
                    progress_callback(downloaded, total_bytes)
                logger.info("Media download finished. output=%s downloaded_bytes=%s total_bytes=%s attempt=%s", output_path, downloaded, total_bytes if total_bytes is not None else "unknown", attempt_no)
                return
            except error.HTTPError as http_err:
                # Clean up .part on any HTTP error — a stale partial file
                # with an outdated offset would corrupt the next download.
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                body_preview = ""
                try:
                    body_preview = http_err.read(200).decode("utf-8", errors="ignore").strip()
                except (UnicodeDecodeError, OSError):
                    body_preview = ""
                logger.warning("Download attempt HTTP error. attempt=%s/%s status=%s scheme=%s referer=%s cookie=%s body=%s", attempt_no, total_attempts, http_err.code, parse.urlparse(candidate_url).scheme, headers.get("Referer", "none"), "yes" if "Cookie" in headers else "no", body_preview[:120])
                if http_err.code == 403:
                    last_403_error = http_err
                    # .part was deleted above; reset resume_offset so the next
                    # attempt starts fresh (wb mode, no Range header).
                    resume_offset = 0
                    continue
                raise MusicFetchError(ErrorCode.DOWNLOAD_FAILED, f"Media request failed: HTTP {http_err.code}.") from http_err
            except error.URLError as url_err:
                if resume_offset == 0 and tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                logger.warning("Download attempt network error. attempt=%s/%s reason=%s", attempt_no, total_attempts, url_err.reason)
                last_network_error = url_err
                continue
            except DownloadCanceled:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                if output_path.exists():
                    output_path.unlink(missing_ok=True)
                logger.info("Media download canceled, partial file removed. output=%s", output_path)
                raise
    if last_403_error is not None:
        logger.error("All download attempts failed with 403. output=%s media_host=%s", output_path, media_host)
        raise MusicFetchError(ErrorCode.DOWNLOAD_FAILED, "Media request failed: HTTP 403. Possible VIP/region/copyright restriction or anti-hotlink blocking.") from last_403_error
    if last_network_error is not None:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        logger.error("All download attempts failed with network errors. output=%s media_host=%s", output_path, media_host)
        raise MusicFetchError(ErrorCode.NETWORK_ERROR, f"Network error: {last_network_error.reason}") from last_network_error
    raise MusicFetchError(ErrorCode.DOWNLOAD_FAILED, "Media download failed after retries.")


# ── Lyrics ──────────────────────────────────────────────────────────

def save_lyric_file(output_path: Path, lyric: str) -> None:
    """Save lyrics as a .lrc file alongside the audio file."""
    if not lyric.strip():
        return
    lrc_path = output_path.with_suffix(".lrc")
    lrc_path.write_text(lyric, encoding="utf-8")
    logger.info("Lyric file saved. path=%s", lrc_path)


def embed_lyric_tag(output_path: Path, lyric: str) -> None:
    """Embed lyrics into the audio file's metadata tags (USLT frame for ID3)."""
    if not lyric.strip():
        return
    try:
        from mutagen.id3 import ID3, USLT
        from mutagen.mp3 import MP3
    except ImportError:
        logger.debug("mutagen not installed, skipping lyric embedding.")
        return

    suffix = output_path.suffix.lower()
    if suffix == ".mp3":
        try:
            audio = MP3(str(output_path), ID3=ID3)
            # Remove existing lyrics if any
            audio.tags.delall("USLT")
            audio.tags.add(
                USLT(encoding=3, lang="eng", desc="", text=lyric)
            )
            audio.save()
            logger.info("Lyric embedded in MP3 tags. path=%s", output_path)
        except (OSError, ValueError, KeyError, TypeError):
            logger.debug("Failed to embed lyric in MP3. path=%s", output_path, exc_info=True)
    elif suffix in (".m4a", ".aac", ".mp4"):
        try:
            from mutagen.mp4 import MP4
            audio = MP4(str(output_path))  # type: ignore[assignment]
            audio["\xa9lyr"] = lyric
            audio.save()
            logger.info("Lyric embedded in M4A tags. path=%s", output_path)
        except (OSError, ValueError, KeyError, TypeError):
            logger.debug("Failed to embed lyric in M4A. path=%s", output_path, exc_info=True)
    elif suffix in (".flac", ".wav"):
        try:
            from mutagen.flac import FLAC
            audio = FLAC(str(output_path))  # type: ignore[assignment]
            audio["lyrics"] = lyric
            audio.save()
            logger.info("Lyric embedded in FLAC tags. path=%s", output_path)
        except (OSError, ValueError, KeyError, TypeError):
            logger.debug("Failed to embed lyric in FLAC. path=%s", output_path, exc_info=True)
