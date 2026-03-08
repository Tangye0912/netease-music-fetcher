#!/usr/bin/env python3
"""CLI utility to fetch a playable NetEase Cloud Music track by song URL."""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple
from urllib import error, parse, request

from app_logging import default_log_path, get_logger, mask_value, setup_logging
from app_settings import SUPPORTED_AUDIO_FORMATS

DEFAULT_OUT_DIR = "downloads"
DEFAULT_COOKIE_FILE = "~/.config/music-fetch/cookies.txt"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
PLAYER_URL_API = "https://music.163.com/api/song/enhance/player/url/v1"
SONG_DETAIL_API = "https://music.163.com/api/song/detail"
ACCOUNT_STATUS_API = "https://music.163.com/api/nuser/account/get"
OUTER_MEDIA_URL_API = "https://music.163.com/song/media/outer/url?id={song_id}.mp3"
INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|]+')
URL_IN_TEXT_PATTERN = re.compile(r"https?://[^\s]+", re.IGNORECASE)
TRAILING_URL_PUNCTUATION = ")]}>,.;!?\"'，。；：、）】》"
SHORT_LINK_HOSTS = {"163cn.tv", "www.163cn.tv"}
PLAYABLE_REQUEST_PROFILES: list[tuple[str, str]] = [
    ("standard", "mp3"),
    ("standard", "aac"),
    ("standard", "mp4"),
    ("higher", "aac"),
    ("exhigh", "aac"),
]
logger = get_logger("music_fetch.core")
SUPPORTED_GUI_AUDIO_FORMATS = SUPPORTED_AUDIO_FORMATS


