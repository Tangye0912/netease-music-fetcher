"""
Command-line interface for music-fetch.

Provides run_download() (script-friendly API), build_parser() (argparse),
and main() (CLI entry).  Depends on _api (fetching) and _audio (saving).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional

from _api import (
    DEFAULT_COOKIE_FILE,
    DEFAULT_OUT_DIR,
    DownloadResult,
    MusicFetchError,
    fetch_playable_url,
    fetch_song_metadata,
    load_cookie,
    logger,
    parse_song_id,
)
from app_logging import default_log_path, setup_logging
from _audio import download_audio_with_progress, resolve_output_path


def run_download(song_url: str, out_dir: Path, cookie_file: Path, timeout: int = 30) -> DownloadResult:
    logger.info("Run download started. out_dir=%s", out_dir)
    song_id = parse_song_id(song_url)
    cookie = load_cookie(cookie_file)
    media_url, media_duration = fetch_playable_url(song_id, cookie, timeout=timeout)
    song_name, meta_duration = fetch_song_metadata(song_id, cookie, timeout=timeout)
    output_path = resolve_output_path(out_dir=out_dir, song_id=song_id, song_name=song_name, rename=None, out_format="mp4")
    download_audio_with_progress(media_url=media_url, output_path=output_path, timeout=timeout, progress_callback=None, cancel_checker=None, cookie=cookie)
    size_bytes = output_path.stat().st_size
    duration_ms = meta_duration if meta_duration is not None else media_duration
    logger.info("Run download completed. song_id=%s output=%s size_bytes=%s duration_ms=%s", song_id, output_path, size_bytes, duration_ms)
    return DownloadResult(song_id=song_id, output_path=output_path.resolve(), size_bytes=size_bytes, duration_ms=duration_ms)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="music-fetch", description="Fetch a playable NetEase Cloud Music track by song URL.")
    parser.add_argument("--url", required=True, help="NetEase song URL or numeric song id.")
    parser.add_argument("--out", default=DEFAULT_OUT_DIR, help=f"Output directory (default: {DEFAULT_OUT_DIR}).")
    parser.add_argument("--cookie-file", default=DEFAULT_COOKIE_FILE, help=f"Cookie file path (default: {DEFAULT_COOKIE_FILE}).")
    parser.add_argument("--timeout", type=int, default=30, help="HTTP timeout in seconds (default: 30).")
    parser.add_argument("--log-file", default=str(default_log_path()), help=f"Log file path (default: {default_log_path()}).")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    log_path = setup_logging(Path(args.log_file))
    logger.info("CLI started. log_path=%s", log_path)
    try:
        result = run_download(song_url=args.url, out_dir=Path(args.out).expanduser(), cookie_file=Path(args.cookie_file).expanduser(), timeout=args.timeout)
        duration_text = str(result.duration_ms) if result.duration_ms is not None else "unknown"
        print(f"SUCCESS path={result.output_path} size_bytes={result.size_bytes} duration_ms={duration_text}")
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
    except Exception as err:
        print(f"UNKNOWN_ERROR: {err}", file=sys.stderr)
        logger.exception("CLI failed with unexpected error.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
