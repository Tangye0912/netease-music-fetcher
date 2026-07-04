"""
NetEase Cloud Music API client.

Data-flow: constants → data-classes → URL/cookie helpers → HTTP helpers → API functions.
Depended on by music_fetch.audio.py (download) and music_fetch.cli.py (CLI entry point).  No reverse dependency.
"""

from __future__ import annotations

__all__ = [
    "MusicFetchError", "ErrorCode", "DownloadCanceled", "DownloadPaused", "DownloadResult", "SongDetectionResult", "AccountProfile", "PlayableCandidate",
    "ProgressCallback", "CancelChecker", "PauseChecker",
    "parse_song_id", "parse_playlist_id", "parse_input_resource",
    "extract_url_from_input", "is_netease_music_host", "resolve_short_url",
    "load_cookie", "extract_csrf", "parse_cookie_fields", "normalize_cookie", "build_cookie_string",
    "check_login_status", "fetch_account_profile",
    "fetch_playable_candidates", "fetch_playable_url", "fetch_song_metadata", "fetch_playlist_song_ids",
    "detect_song", "normalize_media_url",
    "SUPPORTED_GUI_AUDIO_FORMATS",
    "USER_AGENT", "OUTER_MEDIA_URL_API", "DEFAULT_OUT_DIR", "DEFAULT_COOKIE_FILE",
    "PLAYABLE_REQUEST_PROFILES",
    "SHORT_LINK_HOSTS",
    "logger",
]

import json
import logging
import re
from enum import Enum
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple
from urllib import error, parse, request

from music_fetch.app_logging import get_logger, mask_value
from music_fetch.app_settings import SHORT_LINK_HOSTS, SUPPORTED_AUDIO_FORMATS, TRAILING_URL_PUNCTUATION, URL_IN_TEXT_PATTERN

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
PLAYER_URL_API = "https://music.163.com/api/song/enhance/player/url/v1"
SONG_DETAIL_API = "https://music.163.com/api/song/detail"
PLAYLIST_DETAIL_API = "https://music.163.com/api/v6/playlist/detail"
ACCOUNT_STATUS_API = "https://music.163.com/api/nuser/account/get"
OUTER_MEDIA_URL_API = "https://music.163.com/song/media/outer/url?id={song_id}.mp3"
DEFAULT_OUT_DIR = "downloads"
DEFAULT_COOKIE_FILE = "~/.config/music-fetch/cookies.txt"
PLAYABLE_REQUEST_PROFILES: list[tuple[str, str]] = [
    ("standard", "mp3"),
    ("standard", "aac"),
    ("standard", "mp4"),
    ("higher", "aac"),
    ("exhigh", "aac"),
]
logger = get_logger("music_fetch.api")
SUPPORTED_GUI_AUDIO_FORMATS = SUPPORTED_AUDIO_FORMATS


