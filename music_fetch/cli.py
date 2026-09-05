"""
Command-line interface for music-fetch.

Provides run_download() (script-friendly API), run_playlist_download(),
build_parser() (argparse), and main() (CLI entry).  Depends on music_fetch.api (fetching) and music_fetch.audio (saving).
"""

from __future__ import annotations

__all__ = ["run_download", "run_playlist_download", "run_album_download", "build_parser", "main"]

import argparse
import logging
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from music_fetch.api import (
    DEFAULT_OUT_DIR,
    DownloadResult,
    MusicFetchError,
    fetch_account_profile,
    fetch_album_songs,
    fetch_playlist_song_ids,
    fetch_song_metadata,
    load_cookie,
    logger,
    normalize_cookie,
    parse_input_resource,
    parse_song_id,
)
from music_fetch.app_logging import default_log_path, setup_logging
from music_fetch.app_settings import (
    DEFAULT_CLI_CONCURRENCY,
    MAX_CLI_CONCURRENCY,
    SESSION_FILE,
    SUPPORTED_AUDIO_FORMATS,
)
from music_fetch.app_stores import SessionStore
from music_fetch.audio import resolve_output_path
from music_fetch.browser_login import BrowserLoginError, run_official_login
from music_fetch.error_texts import user_error_message
from music_fetch.pipeline import run_download_pipeline
from music_fetch.network import ProxyConfigError, configure_proxy


def _load_cli_cookie(cookie_file: Optional[Path]) -> str:
    """Load an explicit credential or ensure the app session is logged in.

    When the app session is missing or expired, script mode opens the same
    isolated official QR flow as the TUI.  It never inspects a normal browser
    profile.  An explicitly supplied cookie file remains a caller-owned
    override and is not copied into the app session.
    """
    if cookie_file is not None:
        return load_cookie(cookie_file)
    store = SessionStore(SESSION_FILE)
    session = store.load()
    cookie = normalize_cookie(session.cookie)
    if "MUSIC_U=" in cookie:
        try:
            fetch_account_profile(cookie, timeout=6)
            return cookie
        except MusicFetchError as err:
            if err.code != "AUTH_EXPIRED":
                return cookie
            session.cookie = ""
            session.remember_login = False
            store.save(session)

    print("应用登录凭证缺失或已过期，正在打开隔离的官网扫码窗口...", file=sys.stderr)
    try:
        cookie = normalize_cookie(run_official_login(timeout=300))
    except BrowserLoginError as err:
        raise MusicFetchError("AUTH_EXPIRED", str(err)) from err
    if "MUSIC_U=" not in cookie:
        raise MusicFetchError("AUTH_EXPIRED", "扫码登录未返回有效的 MUSIC_U 凭证，请重试。")
    fetch_account_profile(cookie, timeout=6)
    session.cookie = cookie
    session.remember_login = True
    store.save(session)
    return cookie


def run_download(
    song_url: str,
    out_dir: Path,
    cookie_file: Optional[Path] = None,
    timeout: int = 30,
    out_format: str = "mp3",
    rename: Optional[str] = None,
    retry_count: int = 1,
    download_lyric: bool = False,
    lyric_mode: str = "original",
) -> DownloadResult:
    logger.info("Run download started. out_dir=%s format=%s retry=%s", out_dir, out_format, retry_count)
    song_id = parse_song_id(song_url)
    cookie = _load_cli_cookie(cookie_file)
    song_name, meta_duration, cover_url, artist, album_name = fetch_song_metadata(song_id, cookie, timeout=timeout)
    output_path = resolve_output_path(
        out_dir=out_dir,
        song_id=song_id,
        song_name=song_name,
        rename=rename,
        out_format=out_format,
    )
    result = run_download_pipeline(
        song_id=song_id,
        cookie=cookie,
        output_path=output_path,
        target_format=out_format,
        timeout=timeout,
        retry_count=retry_count,
        tags={"title": song_name or "", "artist": artist, "album": album_name, "cover_url": cover_url},
        download_lyric=download_lyric,
        lyric_mode=lyric_mode,
    )
    actual_format = result.output_path.suffix.lstrip(".").lower()
    if actual_format and actual_format != out_format.lower():
        print(
            f"WARNING: 未检测到 ffmpeg，已按源格式 {actual_format} 保存（请求格式 {out_format}）。",
            file=sys.stderr,
        )
    logger.info(
        "Run download completed. song_id=%s output=%s size_bytes=%s duration_ms=%s",
        song_id, result.output_path, result.file_size, meta_duration,
    )
    return DownloadResult(
        song_id=song_id,
        output_path=result.output_path.resolve(),
        size_bytes=result.file_size,
        duration_ms=meta_duration,
    )


