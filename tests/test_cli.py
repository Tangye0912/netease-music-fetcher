"""Tests for music_fetch.cli.py — run_download, build_parser, retry_count wiring."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import music_fetch
import music_fetch.cli
from music_fetch.app_settings import SESSION_FILE
from music_fetch.app_stores import AppSession


class BuildParserTests(unittest.TestCase):
    def test_parser_has_expected_arguments(self):
        parser = music_fetch.cli.build_parser()
        # Parse minimal args to verify parser works
        args = parser.parse_args(["--url", "https://music.163.com/song?id=42"])
        self.assertEqual(args.url, "https://music.163.com/song?id=42")
        self.assertEqual(args.out_format, "mp3")
        self.assertEqual(args.retry_count, 1)
        self.assertEqual(args.timeout, 30)
        self.assertEqual(args.proxy_type, "direct")
        self.assertEqual(args.proxy_host, "")
        self.assertEqual(args.proxy_port, 0)

    def test_format_choices(self):
        parser = music_fetch.cli.build_parser()
        args = parser.parse_args(["--url", "42", "--format", "flac"])
        self.assertEqual(args.out_format, "flac")

    def test_retry_count_parsed(self):
        parser = music_fetch.cli.build_parser()
        args = parser.parse_args(["--url", "42", "--retry", "3"])
        self.assertEqual(args.retry_count, 3)

    def test_proxy_arguments_parsed(self):
        parser = music_fetch.cli.build_parser()
        args = parser.parse_args(
            [
                "--url", "42",
                "--proxy-type", "socks5",
                "--proxy-host", "127.0.0.1",
                "--proxy-port", "1080",
                "--proxy-username", "user",
            ]
        )
        self.assertEqual(args.proxy_type, "socks5")
        self.assertEqual(args.proxy_host, "127.0.0.1")
        self.assertEqual(args.proxy_port, 1080)
        self.assertEqual(args.proxy_username, "user")

    def test_concurrency_argument_parsed(self):
        parser = music_fetch.cli.build_parser()
        args = parser.parse_args(["--url", "42", "--concurrency", "4"])
        self.assertEqual(args.concurrency, 4)
        # Default stays at 1.
        defaults = parser.parse_args(["--url", "42"])
        self.assertEqual(defaults.concurrency, 1)

    def test_cookie_file_defaults_to_tui_session(self):
        parser = music_fetch.cli.build_parser()
        args = parser.parse_args(["--url", "42"])
        self.assertIsNone(args.cookie_file)


class CliSessionCookieTests(unittest.TestCase):
    @mock.patch("music_fetch.cli.run_download_pipeline")
    @mock.patch("music_fetch.cli.fetch_song_metadata")
    @mock.patch("music_fetch.cli.SessionStore")
    def test_run_download_reuses_tui_session(self, session_store_mock, meta_mock, pipeline_mock):
        session_store_mock.return_value.load.return_value = AppSession(
            cookie="MUSIC_U=session; __csrf=session-csrf"
        )
        from music_fetch.pipeline import DownloadPipelineResult

        meta_mock.return_value = ("Session Song", 120000, None, None, None)
        captured: dict[str, str] = {}

        def fake_pipeline(*, song_id, cookie, output_path, target_format, timeout, retry_count, **kwargs):
            captured["cookie"] = cookie
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"data")
            return DownloadPipelineResult(
                output_path=output_path,
                file_size=4,
                candidate=music_fetch.PlayableCandidate(
                    media_url="https://example.com/song.mp3",
                    duration_ms=120000,
                    level="standard",
                    encode_type="mp3",
                ),
                source_format="mp3",
            )

        pipeline_mock.side_effect = fake_pipeline
        with tempfile.TemporaryDirectory() as tmp:
            result = music_fetch.cli.run_download(
                song_url="https://music.163.com/song?id=42",
                out_dir=Path(tmp) / "out",
            )
            self.assertTrue(result.output_path.exists())
        self.assertEqual(captured["cookie"], "MUSIC_U=session; __csrf=session-csrf")
        session_store_mock.assert_called_once_with(SESSION_FILE)

    @mock.patch("music_fetch.cli.SessionStore")
    def test_missing_session_tells_user_to_scan_first(self, session_store_mock):
        session_store_mock.return_value.load.return_value = AppSession()
        with self.assertRaises(music_fetch.MusicFetchError) as ctx:
            music_fetch.cli._load_cli_cookie(None)
        self.assertEqual(ctx.exception.code, "AUTH_EXPIRED")
        self.assertIn("music-fetch（不带参数）", ctx.exception.message)
        self.assertIn("扫码登录", ctx.exception.message)


class RunDownloadTests(unittest.TestCase):
    @mock.patch("music_fetch.cli.run_download_pipeline")
    @mock.patch("music_fetch.cli.fetch_song_metadata")
    def test_run_download_success(self, meta_mock, pipeline_mock):
        from music_fetch.pipeline import DownloadPipelineResult
        meta_mock.return_value = ("Test Song", 120000, None, None, None)

        def fake_pipeline(*, song_id, cookie, output_path, target_format, timeout, retry_count, **kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"data")
            return DownloadPipelineResult(
                output_path=output_path,
                file_size=4,
                candidate=music_fetch.PlayableCandidate(
                    media_url="https://example.com/song.mp3",
                    duration_ms=120000,
                    level="standard",
                    encode_type="mp3",
                ),
                source_format="mp3",
            )

        pipeline_mock.side_effect = fake_pipeline

        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("MUSIC_U=abc; __csrf=def", encoding="utf-8")
            out_dir = Path(tmp) / "out"
            result = music_fetch.cli.run_download(
                song_url="https://music.163.com/song?id=42",
                out_dir=out_dir,
                cookie_file=cookie_file,
                timeout=10,
            )
            self.assertTrue(result.output_path.exists())
            self.assertEqual(result.size_bytes, 4)

    @mock.patch("music_fetch.cli.run_download_pipeline")
    @mock.patch("music_fetch.cli.fetch_song_metadata")
    def test_run_download_ffmpeg_fallback_warning(self, meta_mock, pipeline_mock):
        """When format mismatch, a warning is printed to stderr."""
        from music_fetch.pipeline import DownloadPipelineResult
        import sys, io
        meta_mock.return_value = ("Test Song", 120000, None, None, None)

        def fake_pipeline(*, song_id, cookie, output_path, target_format, timeout, retry_count, **kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            # Output .m4a instead of requested .mp3
            actual_path = output_path.with_suffix(".m4a")
            actual_path.write_bytes(b"data")
            return DownloadPipelineResult(
                output_path=actual_path,
                file_size=4,
                candidate=music_fetch.PlayableCandidate(
                    media_url="https://example.com/song.m4a",
                    duration_ms=120000, level="standard", encode_type="m4a",
                ),
                source_format="m4a",
            )

        pipeline_mock.side_effect = fake_pipeline

        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("MUSIC_U=abc; __csrf=def", encoding="utf-8")
            out_dir = Path(tmp) / "out"
            old_stderr = sys.stderr
            sys.stderr = io.StringIO()
            try:
                result = music_fetch.cli.run_download(
                    song_url="https://music.163.com/song?id=42",
                    out_dir=out_dir, cookie_file=cookie_file,
                    timeout=10, out_format="mp3",
                )
            finally:
                sys.stderr = old_stderr
            self.assertEqual(result.size_bytes, 4)


class RunPlaylistDownloadTests(unittest.TestCase):
    """Test run_playlist_download with mocked pipeline."""

    @mock.patch("music_fetch.cli.run_download_pipeline")
    @mock.patch("music_fetch.cli.fetch_song_metadata")
    @mock.patch("music_fetch.cli.fetch_playlist_song_ids")
    @mock.patch("music_fetch.cli.load_cookie")
    def test_playlist_download_success(self, _cookie_mock, ids_mock, meta_mock, pipeline_mock):
        from music_fetch.pipeline import DownloadPipelineResult
        ids_mock.return_value = ["1", "2"]
        meta_mock.return_value = ("Song", 120000, None, None, None)

        def fake_pipeline(*, song_id, cookie, output_path, target_format, timeout, retry_count, **kwargs):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"data")
            return DownloadPipelineResult(
                output_path=output_path, file_size=4,
                candidate=music_fetch.PlayableCandidate(
                    media_url="https://example.com/song.mp3",
                    duration_ms=120000, level="standard", encode_type="mp3",
                ),
                source_format="mp3",
            )

        pipeline_mock.side_effect = fake_pipeline

        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("MUSIC_U=abc; __csrf=def", encoding="utf-8")
            out_dir = Path(tmp) / "out"
            results = music_fetch.cli.run_playlist_download(
                playlist_url="https://music.163.com/playlist?id=123",
                out_dir=out_dir, cookie_file=cookie_file,
                timeout=10, out_format="mp3",
            )
            self.assertEqual(len(results), 2)

    @mock.patch("music_fetch.cli.run_download_pipeline")
    @mock.patch("music_fetch.cli.fetch_song_metadata")
    @mock.patch("music_fetch.cli.fetch_playlist_song_ids")
    @mock.patch("music_fetch.cli.load_cookie")
    def test_playlist_download_partial_failure(self, _cookie_mock, ids_mock, meta_mock, pipeline_mock):
        """One song fails, the other succeeds — should still return results."""
        from music_fetch.pipeline import DownloadPipelineResult
        from music_fetch.api import MusicFetchError
        ids_mock.return_value = ["1", "2"]
        meta_mock.return_value = ("Song", 120000, None, None, None)

        def fake_pipeline(*, song_id, cookie, output_path, target_format, timeout, retry_count, **kwargs):
            if song_id == "1":
                raise MusicFetchError("DOWNLOAD_FAILED", "fail")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"data")
            return DownloadPipelineResult(
                output_path=output_path, file_size=4,
                candidate=music_fetch.PlayableCandidate(
                    media_url="https://example.com/song.mp3",
                    duration_ms=120000, level="standard", encode_type="mp3",
                ),
                source_format="mp3",
            )

        pipeline_mock.side_effect = fake_pipeline

        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("MUSIC_U=abc; __csrf=def", encoding="utf-8")
            out_dir = Path(tmp) / "out"
            results = music_fetch.cli.run_playlist_download(
                playlist_url="https://music.163.com/playlist?id=123",
                out_dir=out_dir, cookie_file=cookie_file,
                timeout=10,
            )
            self.assertEqual(len(results), 1)

    @mock.patch("music_fetch.cli.run_download_pipeline")
    @mock.patch("music_fetch.cli.fetch_song_metadata")
    @mock.patch("music_fetch.cli.fetch_playlist_song_ids")
    @mock.patch("music_fetch.cli.load_cookie")
    def test_playlist_download_forwards_tags_and_lyric(self, _cookie_mock, ids_mock, meta_mock, pipeline_mock):
        from music_fetch.pipeline import DownloadPipelineResult
        ids_mock.return_value = ["1"]
        meta_mock.return_value = ("Song", 120000, "https://cover/x.jpg", "Artist", "Album")
        pipeline_mock.return_value = DownloadPipelineResult(
            output_path=Path("out/Song-1.mp3"),
            file_size=4,
            candidate=music_fetch.PlayableCandidate(
                media_url="https://example.com/song.mp3",
                duration_ms=120000, level="standard", encode_type="mp3",
            ),
            source_format="mp3",
        )

        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("MUSIC_U=abc; __csrf=def", encoding="utf-8")
            results = music_fetch.cli.run_playlist_download(
                playlist_url="https://music.163.com/playlist?id=123",
                out_dir=Path(tmp) / "out", cookie_file=cookie_file,
                timeout=10, download_lyric=True,
            )
            self.assertEqual(len(results), 1)
            kwargs = pipeline_mock.call_args.kwargs
            self.assertTrue(kwargs["download_lyric"])
            self.assertEqual(
                kwargs["tags"],
                {"title": "Song", "artist": "Artist", "album": "Album", "cover_url": "https://cover/x.jpg"},
            )

    @mock.patch("music_fetch.cli.fetch_song_metadata")
    @mock.patch("music_fetch.cli.fetch_playlist_song_ids")
    @mock.patch("music_fetch.cli.load_cookie")
    def test_playlist_download_respects_concurrency(self, _cookie_mock, ids_mock, meta_mock):
        import threading
        import time
        from music_fetch.pipeline import DownloadPipelineResult

        ids_mock.return_value = [str(i) for i in range(1, 7)]
        meta_mock.return_value = ("Song", 120000, None, None, None)
        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_pipeline(*, song_id, cookie, output_path, target_format, timeout, retry_count, tags=None, download_lyric=False):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.1)
            with lock:
                active -= 1
            return DownloadPipelineResult(
                output_path=output_path,
                file_size=4,
                candidate=music_fetch.PlayableCandidate(
                    media_url="https://example.com/song.mp3",
                    duration_ms=120000, level="standard", encode_type="mp3",
                ),
                source_format="mp3",
            )

        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("MUSIC_U=abc; __csrf=def", encoding="utf-8")
            with mock.patch("music_fetch.cli.run_download_pipeline", new=fake_pipeline):
                results = music_fetch.cli.run_playlist_download(
                    playlist_url="https://music.163.com/playlist?id=123",
                    out_dir=Path(tmp) / "out", cookie_file=cookie_file,
                    timeout=10, concurrency=3,
                )
            self.assertEqual(len(results), 6)
            self.assertGreater(max_active, 1)
            self.assertLessEqual(max_active, 3)


class MainTests(unittest.TestCase):
    def test_main_help_succeeds(self):
        with self.assertRaises(SystemExit) as ctx:
            music_fetch.cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_missing_url_fails(self):
        with self.assertRaises(SystemExit) as ctx:
            music_fetch.cli.main([])
        self.assertNotEqual(ctx.exception.code, 0)

    @mock.patch("music_fetch.cli.setup_logging")
    def test_main_invalid_url(self, _log_mock):
        result = music_fetch.cli.main(["--url", "not-a-valid-url-at-all"])
        self.assertEqual(result, 1)

    @mock.patch("music_fetch.cli.run_playlist_download")
    @mock.patch("music_fetch.cli.setup_logging")
    @mock.patch("music_fetch.cli.load_cookie")
    def test_main_playlist_route(self, _cookie_mock, _log_mock, playlist_mock):
        from music_fetch.api import DownloadResult
        playlist_mock.return_value = [DownloadResult(song_id="1", output_path=Path("out/song.mp3"), size_bytes=4, duration_ms=1000)]
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("MUSIC_U=abc; __csrf=def", encoding="utf-8")
            args = [
                "--url", "https://music.163.com/playlist?id=123",
                "--cookie-file", str(cookie_file),
                "--out", tmp,
            ]
            with mock.patch("music_fetch.cli.Path") as mock_path:
                mock_path.return_value.expanduser.return_value = Path(tmp)
                result = music_fetch.cli.main(args)
            self.assertEqual(result, 0)

    @mock.patch("music_fetch.cli.setup_logging")
    @mock.patch("music_fetch.cli.load_cookie")
    def test_main_playlist_empty(self, _cookie_mock, _log_mock):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("MUSIC_U=abc; __csrf=def", encoding="utf-8")
            args = [
                "--url", "https://music.163.com/playlist?id=123",
                "--cookie-file", str(cookie_file),
                "--out", tmp,
            ]
            with mock.patch("music_fetch.cli.Path") as mock_path:
                mock_path.return_value.expanduser.return_value = Path(tmp)
                with mock.patch("music_fetch.cli.run_playlist_download", return_value=[]):
                    result = music_fetch.cli.main(args)
            self.assertEqual(result, 1)

    @mock.patch("music_fetch.cli.setup_logging")
    def test_main_verbose_and_debug_flags(self, _log_mock):
        with self.assertRaises(SystemExit) as ctx:
            music_fetch.cli.main(["--url", "42", "--verbose", "--debug", "--help"])
        self.assertEqual(ctx.exception.code, 0)

    @mock.patch("music_fetch.cli.run_download")
    @mock.patch("music_fetch.cli.configure_proxy")
    @mock.patch("music_fetch.cli.setup_logging")
    def test_main_applies_authenticated_socks_proxy_from_environment(
        self, _log_mock, configure_proxy_mock, download_mock,
    ):
        from music_fetch.api import DownloadResult
        download_mock.return_value = DownloadResult(
            song_id="42", output_path=Path("out/song.mp3"), size_bytes=4, duration_ms=1000,
        )
        args = [
            "--url", "42",
            "--proxy-type", "socks5",
            "--proxy-host", "127.0.0.1",
            "--proxy-port", "1080",
            "--proxy-username", "user",
        ]
        with mock.patch.dict("os.environ", {"MUSIC_FETCH_PROXY_PASSWORD": "secret"}):
            result = music_fetch.cli.main(args)

        self.assertEqual(result, 0)
        configure_proxy_mock.assert_called_once_with(
            "socks5", "127.0.0.1", 1080, "user", "secret",
        )

    @mock.patch("music_fetch.cli.setup_logging")
    def test_main_rejects_proxy_fields_in_direct_mode(self, _log_mock):
        result = music_fetch.cli.main(
            ["--url", "42", "--proxy-host", "proxy.local", "--proxy-port", "8080"]
        )
        self.assertEqual(result, 2)

    @mock.patch("music_fetch.cli.run_download")
    @mock.patch("music_fetch.cli.setup_logging")
    @mock.patch("music_fetch.cli.load_cookie")
    def test_main_single_song_success(self, _cookie_mock, _log_mock, download_mock):
        from music_fetch.api import DownloadResult
        download_mock.return_value = DownloadResult(
            song_id="42", output_path=Path("out/song.mp3"), size_bytes=4, duration_ms=1000,
        )
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("MUSIC_U=abc; __csrf=def", encoding="utf-8")
            args = [
                "--url", "https://music.163.com/song?id=42",
                "--cookie-file", str(cookie_file),
                "--out", tmp,
            ]
            with mock.patch("music_fetch.cli.Path") as mock_path:
                mock_path.return_value.expanduser.return_value = Path(tmp)
                result = music_fetch.cli.main(args)
            self.assertEqual(result, 0)

    @mock.patch("music_fetch.cli.setup_logging")
    @mock.patch("music_fetch.cli.load_cookie")
    def test_main_keyboard_interrupt(self, _cookie_mock, _log_mock):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("MUSIC_U=abc; __csrf=def", encoding="utf-8")
            args = [
                "--url", "https://music.163.com/song?id=42",
                "--cookie-file", str(cookie_file),
                "--out", tmp,
            ]
            with mock.patch("music_fetch.cli.Path") as mock_path:
                mock_path.return_value.expanduser.return_value = Path(tmp)
                with mock.patch("music_fetch.cli.run_download", side_effect=KeyboardInterrupt):
                    result = music_fetch.cli.main(args)
            self.assertEqual(result, 1)

    @mock.patch("music_fetch.cli.setup_logging")
    @mock.patch("music_fetch.cli.load_cookie")
    def test_main_os_error(self, _cookie_mock, _log_mock):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("MUSIC_U=abc; __csrf=def", encoding="utf-8")
            args = [
                "--url", "https://music.163.com/song?id=42",
                "--cookie-file", str(cookie_file),
                "--out", tmp,
            ]
            with mock.patch("music_fetch.cli.Path") as mock_path:
                mock_path.return_value.expanduser.return_value = Path(tmp)
                with mock.patch("music_fetch.cli.run_download", side_effect=OSError("permission denied")):
                    result = music_fetch.cli.main(args)
            self.assertEqual(result, 1)

    @mock.patch("music_fetch.cli.setup_logging")
    def test_main_lyric_flag(self, _log_mock):
        with self.assertRaises(SystemExit) as ctx:
            music_fetch.cli.main(["--url", "42", "--lyric", "--help"])
        self.assertEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