class MusicFetchError(Exception):
    """Standardized error with stable code and human-readable message."""

    def __init__(self, code: str | ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code.value if isinstance(code, ErrorCode) else code
        self.message = message


class ErrorCode(Enum):
    """Stable error codes for MusicFetchError."""
    INVALID_URL = "INVALID_URL"
    AUTH_EXPIRED = "AUTH_EXPIRED"
    SONG_UNAVAILABLE = "SONG_UNAVAILABLE"
    NETWORK_ERROR = "NETWORK_ERROR"
    DOWNLOAD_FAILED = "DOWNLOAD_FAILED"
    DOWNLOAD_CANCELED = "DOWNLOAD_CANCELED"
    DOWNLOAD_PAUSED = "DOWNLOAD_PAUSED"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    CONVERT_TOOL_MISSING = "CONVERT_TOOL_MISSING"
    CONVERT_FAILED = "CONVERT_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class DownloadCanceled(Exception):
    """Control-flow signal: download was canceled by user. Not a subprocess error."""


class DownloadPaused(Exception):
    """Control-flow signal: download was paused by user. Not a subprocess error."""


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
PauseChecker = Callable[[], bool]


# ── URL / Input parsing ──────────────────────────────────────────

def parse_song_id(value: str) -> str:
    resource_type, resource_id = parse_input_resource(value)
    if resource_type == "playlist":
        raise MusicFetchError(ErrorCode.INVALID_URL, "Detected playlist link. Please use batch mode.")
    return resource_id


def parse_playlist_id(value: str) -> str:
    resource_type, resource_id = parse_input_resource(value)
    if resource_type != "playlist":
        raise MusicFetchError(ErrorCode.INVALID_URL, "Input is not a playlist link.")
    return resource_id


def parse_input_resource(value: str) -> tuple[str, str]:
    raw = value.strip()
    if raw.isdigit():
        logger.info("Parsed numeric song id directly: %s", raw)
        return "song", raw

    url = extract_url_from_input(raw)
    logger.info("Parsing input resource. extracted_url=%s", bool(url))
    parsed = parse.urlparse(url if url else raw)
    host = parsed.netloc.lower()
    if host and not is_netease_music_host(host) and host not in SHORT_LINK_HOSTS:
        raise MusicFetchError(ErrorCode.INVALID_URL, "Only music.163.com or 163cn.tv links are supported.")

    target_url = url if url else raw
    if host in SHORT_LINK_HOSTS:
        logger.info("Resolving short link host=%s", host)
        target_url = resolve_short_url(target_url, timeout=15)
        parsed = parse.urlparse(target_url)
        host = parsed.netloc.lower()
        if host and not is_netease_music_host(host):
            raise MusicFetchError(ErrorCode.INVALID_URL, "Could not resolve short link to a music.163.com resource URL.")

    resource_type = _detect_resource_type(parsed, target_url)
    resource_id = _extract_resource_id(parsed, target_url)
    if not resource_id:
        raise MusicFetchError(ErrorCode.INVALID_URL, "Could not parse resource id from the provided URL.")
    return resource_type, resource_id


def _detect_resource_type(parsed: parse.ParseResult, raw_target: str) -> str:
    path = (parsed.path or "").lower()
    fragment = (parsed.fragment or "").lower()
    lowered = raw_target.lower()
    if "/playlist" in path or "/playlist" in fragment or "#/playlist" in lowered:
        return "playlist"
    return "song"


def _extract_resource_id(parsed: parse.ParseResult, raw_target: str) -> str:
    query = parse.parse_qs(parsed.query)
    parsed_id = _pick_first_digit(query.get("id"))
    if parsed_id:
        return parsed_id

    if parsed.fragment:
        frag_query = parsed.fragment.split("?", 1)[1] if "?" in parsed.fragment else ""
        if frag_query:
            frag_map = parse.parse_qs(frag_query)
            parsed_id = _pick_first_digit(frag_map.get("id"))
            if parsed_id:
                return parsed_id
        match = re.search(r"id=(\d+)", parsed.fragment)
        if match:
            return match.group(1)

    for pattern in (r"/song/(\d+)", r"/playlist/(\d+)"):
        match = re.search(pattern, parsed.path or "")
        if match:
            return match.group(1)

    match = re.search(r"id=(\d+)", raw_target)
    if match:
        logger.info("Parsed resource id from fallback pattern. id=%s", match.group(1))
        return match.group(1)
    return ""


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
        raise MusicFetchError(ErrorCode.NETWORK_ERROR, f"Failed to resolve short link: HTTP {http_err.code}") from http_err
    except error.URLError as url_err:
        logger.error("Short link resolve network error. url=%s reason=%s", url, url_err.reason)
        raise MusicFetchError(ErrorCode.NETWORK_ERROR, f"Network error: {url_err.reason}") from url_err


def _pick_first_digit(values: Optional[list[str]]) -> Optional[str]:
    if not values:
        return None
    for value in values:
        if value and value.isdigit():
            return value
    return None


# ── Cookie helpers ───────────────────────────────────────────────

def load_cookie(cookie_file: Path) -> str:
    logger.info("Loading cookie file from %s", cookie_file)
    if not cookie_file.exists():
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, f"Cookie file not found: {cookie_file}. Please export a valid MUSIC_U cookie.")
    cookie = normalize_cookie(cookie_file.read_text(encoding="utf-8"))
    if not cookie:
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Cookie file is empty. Please refresh your cookie.")
    if "MUSIC_U=" not in cookie:
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Cookie file does not include MUSIC_U. Please re-export from browser.")
    fields = parse_cookie_fields(cookie)
    logger.info("Cookie loaded. has_music_u=%s has_csrf=%s music_u_mask=%s", "MUSIC_U" in fields, "__csrf" in fields, mask_value(fields.get("MUSIC_U", "")))
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


