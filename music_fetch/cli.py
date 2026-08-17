"""
Command-line interface for music-fetch.

Provides run_download() (script-friendly API), run_playlist_download(),
build_parser() (argparse), and main() (CLI entry).  Depends on music_fetch.api (fetching) and music_fetch.audio (saving).
"""

from __future__ import annotations

__all__ = ["run_download", "run_playlist_download", "build_parser", "main"]

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
from music_fetch.pipeline import run_download_pipeline
from music_fetch.network import ProxyConfigError, configure_proxy


def _load_cli_cookie(cookie_file: Optional[Path]) -> str:
    """Load the CLI credential from an explicit cookie file or the TUI session.

    The normal flow is: run `music-fetch` without arguments, scan the QR code
    once in the TUI, then reuse that saved session in script mode.  Users
    never need to visit the NetEase website or copy cookies from a browser.
    """
    if cookie_file is not None:
        return load_cookie(cookie_file)
    session = SessionStore(SESSION_FILE).load()
    cookie = normalize_cookie(session.cookie)
    if "MUSIC_U=" not in cookie:
        raise MusicFetchError(
            "AUTH_EXPIRED",
            "尚未登录：请先运行 music-fetch（不带参数）完成扫码登录，登录状态会自动保存并供脚本模式复用。",
        )
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
    )
    actual_format = result.output_path.suffix.lstrip(".").lower()
    if actual_format and actual_format != out_format.lower():
        print(
            f"WARNING: ffmpeg not available, output saved as {actual_format} "
            f"instead of requested {out_format}.",
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


def run_playlist_download(
    playlist_url: str,
    out_dir: Path,
    cookie_file: Optional[Path] = None,
    timeout: int = 30,
    out_format: str = "mp3",
    retry_count: int = 1,
    download_lyric: bool = False,
    concurrency: int = DEFAULT_CLI_CONCURRENCY,
) -> list[DownloadResult]:
    _, playlist_id = parse_input_resource(playlist_url)
    cookie = _load_cli_cookie(cookie_file)
    song_ids = fetch_playlist_song_ids(playlist_id, cookie, timeout=timeout)
    total = len(song_ids)
    max_workers = max(1, min(int(concurrency), MAX_CLI_CONCURRENCY))
    logger.info(
        "Playlist download started. playlist_id=%s song_count=%s format=%s retry=%s concurrency=%s",
        playlist_id,
        total,
        out_format,
        retry_count,
        max_workers,
    )

    def download_one(index_and_song: tuple[int, str]) -> Optional[DownloadResult]:
        idx, song_id = index_and_song
        print(f"[{idx}/{total}] Downloading song {song_id} ...")
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
            )
            actual_format = pipeline_result.output_path.suffix.lstrip(".").lower()
            if actual_format and actual_format != out_format.lower():
                print(
                    f"  WARNING: ffmpeg not available, saved as {actual_format} "
                    f"instead of {out_format}.",
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
            print(f"  {err.code}: {err.message}", file=sys.stderr)
            logger.warning(
                "Playlist song failed. song_id=%s code=%s message=%s",
                song_id,
                err.code,
                err.message,
            )
            return None

    if max_workers <= 1:
        ordered = [download_one(item) for item in enumerate(song_ids, start=1)]
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            ordered = list(pool.map(download_one, enumerate(song_ids, start=1)))

    results = [result for result in ordered if result is not None]
    logger.info(
        "Playlist download completed. total=%s success=%s failed=%s",
        total,
        len(results),
        total - len(results),
    )
    return results


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="music-fetch",
        description="Fetch a playable NetEase Cloud Music track by song URL or playlist URL.",
    )
    parser.add_argument(
        "--url", required=True,
        help="NetEase song URL, playlist URL, or numeric song id.",
    )
    parser.add_argument(
        "--out", default=DEFAULT_OUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUT_DIR}).",
    )
    parser.add_argument(
        "--cookie-file", default=None,
        help="Optional cookie file path. By default, reuse the session saved by TUI QR login.",
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
        help=f"Parallel playlist downloads, 1-{MAX_CLI_CONCURRENCY} (default: {DEFAULT_CLI_CONCURRENCY}).",
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
            raise ProxyConfigError("Select --proxy-type http or socks5 when proxy fields are provided.")
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
                concurrency=args.concurrency,
            )
            if results:
                print(f"\nDownloaded {len(results)} songs.")
            else:
                print("No songs were downloaded successfully.", file=sys.stderr)
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
        print(f"{err.code}: {err.message}", file=sys.stderr)
        logger.warning("CLI failed with known error. code=%s message=%s", err.code, err.message)
        return 1
    except KeyboardInterrupt:
        print("UNKNOWN_ERROR: Interrupted by user.", file=sys.stderr)
        logger.warning("CLI interrupted by user.")
        return 1
    except (OSError, ValueError) as err:
        print(f"UNKNOWN_ERROR: {err}", file=sys.stderr)
        logger.exception("CLI failed with unexpected error.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
