"""
NetEase Cloud Music API client.

Data-flow: constants → data-classes → URL/cookie helpers → HTTP helpers → API functions.
Depended on by music_fetch.audio.py (download) and music_fetch.cli.py (CLI entry point).  No reverse dependency.
"""

from __future__ import annotations

__all__ = [
    "MusicFetchError", "ErrorCode", "DownloadCanceled", "DownloadResult", "SongDetectionResult", "AccountProfile", "PlayableCandidate",
    "ProgressCallback", "CancelChecker", "PauseChecker",
    "parse_song_id", "parse_playlist_id", "parse_input_resource",
    "extract_url_from_input", "is_netease_music_host", "resolve_short_url",
    "configure_proxy",
    "load_cookie", "extract_csrf", "parse_cookie_fields", "normalize_cookie", "build_cookie_string",
    "check_login_status", "fetch_account_profile",
    "fetch_playable_candidates", "fetch_playable_url", "fetch_song_metadata", "fetch_playlist_song_ids",
    "detect_song", "normalize_media_url",
    "search_songs", "SearchResult",
    "fetch_user_playlists", "UserPlaylist",
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
from typing import Any, Callable, Optional, Tuple
from urllib import error, parse, request

from music_fetch.app_logging import get_logger, mask_value
from music_fetch.app_settings import SHORT_LINK_HOSTS, SUPPORTED_AUDIO_FORMATS, TRAILING_URL_PUNCTUATION, URL_IN_TEXT_PATTERN
from music_fetch.network import configure_proxy, open_url

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)
PLAYER_URL_API = "https://music.163.com/api/song/enhance/player/url/v1"
SONG_DETAIL_API = "https://music.163.com/api/song/detail"
PLAYLIST_DETAIL_API = "https://music.163.com/api/v6/playlist/detail"
ACCOUNT_STATUS_API = "https://music.163.com/api/nuser/account/get"
OUTER_MEDIA_URL_API = "https://music.163.com/song/media/outer/url?id={song_id}.mp3"
LYRIC_API = "https://music.163.com/api/song/lyric?id={song_id}&lv=1&kv=1&tv=-1"
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
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    CONVERT_TOOL_MISSING = "CONVERT_TOOL_MISSING"
    CONVERT_FAILED = "CONVERT_FAILED"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class DownloadCanceled(Exception):
    """Control-flow signal: download was canceled by user. Not a subprocess error."""


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
    cover_url: Optional[str] = None
    artist: Optional[str] = None
    album_name: Optional[str] = None
    level: str = ""  # highest available quality level (standard/higher/exhigh/lossless/hires)
    encode_type: str = ""  # e.g. mp3 / aac of that level


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
        with open_url(req, timeout=timeout) as resp:
            resolved = resp.geturl()
            logger.info("Resolved short link. from=%s to=%s", url, resolved)
            return resolved
    except error.HTTPError as http_err:
        # HTTPError.geturl() returns the final URL after redirects, but only
        # trust it if it actually differs from the original (i.e. a redirect
        # happened). Otherwise the error page URL == original short link.
        redirected = http_err.geturl() if hasattr(http_err, "geturl") else ""
        if redirected and redirected != url:
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
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, f"Cookie file not found: {cookie_file}. Run music-fetch without arguments to sign in with QR first.")
    try:
        raw = cookie_file.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, f"Cookie file is corrupted (invalid encoding): {cookie_file}.")
    cookie = normalize_cookie(raw)
    if not cookie:
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Cookie file is empty. Run music-fetch without arguments to sign in with QR first.")
    if "MUSIC_U=" not in cookie:
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Cookie file does not include MUSIC_U. Run music-fetch without arguments to sign in with QR first.")
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

def perform_json_post(url: str, payload: dict[str, str], headers: dict[str, str], timeout: int) -> Tuple[int, dict[str, object]]:
    encoded = parse.urlencode(payload).encode("utf-8")
    req = request.Request(url, data=encoded, headers=headers, method="POST")
    status, body = _perform_request(req, timeout=timeout)
    return status, _decode_json(body)


def perform_json_get(url: str, headers: dict[str, str], timeout: int) -> Tuple[int, dict[str, object]]:
    req = request.Request(url, headers=headers, method="GET")
    status, body = _perform_request(req, timeout=timeout)
    return status, _decode_json(body)