# ── HTTP helpers ─────────────────────────────────────────────────

def perform_json_post(url: str, payload: dict[str, str], headers: dict[str, str], timeout: int) -> Tuple[int, dict]:
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
        raise MusicFetchError(ErrorCode.NETWORK_ERROR, f"Network error: {url_err.reason}") from url_err


def _decode_json(body: bytes) -> dict[str, object]:
    try:
        decoded = body.decode("utf-8")
        return json.loads(decoded) if decoded else {}
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise MusicFetchError(ErrorCode.NETWORK_ERROR, "Unexpected API response (invalid JSON).") from err


# ── Account / Auth ───────────────────────────────────────────────

def check_login_status(cookie: str, timeout: int = 10) -> bool:
    if "MUSIC_U=" not in cookie:
        logger.info("Login status check failed: no MUSIC_U in cookie.")
        return False
    headers = {"User-Agent": USER_AGENT, "Referer": "https://music.163.com/", "Cookie": cookie}
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
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login cookie missing MUSIC_U.")
    headers = {"User-Agent": USER_AGENT, "Referer": "https://music.163.com/", "Cookie": cookie}
    status, body = perform_json_get(ACCOUNT_STATUS_API, headers, timeout=timeout)
    code = body.get("code")
    if status in (401, 403) or code in (301, 302, 401, 403):
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login state expired. Please login again.")
    if status != 200 or code != 200:
        raise MusicFetchError(ErrorCode.NETWORK_ERROR, f"Unexpected account API response: status={status}, code={code}")
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
    logger.info("Fetched account profile. user_id=%s nickname=%s vip_type=%s", user_id, nickname, vip_type)
    return AccountProfile(user_id=user_id, nickname=nickname, avatar_url=avatar_url, vip_type=vip_type, is_vip=is_vip)


# ── Song / Playlist ──────────────────────────────────────────────

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
        payload = {"ids": json.dumps([int(song_id)]), "level": level, "encodeType": encode_type, "csrf_token": csrf}
        status, body = perform_json_post(PLAYER_URL_API, payload, headers, timeout=timeout)
        logger.info("Requested playable url. song_id=%s level=%s encode=%s status=%s api_code=%s", song_id, level, encode_type, status, body.get("code"))
        if status in (401, 403):
            raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login state expired. Please refresh cookie.")
        if status >= 500:
            last_network_message = f"Server error from NetEase: HTTP {status}."
            continue
        code = body.get("code")
        if code in (301, 302, 401, 403):
            raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login state expired. Please refresh cookie.")
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
        logger.info("Playable url resolved. song_id=%s level=%s encode=%s media_host=%s duration_ms=%s", song_id, level, encode_type, media_host, media.get("time"))
        candidates.append(PlayableCandidate(media_url=media_url, duration_ms=media.get("time"), level=level, encode_type=encode_type))

    if candidates:
        return candidates
    if saw_song_unavailable:
        raise MusicFetchError(ErrorCode.SONG_UNAVAILABLE, "Song is unavailable (copyright/region/VIP restriction).")
    if last_network_message:
        raise MusicFetchError(ErrorCode.NETWORK_ERROR, last_network_message)
    raise MusicFetchError(ErrorCode.NETWORK_ERROR, "Could not resolve playable media url.")


def fetch_playable_url(song_id: str, cookie: str, timeout: int) -> Tuple[str, Optional[int]]:
    candidates = fetch_playable_candidates(song_id, cookie, timeout=timeout)
    first = candidates[0]
    return first.media_url, first.duration_ms