def _cli_download_one(
    index_and_song: tuple[int, str],
    *,
    total: int,
    out_dir: Path,
    cookie: str,
    timeout: int,
    out_format: str,
    retry_count: int,
    download_lyric: bool,
    lyric_mode: str,
) -> Optional[DownloadResult]:
    """Download one track for playlist/album CLI runs; prints its own progress."""
    idx, song_id = index_and_song
    print(f"[{idx}/{total}] 正在下载歌曲 {song_id} ...")
    try:
        song_name, meta_duration, cover_url, artist, album_name = fetch_song_metadata(song_id, cookie, timeout=timeout)
        output_path = resolve_output_path(
            out_dir=out_dir,
            song_id=song_id,
            song_name=song_name,
            rename=None,
            out_format=out_format,
        )
        pipeline_result = run_download_pipeline(
            song_id=song_id,
            cookie=cookie,
            output_path=output_path,
            target_format=out_format,
            timeout=timeout,
            retry_count=retry_count,
            tags={"title": song_name or "", "artist": artist, "album": album_name, "cover_url": cover_url},
            download_lyric=download_lyric,
            lyric_mode=lyric_mode,
        )
        actual_format = pipeline_result.output_path.suffix.lstrip(".").lower()
        if actual_format and actual_format != out_format.lower():
            print(
                f"  WARNING: 未检测到 ffmpeg，已按源格式 {actual_format} 保存（请求格式 {out_format}）。",
                file=sys.stderr,
            )
        result = DownloadResult(
            song_id=song_id,
            output_path=pipeline_result.output_path.resolve(),
            size_bytes=pipeline_result.file_size,
            duration_ms=meta_duration,
        )
        print(f"  SUCCESS path={result.output_path}")
        return result
    except MusicFetchError as err:
        print(f"  {err.code}: {user_error_message(err.code, err.message)}", file=sys.stderr)
        logger.warning(
            "Playlist song failed. song_id=%s code=%s message=%s",
            song_id,
            err.code,
            err.message,
        )
        return None


def _download_song_ids(
    song_ids: list[str],
    *,
    out_dir: Path,
    cookie: str,
    timeout: int,
    out_format: str,
    retry_count: int,
    download_lyric: bool,
    lyric_mode: str,
    concurrency: int,
    source: str,
) -> list[DownloadResult]:
    """Run concurrent CLI downloads for a list of song ids."""
    total = len(song_ids)
    max_workers = max(1, min(int(concurrency), MAX_CLI_CONCURRENCY))
    logger.info(
        "Batch CLI download started. source=%s song_count=%s format=%s retry=%s concurrency=%s",
        source,
        total,
        out_format,
        retry_count,
        max_workers,
    )

    def download_one(index_and_song: tuple[int, str]) -> Optional[DownloadResult]:
        return _cli_download_one(
            index_and_song,
            total=total,
            out_dir=out_dir,
            cookie=cookie,
            timeout=timeout,
            out_format=out_format,
            retry_count=retry_count,
            download_lyric=download_lyric,
            lyric_mode=lyric_mode,
        )

    if max_workers <= 1:
        ordered = [download_one(item) for item in enumerate(song_ids, start=1)]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            ordered = list(pool.map(download_one, enumerate(song_ids, start=1)))

    results = [result for result in ordered if result is not None]
    logger.info(
        "Batch CLI download completed. source=%s total=%s success=%s failed=%s",
        source,
        total,
        len(results),
        total - len(results),
    )
    return results


