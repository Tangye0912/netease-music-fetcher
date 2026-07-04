"""
Command-line interface for music-fetch.

Provides run_download() (script-friendly API), run_playlist_download(),
build_parser() (argparse), and main() (CLI entry).  Depends on _api
(fetching) and _audio (saving).
"""

from __future__ import annotations

__all__ = ["run_download", "run_playlist_download", "build_parser", "main"]

import argparse
import sys
from pathlib import Path
from typing import Optional

from music_fetch.api import (
    DEFAULT_COOKIE_FILE,
    DEFAULT_OUT_DIR,
    DownloadResult,
    MusicFetchError,
    fetch_playlist_song_ids,
    fetch_song_metadata,
    load_cookie,
    logger,
    parse_input_resource,
    parse_song_id,
)
from music_fetch.app_logging import default_log_path, setup_logging
from music_fetch.app_settings import SUPPORTED_AUDIO_FORMATS
from music_fetch.audio import resolve_output_path
from music_fetch.pipeline import run_download_pipeline


def run_download(
    song_url: str,
    out_dir: Path,
    cookie_file: Path,
    timeout: int = 30,
    out_format: str = "mp3",
    rename: Optional[str] = None,
    retry_count: int = 1,
) -> DownloadResult:
    logger.info("Run download started. out_dir=%s format=%s retry=%s", out_dir, out_format, retry_count)
    song_id = parse_song_id(song_url)
    cookie = load_cookie(cookie_file)
    song_name, meta_duration = fetch_song_metadata(song_id, cookie, timeout=timeout)
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
    cookie_file: Path,
    timeout: int = 30,
    out_format: str = "mp3",
    retry_count: int = 1,
) -> list[DownloadResult]:
    _, playlist_id = parse_input_resource(playlist_url)
    cookie = load_cookie(cookie_file)
    song_ids = fetch_playlist_song_ids(playlist_id, cookie, timeout=timeout)
    logger.info(
        "Playlist download started. playlist_id=%s song_count=%s format=%s retry=%s",
        playlist_id,
        len(song_ids),
        out_format,
        retry_count,
    )
    results: list[DownloadResult] = []
    for idx, song_id in enumerate(song_ids, start=1):
        print(f"[{idx}/{len(song_ids)}] Downloading song {song_id} ...")
        try:
            song_name, meta_duration = fetch_song_metadata(song_id, cookie, timeout=timeout)
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
            )
            result = DownloadResult(
                song_id=song_id,
                output_path=pipeline_result.output_path.resolve(),
                size_bytes=pipeline_result.file_size,
                duration_ms=meta_duration,
            )
            results.append(result)
            print(f"  SUCCESS path={result.output_path}")
        except MusicFetchError as err:
            print(f"  {err.code}: {err.message}", file=sys.stderr)
            logger.warning(
                "Playlist song failed. song_id=%s code=%s message=%s",
                song_id,
                err.code,
                err.message,
            )
    logger.info(
        "Playlist download completed. total=%s success=%s failed=%s",
        len(song_ids),
        len(results),
        len(song_ids) - len(results),
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
        "--cookie-file", default=DEFAULT_COOKIE_FILE,
        help=f"Cookie file path (default: {DEFAULT_COOKIE_FILE}).",
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
        "--format", dest="out_format", default="mp3",
        choices=list(SUPPORTED_AUDIO_FORMATS),
        help=f"Output audio format (default: mp3). Supported: {', '.join(SUPPORTED_AUDIO_FORMATS)}.",
    )
    parser.add_argument(
        "--rename", default=None,
        help="Custom output filename (without extension).",
    )
    parser.add_argument(
        "--log-file", default=str(default_log_path()),
        help=f"Log file path (default: {default_log_path()}).",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    log_path = setup_logging(Path(args.log_file))
    logger.info("CLI started. log_path=%s", log_path)
    try:
        resource_type, resource_id = parse_input_resource(args.url)
        out_dir = Path(args.out).expanduser()
        cookie_file = Path(args.cookie_file).expanduser()

        if resource_type == "playlist":
            results = run_playlist_download(
                playlist_url=args.url,
                out_dir=out_dir,
                cookie_file=cookie_file,
                timeout=args.timeout,
                out_format=args.out_format,
                retry_count=args.retry_count,
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
            )
            duration_text = str(result.duration_ms) if result.duration_ms is not None else "unknown"
            print(
                f"SUCCESS path={result.output_path} size_bytes={result.size_bytes} duration_ms={duration_text}"
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
    except (OSError, ValueError) as err:
        print(f"UNKNOWN_ERROR: {err}", file=sys.stderr)
        logger.exception("CLI failed with unexpected error.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())