def _perform_request(req: request.Request, timeout: int) -> Tuple[int, bytes]:
    logger.debug("HTTP request. method=%s url=%s", req.get_method(), req.full_url)
    try:
        with open_url(req, timeout=timeout) as resp:
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
        if not decoded:
            return {}
        result = json.loads(decoded)
        if not isinstance(result, dict):
            raise MusicFetchError(ErrorCode.NETWORK_ERROR, "Unexpected API response (not a JSON object).")
        return result
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
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login credential is missing MUSIC_U.")
    headers = {"User-Agent": USER_AGENT, "Referer": "https://music.163.com/", "Cookie": cookie}
    status, body = perform_json_get(ACCOUNT_STATUS_API, headers, timeout=timeout)
    code = body.get("code")
    if status in (401, 403) or code in (301, 302, 401, 403):
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login state expired. Run music-fetch without arguments to scan QR login again.")
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
            raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login state expired. Run music-fetch without arguments to scan QR login again.")
        if status >= 500:
            last_network_message = f"Server error from NetEase: HTTP {status}."
            continue
        code = body.get("code")
        if code in (301, 302, 401, 403):
            raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login state expired. Run music-fetch without arguments to scan QR login again.")
        if code != 200:
            last_network_message = str(body.get("message") or f"Unexpected API code={code}")
            continue
        data = body.get("data") or []
        if not data:
            saw_song_unavailable = True
            continue
        media = data[0]  # type: ignore[index]
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


def fetch_song_metadata(song_id: str, cookie: str, timeout: int) -> Tuple[Optional[str], Optional[int], Optional[str], Optional[str], Optional[str]]:
    headers = {"User-Agent": USER_AGENT, "Referer": "https://music.163.com/", "Cookie": cookie}
    query = parse.urlencode({"ids": f"[{song_id}]"})
    url = f"{SONG_DETAIL_API}?{query}"
    try:
        status, body = perform_json_get(url, headers, timeout=timeout)
    except MusicFetchError as err:
        logger.warning("Failed to fetch song metadata. song_id=%s code=%s message=%s", song_id, err.code, err.message)
        return None, None, None, None, None
    if status != 200 or body.get("code") != 200:
        return None, None, None, None, None
    songs = body.get("songs") or []
    if not songs:
        logger.warning("Song metadata not found. song_id=%s", song_id)
        return None, None, None, None, None
    song = songs[0]  # type: ignore[index]
    name = song.get("name")
    duration_ms = song.get("dt")
    # Extract cover art URL from album info
    cover_url = None
    album = song.get("al")
    if isinstance(album, dict):
        cover_url = album.get("picUrl") or None
    # Extract artist names
    artist_names: list[str] = []
    artists = song.get("ar")
    if isinstance(artists, list):
        for ar in artists:
            if isinstance(ar, dict):
                ar_name = ar.get("name")
                if isinstance(ar_name, str) and ar_name.strip():
                    artist_names.append(ar_name.strip())
    artist_str = " / ".join(artist_names) if artist_names else None
    # Extract album name
    album_name = album.get("name") if isinstance(album, dict) else None
    if isinstance(album_name, str):
        album_name = album_name.strip() or None
    if isinstance(name, str):
        name = name.strip() or None
    else:
        name = None
    if not isinstance(duration_ms, int):
        duration_ms = None
    return name, duration_ms, cover_url, artist_str, album_name