def fetch_song_metadata(song_id: str, cookie: str, timeout: int) -> Tuple[Optional[str], Optional[int]]:
    headers = {"User-Agent": USER_AGENT, "Referer": "https://music.163.com/", "Cookie": cookie}
    query = parse.urlencode({"ids": f"[{song_id}]"})
    url = f"{SONG_DETAIL_API}?{query}"
    try:
        status, body = perform_json_get(url, headers, timeout=timeout)
    except MusicFetchError as err:
        logger.warning("Failed to fetch song metadata. song_id=%s code=%s message=%s", song_id, err.code, err.message)
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


def fetch_playlist_song_ids(playlist_id: str, cookie: str, timeout: int = 20) -> list[str]:
    headers = {"User-Agent": USER_AGENT, "Referer": "https://music.163.com/", "Cookie": cookie}
    page_size = 1000
    offset = 0
    all_ids: list[str] = []
    seen: set[str] = set()
    while True:
        query = parse.urlencode({"id": playlist_id, "n": str(page_size), "s": str(offset)})
        url = f"{PLAYLIST_DETAIL_API}?{query}"
        status, body = perform_json_get(url, headers, timeout=timeout)
        if status in (401, 403):
            raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login state expired. Please refresh cookie.")
        code = body.get("code")
        if code in (301, 302, 401, 403):
            raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login state expired. Please refresh cookie.")
        if status != 200 or code != 200:
            message = str(body.get("message") or f"Unexpected playlist API response: status={status}, code={code}")
            raise MusicFetchError(ErrorCode.NETWORK_ERROR, message)
        playlist = body.get("playlist") or {}
        raw_track_ids = playlist.get("trackIds") or []
        page_ids: list[str] = []
        for row in raw_track_ids if isinstance(raw_track_ids, list) else []:
            if isinstance(row, dict):
                value = row.get("id")
                if isinstance(value, int):
                    sid = str(value)
                    if sid not in seen:
                        seen.add(sid)
                        page_ids.append(sid)
        if not page_ids:
            break
        all_ids.extend(page_ids)
        if len(raw_track_ids) < page_size:
            break
        offset += page_size
    if not all_ids:
        # Fallback: try the legacy tracks field (only on first page when trackIds returned nothing)
        playlist = body.get("playlist") or {}
        raw_tracks = playlist.get("tracks") or []
        for row in raw_tracks if isinstance(raw_tracks, list) else []:
            if isinstance(row, dict):
                value = row.get("id")
                if isinstance(value, int):
                    sid = str(value)
                    if sid not in seen:
                        seen.add(sid)
                        all_ids.append(sid)
    if not all_ids:
        raise MusicFetchError(ErrorCode.SONG_UNAVAILABLE, "Playlist is empty or unavailable.")
    if len(all_ids) >= page_size:
        logger.info("Fetched playlist songs. playlist_id=%s count=%s (may have more)", playlist_id, len(all_ids))
    else:
        logger.info("Fetched playlist songs. playlist_id=%s count=%s", playlist_id, len(all_ids))
    return all_ids


def detect_song(song_url: str, cookie: str, timeout: int = 20) -> SongDetectionResult:
    song_id = parse_song_id(song_url)
    logger.info("Detecting song by url. song_id=%s", song_id)
    song_name, meta_duration = fetch_song_metadata(song_id, cookie, timeout=timeout)
    try:
        media_url, media_duration = fetch_playable_url(song_id, cookie, timeout=timeout)
    except MusicFetchError as err:
        if err.code != "SONG_UNAVAILABLE":
            raise
        return SongDetectionResult(song_id=song_id, song_name=song_name, duration_ms=meta_duration, media_url=None, can_download=False, unavailable_reason=err.message)
    duration = meta_duration if meta_duration is not None else media_duration
    return SongDetectionResult(song_id=song_id, song_name=song_name, duration_ms=duration, media_url=media_url, can_download=True, unavailable_reason=None)


# ── Media URL utils ──────────────────────────────────────────────

def normalize_media_url(url: str) -> str:
    parsed = parse.urlparse(url)
    host = parsed.netloc.lower()
    if parsed.scheme == "http" and host.endswith(".music.126.net"):
        secure_url = parse.urlunparse(("https", parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
        logger.info("Upgraded media url scheme to https. host=%s", host)
        return secure_url
    return url
