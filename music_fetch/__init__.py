"""
music-fetch — NetEase Cloud Music download tool.

Public API surface.  Backward-compatible with pre-package imports.
"""

from music_fetch.api import (
    # Exceptions
    MusicFetchError,
    ErrorCode,
    DownloadCanceled,
    # Data classes
    DownloadResult,
    SongDetectionResult,
    AccountProfile,
    PlayableCandidate,
    # Callback types
    ProgressCallback,
    CancelChecker,
    PauseChecker,
    # URL / input parsing
    parse_song_id,
    parse_playlist_id,
    parse_input_resource,
    extract_url_from_input,
    is_netease_music_host,
    resolve_short_url,
    # Cookie helpers
    load_cookie,
    extract_csrf,
    parse_cookie_fields,
    normalize_cookie,
    build_cookie_string,
    # Auth / account
    check_login_status,
    fetch_account_profile,
    # Song / playlist
    fetch_playable_candidates,
    fetch_playable_url,
    fetch_song_metadata,
    fetch_playlist_song_ids,
    detect_song,
    normalize_media_url,
    search_songs,
    SearchResult,
    fetch_user_playlists,
    UserPlaylist,
    # Lyrics
    fetch_lyric,
    LyricResult,
    # Constants
    SUPPORTED_GUI_AUDIO_FORMATS,
    SHORT_LINK_HOSTS,
    DEFAULT_OUT_DIR,
    DEFAULT_COOKIE_FILE,
)

from music_fetch.audio import (
    sanitize_filename,
    dedupe_path,
    resolve_output_path,
    infer_audio_format_from_url,
    is_ffmpeg_available,
    convert_audio_file,
    download_audio,
    download_audio_with_progress,
    download_song_with_fallback,
    prioritize_candidates_by_format,
    fetch_outer_media_url,
)

from music_fetch.network import (
    ProxyConfig,
    ProxyConfigError,
    configure_proxy,
    get_proxy_config,
    normalize_proxy_config,
    open_url,
)

from music_fetch.download_runner import (
    DownloadJob,
    DownloadJobResult,
    DownloadProgressSnapshot,
)
from music_fetch.batch_inspect import run_batch_detect
from music_fetch.batch_download import (
    BatchDownloadCounters,
    BatchDownloadSession,
    format_speed,
)

from music_fetch.cli import (
    run_download,
    run_playlist_download,
    build_parser,
    main,
)

# Explicit public surface — keeps `from music_fetch import *` deterministic and
# prevents incidental re-exports from leaking into downstream code.
__all__ = [
    # Exceptions / errors
    "MusicFetchError",
    "ErrorCode",
    "DownloadCanceled",
    "ProxyConfigError",
    # Data classes
    "DownloadResult",
    "SongDetectionResult",
    "AccountProfile",
    "PlayableCandidate",
    "SearchResult",
    "UserPlaylist",
    "LyricResult",
    "ProxyConfig",
    # Callback types
    "ProgressCallback",
    "CancelChecker",
    "PauseChecker",
    # URL / input parsing
    "parse_song_id",
    "parse_playlist_id",
    "parse_input_resource",
    "extract_url_from_input",
    "is_netease_music_host",
    "resolve_short_url",
    # Cookie helpers
    "load_cookie",
    "extract_csrf",
    "parse_cookie_fields",
    "normalize_cookie",
    "build_cookie_string",
    # Auth / account
    "check_login_status",
    "fetch_account_profile",
    # Song / playlist / search
    "fetch_playable_candidates",
    "fetch_playable_url",
    "fetch_song_metadata",
    "fetch_playlist_song_ids",
    "detect_song",
    "normalize_media_url",
    "search_songs",
    "fetch_user_playlists",
    "fetch_lyric",
    # Download runner / batch (TUI-era)
    "DownloadJob",
    "DownloadJobResult",
    "DownloadProgressSnapshot",
    "run_batch_detect",
    "BatchDownloadCounters",
    "BatchDownloadSession",
    "format_speed",
    # Audio helpers
    "sanitize_filename",
    "dedupe_path",
    "resolve_output_path",
    "infer_audio_format_from_url",
    "is_ffmpeg_available",
    "convert_audio_file",
    "download_audio",
    "download_audio_with_progress",
    "download_song_with_fallback",
    "prioritize_candidates_by_format",
    "fetch_outer_media_url",
    # Network / proxy
    "configure_proxy",
    "get_proxy_config",
    "normalize_proxy_config",
    "open_url",
    # CLI entry points
    "run_download",
    "run_playlist_download",
    "build_parser",
    "main",
    # Constants
    "SUPPORTED_GUI_AUDIO_FORMATS",
    "SHORT_LINK_HOSTS",
    "DEFAULT_OUT_DIR",
    "DEFAULT_COOKIE_FILE",
]