def fetch_playlist_song_ids(playlist_id: str, cookie: str, timeout: int = 20) -> list[str]:
    headers = {"User-Agent": USER_AGENT, "Referer": "https://music.163.com/", "Cookie": cookie}
    page_size = 1000
    offset = 0
    all_ids: list[str] = []
    seen: set[str] = set()
    first_page_body: Optional[dict[str, object]] = None
    while True:
        query = parse.urlencode({"id": playlist_id, "n": str(page_size), "s": str(offset)})
        url = f"{PLAYLIST_DETAIL_API}?{query}"
        try:
            status, body = perform_json_get(url, headers, timeout=timeout)
        except MusicFetchError as err:
            if all_ids:
                logger.warning(
                    "Playlist fetch interrupted, returning partial results. playlist_id=%s fetched=%s error=%s",
                    playlist_id, len(all_ids), err.message,
                )
                return all_ids
            raise
        if first_page_body is None:
            first_page_body = body
        if status in (401, 403):
            raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login state expired. Run music-fetch without arguments to scan QR login again.")
        code = body.get("code")
        if code in (301, 302, 401, 403):
            raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login state expired. Run music-fetch without arguments to scan QR login again.")
        if status != 200 or code != 200:
            message = str(body.get("message") or f"Unexpected playlist API response: status={status}, code={code}")
            raise MusicFetchError(ErrorCode.NETWORK_ERROR, message)
        playlist = (body or {}).get("playlist") or {}
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
        if len(raw_track_ids) < page_size or not page_ids:
            break
        offset += page_size
    if not all_ids:
        # Fallback: try the legacy tracks field (only on first page when trackIds returned nothing)
        playlist = (first_page_body or {}).get("playlist") or {}
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


_LEVEL_RANK = {"standard": 1, "higher": 2, "exhigh": 3, "lossless": 4, "hires": 5}


def _pick_highest_level(candidates: list[PlayableCandidate]) -> tuple[str, str]:
    """Return (level, encode_type) of the highest-quality candidate."""
    best_level = ""
    best_encode = ""
    best_rank = 0
    for candidate in candidates:
        rank = _LEVEL_RANK.get((candidate.level or "").strip().lower(), 0)
        if rank > best_rank:
            best_rank = rank
            best_level = candidate.level
            best_encode = candidate.encode_type
    return best_level, best_encode


def detect_song(song_url: str, cookie: str, timeout: int = 20) -> SongDetectionResult:
    song_id = parse_song_id(song_url)
    logger.info("Detecting song by url. song_id=%s", song_id)
    song_name, meta_duration, cover_url, artist, album_name = fetch_song_metadata(song_id, cookie, timeout=timeout)
    try:
        candidates = fetch_playable_candidates(song_id, cookie, timeout=timeout)
    except MusicFetchError as err:
        if err.code != "SONG_UNAVAILABLE":
            raise
        return SongDetectionResult(song_id=song_id, song_name=song_name, duration_ms=meta_duration, media_url=None, can_download=False, unavailable_reason=err.message, cover_url=cover_url, artist=artist, album_name=album_name)
    first = candidates[0]
    level, encode_type = _pick_highest_level(candidates)
    duration = meta_duration if meta_duration is not None else first.duration_ms
    return SongDetectionResult(song_id=song_id, song_name=song_name, duration_ms=duration, media_url=first.media_url, can_download=True, unavailable_reason=None, cover_url=cover_url, artist=artist, album_name=album_name, level=level, encode_type=encode_type)


# ── Media URL utils ──────────────────────────────────────────────

