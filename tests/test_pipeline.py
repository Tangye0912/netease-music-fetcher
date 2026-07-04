"""Tests for music_fetch/pipeline.py — run_download_pipeline."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from music_fetch.api import (
    DownloadCanceled,
    MusicFetchError,
    PlayableCandidate,
)
from music_fetch.pipeline import DownloadPipelineResult, run_download_pipeline


class RunDownloadPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_path = Path(self.tmp.name) / "test.mp3"

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_success(self, fallback_mock):
        def fake_fallback(song_id, cookie, output_path, timeout, prefer_format, **kwargs):
            output_path.write_bytes(b"data")
            return PlayableCandidate(
                media_url="https://example.com/song.mp3",
                duration_ms=120000,
                level="standard",
                encode_type="mp3",
            )

        fallback_mock.side_effect = fake_fallback

        result = run_download_pipeline(
            song_id="42",
            cookie="MUSIC_U=test",
            output_path=self.output_path,
            target_format="mp3",
            timeout=10,
            retry_count=1,
        )
        self.assertIsInstance(result, DownloadPipelineResult)
        self.assertTrue(result.output_path.exists())
        self.assertEqual(result.file_size, 4)
        self.assertEqual(result.source_format, "mp3")

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_retry_on_failure(self, fallback_mock):
        call_count = [0]

        def fake_fallback(song_id, cookie, output_path, timeout, prefer_format, **kwargs):
            call_count[0] += 1
            if call_count[0] <= 2:
                raise MusicFetchError("DOWNLOAD_FAILED", "test error")
            output_path.write_bytes(b"data")
            return PlayableCandidate(
                media_url="https://example.com/song.mp3",
                duration_ms=120000,
                level="standard",
                encode_type="mp3",
            )

        fallback_mock.side_effect = fake_fallback

        result = run_download_pipeline(
            song_id="42",
            cookie="MUSIC_U=test",
            output_path=self.output_path,
            target_format="mp3",
            timeout=10,
            retry_count=2,
        )
        self.assertEqual(call_count[0], 3)
        self.assertTrue(result.output_path.exists())

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_exhausts_retries(self, fallback_mock):
        fallback_mock.side_effect = MusicFetchError("DOWNLOAD_FAILED", "always fail")

        with self.assertRaises(MusicFetchError):
            run_download_pipeline(
                song_id="42",
                cookie="MUSIC_U=test",
                output_path=self.output_path,
                target_format="mp3",
                timeout=10,
                retry_count=1,
            )

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_cancel_during_pipeline(self, fallback_mock):
        def fake_fallback(song_id, cookie, output_path, timeout, prefer_format, cancel_checker=None, **kwargs):
            if cancel_checker and cancel_checker():
                raise DownloadCanceled()
            output_path.write_bytes(b"data")
            return PlayableCandidate(
                media_url="https://example.com/song.mp3",
                duration_ms=120000,
                level="standard",
                encode_type="mp3",
            )

        fallback_mock.side_effect = fake_fallback
        cancel_called = [False]

        def cancel_checker():
            cancel_called[0] = True
            return True

        with self.assertRaises(DownloadCanceled):
            run_download_pipeline(
                song_id="42",
                cookie="MUSIC_U=test",
                output_path=self.output_path,
                target_format="mp3",
                timeout=10,
                retry_count=1,
                cancel_checker=cancel_checker,
            )

    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    @mock.patch("music_fetch.pipeline.Path.mkdir")
    def test_unwritable_directory(self, mkdir_mock, fallback_mock):
        mkdir_mock.side_effect = PermissionError("Permission denied")
        with self.assertRaises(MusicFetchError) as ctx:
            run_download_pipeline(
                song_id="42",
                cookie="MUSIC_U=test",
                output_path=self.output_path,
                target_format="mp3",
                timeout=10,
                retry_count=1,
            )
        self.assertIn("Cannot write", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()