def run_playlist_download(
    playlist_url: str,
    out_dir: Path,
    cookie_file: Optional[Path] = None,
    timeout: int = 30,
    out_format: str = "mp3",
    retry_count: int = 1,
    download_lyric: bool = False,
    lyric_mode: str = "original",
    concurrency: int = DEFAULT_CLI_CONCURRENCY,
) -> list[DownloadResult]:
    _, playlist_id = parse_input_resource(playlist_url)
    cookie = _load_cli_cookie(cookie_file)
    song_ids = fetch_playlist_song_ids(playlist_id, cookie, timeout=timeout)
    return _download_song_ids(
        song_ids,
        out_dir=out_dir,
        cookie=cookie,
        timeout=timeout,
        out_format=out_format,
        retry_count=retry_count,
        download_lyric=download_lyric,
        lyric_mode=lyric_mode,
        concurrency=concurrency,
        source=f"playlist:{playlist_id}",
    )


def run_album_download(
    album_url: str,
    out_dir: Path,
    cookie_file: Optional[Path] = None,
    timeout: int = 30,
    out_format: str = "mp3",
    retry_count: int = 1,
    download_lyric: bool = False,
    lyric_mode: str = "original",
    concurrency: int = DEFAULT_CLI_CONCURRENCY,
) -> list[DownloadResult]:
    _, album_id = parse_input_resource(album_url)
    cookie = _load_cli_cookie(cookie_file)
    album = fetch_album_songs(album_id, cookie, timeout=timeout)
    return _download_song_ids(
        album.song_ids,
        out_dir=out_dir,
        cookie=cookie,
        timeout=timeout,
        out_format=out_format,
        retry_count=retry_count,
        download_lyric=download_lyric,
        lyric_mode=lyric_mode,
        concurrency=concurrency,
        source=f"album:{album_id}",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="music-fetch",
        description="Download NetEase Cloud Music from a song, playlist, or album URL.",
    )
    parser.add_argument(
        "--url", required=True,
        help="NetEase song, playlist, or album URL, or numeric song id.",
    )
    parser.add_argument(
        "--out", default=DEFAULT_OUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--cookie-file", default=None,
        help=(
            "Optional cookie file path. By default, reuse the app session; "
            "if missing or expired, open isolated official browser QR login."
        ),
    )
    parser.add_argument(
        "--timeout", type=int, default=30,
        help="HTTP timeout in seconds (default: 30).",
    )
    parser.add_argument(
        "--retry", type=int, default=1, dest="retry_count",
        help="Download retry count on network failure (default: 1).",
    )
    parser.add_argument(
        "--concurrency", type=int, default=DEFAULT_CLI_CONCURRENCY, dest="concurrency",
        help=f"Parallel playlist/album downloads, 1-{MAX_CLI_CONCURRENCY} (default: {DEFAULT_CLI_CONCURRENCY}).",
    )
    parser.add_argument(
        "--format", dest="out_format", default="mp3",
        choices=list(SUPPORTED_AUDIO_FORMATS),
        help=f"Output audio format (default: mp3). Supported: {', '.join(SUPPORTED_AUDIO_FORMATS)}.",
    )
    parser.add_argument(
        "--rename", default=None,
        help="Custom output filename (without extension).",
    )
    parser.add_argument(
        "--lyric", action="store_true",
        help="Download and embed lyrics (.lrc file + audio tag).",
    )
    parser.add_argument(
        "--lyric-mode", dest="lyric_mode",
        choices=["original", "translation", "bilingual"], default="original",
        help="Lyric variant when --lyric is set (default: original).",
    )
    parser.add_argument(
        "--proxy-type", choices=["direct", "http", "socks5"], default="direct",
        help="Application proxy type (default: direct).",
    )
    parser.add_argument(
        "--proxy-host", default="",
        help="Proxy hostname or IP address.",
    )
    parser.add_argument(
        "--proxy-port", type=int, default=0,
        help="Proxy port (1-65535).",
    )
    parser.add_argument(
        "--proxy-username", default="",
        help="Optional proxy username. Read the password from MUSIC_FETCH_PROXY_PASSWORD.",
    )
    parser.add_argument(
        "--log-file", default=str(default_log_path()),
        help=f"Log file path (default: {default_log_path()}).",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable verbose (INFO) logging to stdout.",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable debug (DEBUG) logging to stdout.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    log_level = logging.DEBUG if args.debug else (logging.INFO if args.verbose else logging.WARNING)
    log_path = setup_logging(Path(args.log_file), level=log_level)
    logger.info("CLI started. log_path=%s", log_path)
    try:
        proxy_fields_supplied = bool(args.proxy_host or args.proxy_port or args.proxy_username)
        if args.proxy_type == "direct" and proxy_fields_supplied:
            raise ProxyConfigError("提供了代理参数时必须指定 --proxy-type http 或 socks5。")
        configure_proxy(
            "" if args.proxy_type == "direct" else args.proxy_type,
            args.proxy_host,
            args.proxy_port,
            args.proxy_username,
            os.environ.get("MUSIC_FETCH_PROXY_PASSWORD", ""),
        )
        resource_type, resource_id = parse_input_resource(args.url)
        out_dir = Path(args.out).expanduser()
        cookie_file = Path(args.cookie_file).expanduser() if args.cookie_file else None

        if resource_type == "playlist":
            results = run_playlist_download(
                playlist_url=args.url,
                out_dir=out_dir,
                cookie_file=cookie_file,
                timeout=args.timeout,
                out_format=args.out_format,
                retry_count=args.retry_count,
                download_lyric=args.lyric,
                lyric_mode=args.lyric_mode,
                concurrency=args.concurrency,
            )
            if results:
                print(f"\n已下载 {len(results)} 首歌曲。")
            else:
                print("未成功下载任何歌曲。", file=sys.stderr)
                return 1
            return 0
        if resource_type == "album":
            results = run_album_download(
                album_url=args.url,
                out_dir=out_dir,
                cookie_file=cookie_file,
                timeout=args.timeout,
                out_format=args.out_format,
                retry_count=args.retry_count,
                download_lyric=args.lyric,
                lyric_mode=args.lyric_mode,
                concurrency=args.concurrency,
            )
            if results:
                print(f"\n已下载 {len(results)} 首歌曲。")
            else:
                print("未成功下载任何歌曲。", file=sys.stderr)
                return 1
            return 0
        else:
            result = run_download(
                song_url=args.url,
                out_dir=out_dir,
                cookie_file=cookie_file,
                timeout=args.timeout,
                out_format=args.out_format,
                rename=args.rename,
                retry_count=args.retry_count,
                download_lyric=args.lyric,
                lyric_mode=args.lyric_mode,
            )
            duration_text = str(result.duration_ms) if result.duration_ms is not None else "unknown"
            print(
                f"SUCCESS path={result.output_path} size_bytes={result.size_bytes} duration_ms={duration_text}"
            )
            logger.info("CLI succeeded. output=%s", result.output_path)
            return 0
    except ProxyConfigError as err:
        print(f"PROXY_CONFIG_ERROR: {err}", file=sys.stderr)
        logger.warning("CLI proxy configuration rejected. type=%s reason=%s", args.proxy_type, err)
        return 2
    except MusicFetchError as err:
        print(f"{err.code}: {user_error_message(err.code, err.message)}", file=sys.stderr)
        logger.warning("CLI failed with known error. code=%s message=%s", err.code, err.message)
        return 1
    except KeyboardInterrupt:
        print("UNKNOWN_ERROR: 用户中断。", file=sys.stderr)
        logger.warning("CLI interrupted by user.")
        return 1
    except (OSError, ValueError) as err:
        print(f"UNKNOWN_ERROR: {err}", file=sys.stderr)
        logger.exception("CLI failed with unexpected error.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