class MusicFetchError(Exception):
    """Standardized error with stable code and human-readable message."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class DownloadResult:
    song_id: str
    output_path: Path
    size_bytes: int
    duration_ms: Optional[int]


@dataclass
class SongDetectionResult:
    song_id: str
    song_name: Optional[str]
    duration_ms: Optional[int]
    media_url: Optional[str]
    can_download: bool
    unavailable_reason: Optional[str]


@dataclass
class AccountProfile:
    user_id: Optional[int]
    nickname: str
    avatar_url: str
    vip_type: int
    is_vip: bool


@dataclass
class PlayableCandidate:
    media_url: str
    duration_ms: Optional[int]
    level: str
    encode_type: str


ProgressCallback = Callable[[int, Optional[int]], None]
CancelChecker = Callable[[], bool]


def parse_song_id(value: str) -> str:
    value = value.strip()
    if value.isdigit():
        logger.info("Parsed numeric song id directly: %s", value)
        return value

    url = extract_url_from_input(value)
    logger.info("Parsing input to song id. extracted_url=%s", bool(url))
    parsed = parse.urlparse(url if url else value)
    host = parsed.netloc.lower()
    if host and not is_netease_music_host(host) and host not in SHORT_LINK_HOSTS:
        raise MusicFetchError(
            "INVALID_URL",
            "Only music.163.com or 163cn.tv links are supported.",
        )

    target_url = url if url else value
    if host in SHORT_LINK_HOSTS:
        logger.info("Resolving short link host=%s", host)
        target_url = resolve_short_url(target_url, timeout=15)
        parsed = parse.urlparse(target_url)
        host = parsed.netloc.lower()
        if host and not is_netease_music_host(host):
            raise MusicFetchError(
                "INVALID_URL",
                "Could not resolve short link to a music.163.com song URL.",
            )

    query = parse.parse_qs(parsed.query)
    song_id = _pick_first_digit(query.get("id"))
    if song_id:
        return song_id

    # Supports URLs like https://music.163.com/#/song?id=123456
    if parsed.fragment:
        frag_query = parsed.fragment.split("?", 1)[1] if "?" in parsed.fragment else ""
        if frag_query:
            frag_map = parse.parse_qs(frag_query)
            song_id = _pick_first_digit(frag_map.get("id"))
            if song_id:
                return song_id
        match = re.search(r"id=(\d+)", parsed.fragment)
        if match:
            return match.group(1)

    match = re.search(r"/song/(\d+)", parsed.path)
    if match:
        return match.group(1)

    match = re.search(r"id=(\d+)", target_url)
    if match:
        logger.info("Parsed song id from fallback pattern. song_id=%s", match.group(1))
        return match.group(1)

    raise MusicFetchError("INVALID_URL", "Could not parse song id from the provided URL.")


def extract_url_from_input(value: str) -> Optional[str]:
    match = URL_IN_TEXT_PATTERN.search(value)
    if not match:
        return None
    candidate = match.group(0).rstrip(TRAILING_URL_PUNCTUATION)
    return candidate if candidate.startswith(("http://", "https://")) else None


def is_netease_music_host(host: str) -> bool:
    host = host.lower().split(":")[0]
    return host == "music.163.com" or host.endswith(".music.163.com")


def resolve_short_url(url: str, timeout: int = 15) -> str:
    req = request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            resolved = resp.geturl()
            logger.info("Resolved short link. from=%s to=%s", url, resolved)
            return resolved
    except error.HTTPError as http_err:
        redirected = http_err.geturl() if hasattr(http_err, "geturl") else ""
        if redirected:
            logger.warning("Short link returned HTTP error but redirected. from=%s to=%s", url, redirected)
            return redirected
        logger.error("Failed to resolve short link. url=%s status=%s", url, http_err.code)
        raise MusicFetchError("NETWORK_ERROR", f"Failed to resolve short link: HTTP {http_err.code}") from http_err
    except error.URLError as url_err:
        logger.error("Short link resolve network error. url=%s reason=%s", url, url_err.reason)
        raise MusicFetchError("NETWORK_ERROR", f"Network error: {url_err.reason}") from url_err


def _pick_first_digit(values: Optional[list[str]]) -> Optional[str]:
    if not values:
        return None
    for value in values:
        if value and value.isdigit():
            return value
    return None


def load_cookie(cookie_file: Path) -> str:
    logger.info("Loading cookie file from %s", cookie_file)
    if not cookie_file.exists():
        raise MusicFetchError(
            "AUTH_EXPIRED",
            f"Cookie file not found: {cookie_file}. Please export a valid MUSIC_U cookie.",
        )

    cookie = normalize_cookie(cookie_file.read_text(encoding="utf-8"))
    if not cookie:
        raise MusicFetchError("AUTH_EXPIRED", "Cookie file is empty. Please refresh your cookie.")
    if "MUSIC_U=" not in cookie:
        raise MusicFetchError(
            "AUTH_EXPIRED",
            "Cookie file does not include MUSIC_U. Please re-export from browser.",
        )
    fields = parse_cookie_fields(cookie)
    logger.info(
        "Cookie loaded. has_music_u=%s has_csrf=%s music_u_mask=%s",
        "MUSIC_U" in fields,
        "__csrf" in fields,
        mask_value(fields.get("MUSIC_U", "")),
    )
    return cookie


def extract_csrf(cookie: str) -> str:
    return parse_cookie_fields(cookie).get("__csrf", "")


def parse_cookie_fields(cookie: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for part in cookie.split(";"):
        stripped = part.strip()
        if not stripped or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        fields[key] = value.strip()
    return fields


def normalize_cookie(raw_cookie: str) -> str:
    fields = parse_cookie_fields(raw_cookie)
    if not fields:
        return ""
    return "; ".join(f"{key}={value}" for key, value in fields.items())


def build_cookie_string(music_u: str, csrf: str = "") -> str:
    music_u = music_u.strip()
    csrf = csrf.strip()
    if not music_u:
        return ""
    segments = [f"MUSIC_U={music_u}"]
    if csrf:
        segments.append(f"__csrf={csrf}")
    return "; ".join(segments)


def perform_json_post(
    url: str, payload: dict[str, str], headers: dict[str, str], timeout: int
) -> Tuple[int, dict]:
    encoded = parse.urlencode(payload).encode("utf-8")
    req = request.Request(url, data=encoded, headers=headers, method="POST")
    status, body = _perform_request(req, timeout=timeout)
    return status, _decode_json(body)


def perform_json_get(url: str, headers: dict[str, str], timeout: int) -> Tuple[int, dict]:
    req = request.Request(url, headers=headers, method="GET")
    status, body = _perform_request(req, timeout=timeout)
    return status, _decode_json(body)


def _perform_request(req: request.Request, timeout: int) -> Tuple[int, bytes]:
    logger.debug("HTTP request. method=%s url=%s", req.get_method(), req.full_url)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", resp.getcode())
            logger.debug("HTTP response. status=%s url=%s", status, req.full_url)
            return status, resp.read()
    except error.HTTPError as http_err:
        body = http_err.read() if hasattr(http_err, "read") else b""
        logger.warning("HTTP error. status=%s url=%s", http_err.code, req.full_url)
        return http_err.code, body
    except error.URLError as url_err:
        logger.error("URL error. url=%s reason=%s", req.full_url, url_err.reason)
        raise MusicFetchError("NETWORK_ERROR", f"Network error: {url_err.reason}") from url_err


def _decode_json(body: bytes) -> dict:
    try:
        decoded = body.decode("utf-8")
        return json.loads(decoded) if decoded else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise MusicFetchError("NETWORK_ERROR", "Unexpected API response (invalid JSON).") from err


def check_login_status(cookie: str, timeout: int = 10) -> bool:
    if "MUSIC_U=" not in cookie:
        logger.info("Login status check failed: no MUSIC_U in cookie.")
        return False
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://music.163.com/",
        "Cookie": cookie,
    }
    status, body = perform_json_get(ACCOUNT_STATUS_API, headers, timeout=timeout)
    if status in (401, 403):
        return False
    code = body.get("code")
    if code in (301, 302, 401, 403):
        return False
    has_account = bool(body.get("account") or body.get("profile"))
    is_valid = status == 200 and code == 200 and has_account
    logger.info("Login status checked. status=%s code=%s valid=%s", status, code, is_valid)
    return is_valid


def fetch_account_profile(cookie: str, timeout: int = 10) -> AccountProfile:
    if "MUSIC_U=" not in cookie:
        raise MusicFetchError("AUTH_EXPIRED", "Login cookie missing MUSIC_U.")
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://music.163.com/",
        "Cookie": cookie,
    }
    status, body = perform_json_get(ACCOUNT_STATUS_API, headers, timeout=timeout)
    code = body.get("code")
    if status in (401, 403) or code in (301, 302, 401, 403):
        raise MusicFetchError("AUTH_EXPIRED", "Login state expired. Please login again.")
    if status != 200 or code != 200:
        raise MusicFetchError("NETWORK_ERROR", f"Unexpected account API response: status={status}, code={code}")

    profile = body.get("profile") or {}
    account = body.get("account") or {}
    nickname = str(profile.get("nickname") or account.get("userName") or "未命名用户")
    avatar_url = str(profile.get("avatarUrl") or "")

    vip_raw = profile.get("vipType")
    if not isinstance(vip_raw, int):
        vip_raw = account.get("vipType")
    vip_type = vip_raw if isinstance(vip_raw, int) else 0
    is_vip = vip_type > 0

    user_id_raw = profile.get("userId")
    if not isinstance(user_id_raw, int):
        user_id_raw = account.get("id")
    user_id = user_id_raw if isinstance(user_id_raw, int) else None

    logger.info(
        "Fetched account profile. user_id=%s nickname=%s vip_type=%s",
        user_id,
        nickname,
        vip_type,
    )
    return AccountProfile(
        user_id=user_id,
        nickname=nickname,
        avatar_url=avatar_url,
        vip_type=vip_type,
        is_vip=is_vip,
    )


def fetch_playable_candidates(song_id: str, cookie: str, timeout: int) -> list[PlayableCandidate]:
    csrf = extract_csrf(cookie)
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://music.163.com/",
        "Origin": "https://music.163.com",
        "Content-Type": "application/x-www-form-urlencoded",
        "Cookie": cookie,
    }
    last_network_message: Optional[str] = None
    saw_song_unavailable = False
    candidates: list[PlayableCandidate] = []
    seen_urls: set[str] = set()

    for level, encode_type in PLAYABLE_REQUEST_PROFILES:
        payload = {
            "ids": json.dumps([int(song_id)]),
            "level": level,
            "encodeType": encode_type,
            "csrf_token": csrf,
        }
        status, body = perform_json_post(PLAYER_URL_API, payload, headers, timeout=timeout)
        logger.info(
            "Requested playable url. song_id=%s level=%s encode=%s status=%s api_code=%s",
            song_id,
            level,
            encode_type,
            status,
            body.get("code"),
        )

        if status in (401, 403):
            raise MusicFetchError("AUTH_EXPIRED", "Login state expired. Please refresh cookie.")
        if status >= 500:
            last_network_message = f"Server error from NetEase: HTTP {status}."
            continue

        code = body.get("code")
        if code in (301, 302, 401, 403):
            raise MusicFetchError("AUTH_EXPIRED", "Login state expired. Please refresh cookie.")
        if code != 200:
            last_network_message = str(body.get("message") or f"Unexpected API code={code}")
            continue

        data = body.get("data") or []
        if not data:
            saw_song_unavailable = True
            continue

        media = data[0]
        media_url = media.get("url")
        if not media_url:
            saw_song_unavailable = True
            logger.warning("Playable url empty. song_id=%s level=%s encode=%s", song_id, level, encode_type)
            continue

        media_url = normalize_media_url(media_url)
        if media_url in seen_urls:
            continue
        seen_urls.add(media_url)
        media_host = parse.urlparse(media_url).netloc
        logger.info(
            "Playable url resolved. song_id=%s level=%s encode=%s media_host=%s duration_ms=%s",
            song_id,
            level,
            encode_type,
            media_host,
            media.get("time"),
        )
        candidates.append(
            PlayableCandidate(
                media_url=media_url,
                duration_ms=media.get("time"),
                level=level,
                encode_type=encode_type,
            )
        )

    if candidates:
        return candidates

    if saw_song_unavailable:
        raise MusicFetchError(
            "SONG_UNAVAILABLE",
            "Song is unavailable (copyright/region/VIP restriction).",
        )
    if last_network_message:
        raise MusicFetchError("NETWORK_ERROR", last_network_message)
    raise MusicFetchError("NETWORK_ERROR", "Could not resolve playable media url.")


def fetch_playable_url(song_id: str, cookie: str, timeout: int) -> Tuple[str, Optional[int]]:
    candidates = fetch_playable_candidates(song_id, cookie, timeout=timeout)
    first = candidates[0]
    return first.media_url, first.duration_ms


def fetch_song_metadata(song_id: str, cookie: str, timeout: int) -> Tuple[Optional[str], Optional[int]]:
    headers = {
        "User-Agent": USER_AGENT,
        "Referer": "https://music.163.com/",
        "Cookie": cookie,
    }
    query = parse.urlencode({"ids": f"[{song_id}]"})
    url = f"{SONG_DETAIL_API}?{query}"
    try:
        status, body = perform_json_get(url, headers, timeout=timeout)
    except MusicFetchError:
        return None, None

    if status != 200 or body.get("code") != 200:
        return None, None

    songs = body.get("songs") or []
    if not songs:
        logger.warning("Song metadata not found. song_id=%s", song_id)
        return None, None

    song = songs[0]
    name = song.get("name")
    duration_ms = song.get("dt")
    if isinstance(name, str):
        name = name.strip() or None
    else:
        name = None
    if not isinstance(duration_ms, int):
        duration_ms = None
    return name, duration_ms


def detect_song(song_url: str, cookie: str, timeout: int = 20) -> SongDetectionResult:
    song_id = parse_song_id(song_url)
    logger.info("Detecting song by url. song_id=%s", song_id)
    song_name, meta_duration = fetch_song_metadata(song_id, cookie, timeout=timeout)

    try:
        media_url, media_duration = fetch_playable_url(song_id, cookie, timeout=timeout)
    except MusicFetchError as err:
        if err.code != "SONG_UNAVAILABLE":
            raise
        return SongDetectionResult(
            song_id=song_id,
            song_name=song_name,
            duration_ms=meta_duration,
            media_url=None,
            can_download=False,
            unavailable_reason=err.message,
        )

    duration = meta_duration if meta_duration is not None else media_duration
    return SongDetectionResult(
        song_id=song_id,
        song_name=song_name,
        duration_ms=duration,
        media_url=media_url,
        can_download=True,
        unavailable_reason=None,
    )


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
    raise MusicFetchError("DOWNLOAD_FAILED", "Could not allocate an output filename.")


def resolve_output_path(
    out_dir: Path,
    song_id: str,
    song_name: Optional[str] = None,
    rename: Optional[str] = None,
    out_format: str = "mp4",
) -> Path:
    raw_name = rename if rename else (f"{song_name}-{song_id}" if song_name else f"song-{song_id}")
    final_name = sanitize_filename(raw_name)
    return dedupe_path(out_dir / f"{final_name}.{out_format}")


def infer_audio_format_from_url(media_url: str) -> Optional[str]:
    suffix = Path(parse.urlparse(media_url).path).suffix.lower().lstrip(".")
    if suffix in SUPPORTED_GUI_AUDIO_FORMATS:
        return suffix
    if suffix == "mp4":
        return "m4a"
    return None


def is_ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg"))


def convert_audio_file(
    input_path: Path,
    output_path: Path,
    target_format: str,
    timeout: int = 240,
) -> None:
    fmt = target_format.lower().strip()
    if fmt not in SUPPORTED_GUI_AUDIO_FORMATS:
        raise MusicFetchError("UNSUPPORTED_FORMAT", f"Unsupported output format: {fmt}")

    ffmpeg_bin = shutil.which("ffmpeg")
    if not ffmpeg_bin:
        raise MusicFetchError("CONVERT_TOOL_MISSING", "ffmpeg is not installed. Please install ffmpeg first.")

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
        raise MusicFetchError("UNSUPPORTED_FORMAT", f"Unsupported output format: {fmt}")

    logger.info("Start audio conversion. input=%s output=%s format=%s", input_path, output_path, fmt)
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        stderr_preview = (proc.stderr or "").strip().splitlines()
        preview = stderr_preview[-1] if stderr_preview else "unknown conversion error"
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        raise MusicFetchError("CONVERT_FAILED", f"Failed to convert audio to {fmt}: {preview}")
    logger.info("Audio conversion completed. output=%s format=%s", output_path, fmt)


def download_audio(media_url: str, output_path: Path, timeout: int) -> None:
    _download_audio_stream(
        media_url,
        output_path,
        timeout,
        progress_callback=None,
        cancel_checker=None,
        cookie="",
    )


def download_audio_with_progress(
    media_url: str,
    output_path: Path,
    timeout: int,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_checker: Optional[CancelChecker] = None,
    cookie: str = "",
) -> None:
    _download_audio_stream(
        media_url,
        output_path,
        timeout,
        progress_callback=progress_callback,
        cancel_checker=cancel_checker,
        cookie=cookie,
    )


def download_song_with_fallback(
    song_id: str,
    cookie: str,
    output_path: Path,
    timeout: int,
    prefer_format: Optional[str] = None,
    progress_callback: Optional[ProgressCallback] = None,
    cancel_checker: Optional[CancelChecker] = None,
) -> PlayableCandidate:
    candidates = fetch_playable_candidates(song_id, cookie, timeout=timeout)
    if prefer_format:
        candidates = prioritize_candidates_by_format(candidates, prefer_format=prefer_format)
    last_403: Optional[MusicFetchError] = None
    outer_available = False
    # Try candidate URLs from best to lower quality. Some CDN links may be rejected with 403.
    for idx, candidate in enumerate(candidates, start=1):
        logger.info(
            "Trying candidate download. song_id=%s candidate=%s/%s level=%s encode=%s",
            song_id,
            idx,
            len(candidates),
            candidate.level,
            candidate.encode_type,
        )
        try:
            _download_audio_stream(
                candidate.media_url,
                output_path,
                timeout,
                progress_callback=progress_callback,
                cancel_checker=cancel_checker,
                cookie=cookie,
            )
            return candidate
        except MusicFetchError as err:
            if err.code == "DOWNLOAD_CANCELED":
                raise
            if err.code == "DOWNLOAD_FAILED" and "HTTP 403" in err.message:
                last_403 = err
                logger.warning(
                    "Candidate rejected by CDN with 403. song_id=%s level=%s encode=%s",
                    song_id,
                    candidate.level,
                    candidate.encode_type,
                )
                continue
            raise

    logger.info("Trying outer-url fallback download. song_id=%s", song_id)
    # "outer/url" is a looser public endpoint and can succeed when direct API URLs fail.
    outer_url = fetch_outer_media_url(song_id, timeout=timeout)
    if outer_url:
        outer_available = True
        try:
            _download_audio_stream(
                outer_url,
                output_path,
                timeout,
                progress_callback=progress_callback,
                cancel_checker=cancel_checker,
                cookie="",
            )
            logger.info("Outer-url fallback download succeeded. song_id=%s", song_id)
            return PlayableCandidate(
                media_url=outer_url,
                duration_ms=None,
                level="outer",
                encode_type=(infer_audio_format_from_url(outer_url) or "unknown"),
            )
        except MusicFetchError as err:
            logger.warning("Outer-url fallback failed. song_id=%s code=%s message=%s", song_id, err.code, err.message)
            if err.code != "DOWNLOAD_CANCELED":
                last_403 = err
            else:
                raise
    else:
        logger.warning("Outer-url fallback is unavailable for song. song_id=%s", song_id)

    if last_403:
        # If outer-url is not available, this is usually a true resource restriction
        # rather than a transient downloader issue.
        if not outer_available:
            raise MusicFetchError(
                "SONG_UNAVAILABLE",
                "Playable resources are blocked by CDN, and outer-url fallback is unavailable.",
            ) from last_403
        raise MusicFetchError(
            "DOWNLOAD_FAILED",
            "All playable candidates were rejected with HTTP 403 (including outer-url fallback).",
        ) from last_403
    raise MusicFetchError("DOWNLOAD_FAILED", "Failed to download all playable candidates.")


def prioritize_candidates_by_format(
    candidates: list[PlayableCandidate], prefer_format: str
) -> list[PlayableCandidate]:
    normalized = (prefer_format or "").strip().lower()
    if not normalized:
        return candidates

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
    logger.info(
        "Candidates reordered by preferred format. prefer=%s order=%s",
        normalized,
        [f"{c.level}:{c.encode_type}" for c in sorted_candidates],
    )
    return sorted_candidates


def fetch_outer_media_url(song_id: str, timeout: int = 20) -> Optional[str]:
    url = OUTER_MEDIA_URL_API.format(song_id=song_id)
    req = request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://music.163.com/",
            "Accept": "*/*",
        },
        method="GET",
    )
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
    # Different CDN nodes may enforce different anti-hotlink rules.
    # We keep a deterministic header matrix and iterate through it in order.
    attempts: list[dict[str, str]] = [
        {
            "User-Agent": base_user_agent,
            "Referer": "https://music.163.com/",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Range": "bytes=0-",
            "Sec-Fetch-Dest": "audio",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        },
        {
            "User-Agent": base_user_agent,
            "Referer": "https://y.music.163.com/",
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Range": "bytes=0-",
            "Sec-Fetch-Dest": "audio",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
        },
        {
            "User-Agent": base_user_agent,
            "Accept": "*/*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Range": "bytes=0-",
        },
    ]
    if cookie:
        attempts.append(
            {
                "User-Agent": base_user_agent,
                "Referer": "https://music.163.com/",
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Range": "bytes=0-",
                "Cookie": cookie,
                "Sec-Fetch-Dest": "audio",
                "Sec-Fetch-Mode": "no-cors",
                "Sec-Fetch-Site": "cross-site",
            }
        )
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


def normalize_media_url(url: str) -> str:
    parsed = parse.urlparse(url)
    host = parsed.netloc.lower()
    if parsed.scheme == "http" and host.endswith(".music.126.net"):
        secure_url = parse.urlunparse(("https", parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
        logger.info("Upgraded media url scheme to https. host=%s", host)
        return secure_url
    return url


def _candidate_media_urls(url: str) -> list[str]:
    normalized = normalize_media_url(url)
    candidates = [normalized]
    parsed = parse.urlparse(normalized)
    if parsed.scheme == "https" and parsed.netloc.lower().endswith(".music.126.net"):
        fallback_http = parse.urlunparse(("http", parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
        candidates.append(fallback_http)
    return candidates


def _download_audio_stream(
    media_url: str,
    output_path: Path,
    timeout: int,
    progress_callback: Optional[ProgressCallback],
    cancel_checker: Optional[CancelChecker],
    cookie: str,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    attempts = _build_download_attempt_headers(cookie)
    media_urls = _candidate_media_urls(media_url)
    media_host = parse.urlparse(media_urls[0]).netloc
    logger.info(
        "Starting media download. output=%s media_host=%s attempts=%s media_url=%s variants=%s",
        output_path,
        media_host,
        len(attempts),
        _url_for_log(media_urls[0]),
        len(media_urls),
    )

    tmp_path = output_path.with_name(f"{output_path.name}.part")
    last_403_error: Optional[error.HTTPError] = None
    last_network_error: Optional[error.URLError] = None

    total_attempts = len(attempts) * len(media_urls)
    attempt_no = 0
    for candidate_url in media_urls:
        for headers in attempts:
            attempt_no += 1
            if progress_callback:
                progress_callback(0, None)
            downloaded = 0
            total_bytes: Optional[int] = None
            req = request.Request(candidate_url, headers=headers, method="GET")
            logger.info(
                "Download attempt started. attempt=%s/%s scheme=%s referer=%s cookie=%s",
                attempt_no,
                total_attempts,
                parse.urlparse(candidate_url).scheme,
                headers.get("Referer", "none"),
                "yes" if "Cookie" in headers else "no",
            )
            try:
                with request.urlopen(req, timeout=timeout) as resp:
                    status = getattr(resp, "status", resp.getcode())
                    if status >= 400:
                        raise MusicFetchError("DOWNLOAD_FAILED", f"Media request failed: HTTP {status}.")
                    content_length = getattr(resp, "headers", {}).get("Content-Length")
                    if content_length and content_length.isdigit():
                        total_bytes = int(content_length)
                    with tmp_path.open("wb") as file_obj:
                        while True:
                            if cancel_checker and cancel_checker():
                                raise MusicFetchError("DOWNLOAD_CANCELED", "Download canceled by user.")
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
                logger.info(
                    "Media download finished. output=%s downloaded_bytes=%s total_bytes=%s attempt=%s",
                    output_path,
                    downloaded,
                    total_bytes if total_bytes is not None else "unknown",
                    attempt_no,
                )
                return
            except error.HTTPError as http_err:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                body_preview = ""
                try:
                    body_preview = http_err.read(200).decode("utf-8", errors="ignore").strip()
                except Exception:
                    body_preview = ""
                logger.warning(
                    "Download attempt HTTP error. attempt=%s/%s status=%s scheme=%s referer=%s cookie=%s body=%s",
                    attempt_no,
                    total_attempts,
                    http_err.code,
                    parse.urlparse(candidate_url).scheme,
                    headers.get("Referer", "none"),
                    "yes" if "Cookie" in headers else "no",
                    body_preview[:120],
                )
                if http_err.code == 403:
                    last_403_error = http_err
                    continue
                raise MusicFetchError("DOWNLOAD_FAILED", f"Media request failed: HTTP {http_err.code}.") from http_err
            except error.URLError as url_err:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                logger.warning(
                    "Download attempt network error. attempt=%s/%s reason=%s",
                    attempt_no,
                    total_attempts,
                    url_err.reason,
                )
                last_network_error = url_err
                continue
            except MusicFetchError:
                if tmp_path.exists():
                    tmp_path.unlink(missing_ok=True)
                if output_path.exists():
                    output_path.unlink(missing_ok=True)
                logger.warning("Media download canceled or failed, partial file removed. output=%s", output_path)
                raise

    if last_403_error is not None:
        logger.error("All download attempts failed with 403. output=%s media_host=%s", output_path, media_host)
        raise MusicFetchError(
            "DOWNLOAD_FAILED",
            "Media request failed: HTTP 403. Possible VIP/region/copyright restriction or anti-hotlink blocking.",
        ) from last_403_error
    if last_network_error is not None:
        logger.error("All download attempts failed with network errors. output=%s media_host=%s", output_path, media_host)
        raise MusicFetchError("NETWORK_ERROR", f"Network error: {last_network_error.reason}") from last_network_error

    raise MusicFetchError("DOWNLOAD_FAILED", "Media download failed after retries.")


def run_download(
    song_url: str,
    out_dir: Path,
    cookie_file: Path,
    out_format: str = "mp4",
    timeout: int = 30,
) -> DownloadResult:
    if out_format.lower() != "mp4":
        raise MusicFetchError("UNSUPPORTED_FORMAT", "Only mp4 output is supported in v1.")

    logger.info("Run download started. out_dir=%s format=%s", out_dir, out_format)
    song_id = parse_song_id(song_url)
    cookie = load_cookie(cookie_file)
    media_url, media_duration = fetch_playable_url(song_id, cookie, timeout=timeout)
    song_name, meta_duration = fetch_song_metadata(song_id, cookie, timeout=timeout)

    output_path = resolve_output_path(
        out_dir=out_dir,
        song_id=song_id,
        song_name=song_name,
        rename=None,
        out_format="mp4",
    )
    download_audio_with_progress(
        media_url=media_url,
        output_path=output_path,
        timeout=timeout,
        progress_callback=None,
        cancel_checker=None,
        cookie=cookie,
    )

    size_bytes = output_path.stat().st_size
    duration_ms = meta_duration if meta_duration is not None else media_duration
    logger.info(
        "Run download completed. song_id=%s output=%s size_bytes=%s duration_ms=%s",
        song_id,
        output_path,
        size_bytes,
        duration_ms,
    )
    return DownloadResult(
        song_id=song_id,
        output_path=output_path.resolve(),
        size_bytes=size_bytes,
        duration_ms=duration_ms,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="music-fetch",
        description="Fetch a playable NetEase Cloud Music track by song URL.",
    )
    parser.add_argument("--url", required=True, help="NetEase song URL or numeric song id.")
    parser.add_argument(
        "--out",
        default=DEFAULT_OUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--format",
        default="mp4",
        help="Output format (v1 only supports mp4).",
    )
    parser.add_argument(
        "--cookie-file",
        default=DEFAULT_COOKIE_FILE,
        help=f"Cookie file path (default: {DEFAULT_COOKIE_FILE}).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="HTTP timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "--log-file",
        default=str(default_log_path()),
        help=f"Log file path (default: {default_log_path()}).",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    log_path = setup_logging(Path(args.log_file))
    logger.info("CLI started. log_path=%s", log_path)

    try:
        result = run_download(
            song_url=args.url,
            out_dir=Path(args.out).expanduser(),
            cookie_file=Path(args.cookie_file).expanduser(),
            out_format=args.format,
            timeout=args.timeout,
        )
        duration_text = str(result.duration_ms) if result.duration_ms is not None else "unknown"
        print(
            "SUCCESS "
            f"path={result.output_path} "
            f"size_bytes={result.size_bytes} "
            f"duration_ms={duration_text}"
        )
        logger.info("CLI succeeded. output=%s", result.output_path)
        return 0
    except MusicFetchError as err:
        print(f"{err.code}: {err.message}", file=sys.stderr)
        logger.warning("CLI failed with known error. code=%s message=%s", err.code, err.message)
        return 1
    except KeyboardInterrupt:
        print("UNKNOWN_ERROR: Interrupted by user.", file=sys.stderr)
        logger.warning("CLI interrupted by user.")
        return 1
    except Exception as err:  # pragma: no cover
        print(f"UNKNOWN_ERROR: {err}", file=sys.stderr)
        logger.exception("CLI failed with unexpected error.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
