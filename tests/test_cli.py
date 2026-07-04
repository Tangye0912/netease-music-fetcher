"""Tests for music_fetch.cli.py — run_download, build_parser, retry_count wiring."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import music_fetch.cli
import music_fetch


class BuildParserTests(unittest.TestCase):
    def test_parser_has_expected_arguments(self):
        parser = music_fetch.cli.build_parser()
        # Parse minimal args to verify parser works
        args = parser.parse_args(["--url", "https://music.163.com/song?id=42"])
        self.assertEqual(args.url, "https://music.163.com/song?id=42")
        self.assertEqual(args.out_format, "mp3")
        self.assertEqual(args.retry_count, 1)
        self.assertEqual(args.timeout, 30)

    def test_format_choices(self):
        parser = music_fetch.cli.build_parser()
        args = parser.parse_args(["--url", "42", "--format", "flac"])
        self.assertEqual(args.out_format, "flac")

    def test_retry_count_parsed(self):
        parser = music_fetch.cli.build_parser()
        args = parser.parse_args(["--url", "42", "--retry", "3"])
        self.assertEqual(args.retry_count, 3)


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


class MainTests(unittest.TestCase):
    def test_main_help_succeeds(self):
        with self.assertRaises(SystemExit) as ctx:
            music_fetch.cli.main(["--help"])
        self.assertEqual(ctx.exception.code, 0)

    def test_main_missing_url_fails(self):
        with self.assertRaises(SystemExit) as ctx:
            music_fetch.cli.main([])
        self.assertNotEqual(ctx.exception.code, 0)


if __name__ == "__main__":
    unittest.main()