def normalize_media_url(url: str) -> str:
    parsed = parse.urlparse(url)
    host = parsed.netloc.lower()
    if parsed.scheme == "http" and host.endswith(".music.126.net"):
        secure_url = parse.urlunparse(("https", parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
        logger.info("Upgraded media url scheme to https. host=%s", host)
        return secure_url
    return url


# ── Search ──────────────────────────────────────────────────────

SEARCH_API = "https://music.163.com/api/search/get"


@dataclass
class SearchResult:
    song_id: str
    song_name: str
    artist: str
    album: str
    duration_ms: int


def search_songs(keyword: str, cookie: str, timeout: int = 10, limit: int = 30) -> list[SearchResult]:
    """Search songs by keyword on NetEase Cloud Music."""
    if not keyword.strip():
        return []
    headers = {"User-Agent": USER_AGENT, "Referer": "https://music.163.com/", "Cookie": cookie}
    payload = {"s": keyword, "type": "1", "limit": str(limit), "offset": "0"}
    try:
        status, body = perform_json_post(SEARCH_API, payload, headers, timeout=timeout)
    except MusicFetchError:
        logger.warning("Search request failed. keyword=%s", keyword)
        return []
    if status != 200 or body.get("code") != 200:
        logger.warning("Search API returned non-200. status=%s code=%s", status, body.get("code"))
        return []
    raw_songs = body.get("result", {}).get("songs") or []
    results: list[SearchResult] = []
    for song in raw_songs:
        if not isinstance(song, dict):
            continue
        song_id = str(song.get("id") or "")
        if not song_id:
            continue
        name = str(song.get("name") or "")
        artists = song.get("artists") or song.get("ar") or []
        artist_names: list[str] = []
        if isinstance(artists, list):
            for ar in artists:
                if isinstance(ar, dict):
                    ar_name = ar.get("name")
                    if isinstance(ar_name, str) and ar_name.strip():
                        artist_names.append(ar_name.strip())
        album_info = song.get("album") or song.get("al") or {}
        album_name = album_info.get("name") if isinstance(album_info, dict) else None
        duration = song.get("duration") or song.get("dt") or 0
        results.append(SearchResult(
            song_id=song_id,
            song_name=name,
            artist=" / ".join(artist_names) if artist_names else "",
            album=str(album_name or ""),
            duration_ms=int(duration) if duration else 0,
        ))
    logger.info("Search completed. keyword=%s results=%s", keyword, len(results))
    return results


# ── User playlists ──────────────────────────────────────────────

USER_PLAYLIST_API = "https://music.163.com/api/user/playlist"


@dataclass
class UserPlaylist:
    playlist_id: str
    name: str
    song_count: int
    cover_url: str
    creator: str


def fetch_user_playlists(cookie: str, timeout: int = 10) -> list[UserPlaylist]:
    """Fetch the logged-in user's playlists."""
    if "MUSIC_U=" not in cookie:
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Login credential is missing MUSIC_U.")
    headers = {"User-Agent": USER_AGENT, "Referer": "https://music.163.com/", "Cookie": cookie}
    # First get user ID from account status
    status, body = perform_json_get(ACCOUNT_STATUS_API, headers, timeout=timeout)
    if status != 200 or body.get("code") != 200:
        raise MusicFetchError(ErrorCode.NETWORK_ERROR, "Failed to fetch account info for playlists.")
    account = body.get("account") or {}
    user_id = account.get("id")
    if not user_id:
        raise MusicFetchError(ErrorCode.AUTH_EXPIRED, "Could not determine user ID from account.")
    query = parse.urlencode({"uid": str(user_id), "limit": "100", "offset": "0"})
    url = f"{USER_PLAYLIST_API}?{query}"
    status, body = perform_json_get(url, headers, timeout=timeout)
    if status != 200 or body.get("code") != 200:
        logger.warning("User playlist API returned non-200. status=%s", status)
        return []
    raw_playlists = body.get("playlist") or []
    results: list[UserPlaylist] = []
    for pl in raw_playlists:
        if not isinstance(pl, dict):
            continue
        pid = str(pl.get("id") or "")
        if not pid:
            continue
        results.append(UserPlaylist(
            playlist_id=pid,
            name=str(pl.get("name") or ""),
            song_count=int(pl.get("trackCount") or 0),
            cover_url=str(pl.get("coverImgUrl") or ""),
            creator=str((pl.get("creator") or {}).get("nickname") or ""),
        ))
    logger.info("User playlists fetched. count=%s", len(results))
    return results


# ── Lyrics ─────────────────────────────────────────────────────────

@dataclass
class LyricResult:
    """Lyric data for a song."""
    lyric: str  # original LRC format lyrics
    translated_lyric: str = ""  # translated LRC lyrics (may be empty)


def fetch_lyric(song_id: str, timeout: int = 10) -> LyricResult:
    """Fetch lyrics for a song. No authentication required."""
    url = LYRIC_API.format(song_id=song_id)
    headers = {"User-Agent": USER_AGENT, "Referer": "https://music.163.com/"}
    try:
        status, body = perform_json_get(url, headers, timeout=timeout)
    except MusicFetchError:
        logger.warning("Failed to fetch lyric for song. song_id=%s", song_id)
        return LyricResult(lyric="")
    if status != 200 or body.get("code") != 200:
        logger.warning("Lyric API returned non-200. song_id=%s status=%s", song_id, status)
        return LyricResult(lyric="")
    lrc = str(body.get("lrc", {}).get("lyric") or "")
    tlyric = str(body.get("tlyric", {}).get("lyric") or "")
    logger.info("Fetched lyric. song_id=%s lyric_len=%s translated_len=%s", song_id, len(lrc), len(tlyric))
    return LyricResult(lyric=lrc, translated_lyric=tlyric)

