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
from music_fetch.pipeline import DownloadPipelineResult, run_download_pipeline, write_audio_tags


class WriteAudioTagsTests(unittest.TestCase):
    """Tests for format-specific tag writing (MP4/MP3/Vorbis branches)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def _make_mock_audio(self, tags_dict, audio_type):
        """Create a mock mutagen audio object with given tags dict and type."""
        audio = mock.MagicMock()
        audio.tags = tags_dict
        # Make isinstance checks work by setting __class__
        audio.__class__ = audio_type
        return audio

    @mock.patch("mutagen.File")
    def test_mp3_tags_use_id3_frames(self, mock_file):
        from mutagen.mp3 import MP3
        tags = mock.MagicMock()
        audio = self._make_mock_audio(tags, MP3)
        mock_file.return_value = audio
        output_path = Path(self.tmp.name) / "test.mp3"
        output_path.write_bytes(b"fake")

        write_audio_tags(output_path, title="My Song", artist="Artist", album="Album")

        # MP3 should use TIT2/TPE1/TALB frame classes
        tags.add.assert_any_call(mock.ANY)
        audio.save.assert_called_once()

    @mock.patch("mutagen.File")
    def test_mp4_tags_use_atom_codes(self, mock_file):
        from mutagen.mp4 import MP4
        tags = {}
        audio = self._make_mock_audio(tags, MP4)
        mock_file.return_value = audio
        output_path = Path(self.tmp.name) / "test.m4a"
        output_path.write_bytes(b"fake")

        write_audio_tags(output_path, title="My Song", artist="Artist", album="Album")

        self.assertEqual(tags.get('\xa9nam'), "My Song")
        self.assertEqual(tags.get('\xa9ART'), "Artist")
        self.assertEqual(tags.get('\xa9alb'), "Album")
        audio.save.assert_called_once()

    @mock.patch("mutagen.File")
    def test_vorbis_tags_use_string_keys(self, mock_file):
        from mutagen.flac import FLAC
        tags = {}
        audio = self._make_mock_audio(tags, FLAC)
        mock_file.return_value = audio
        output_path = Path(self.tmp.name) / "test.flac"
        output_path.write_bytes(b"fake")

        write_audio_tags(output_path, title="My Song", artist="Artist", album="Album")

        self.assertEqual(tags.get('title'), "My Song")
        self.assertEqual(tags.get('artist'), "Artist")
        self.assertEqual(tags.get('album'), "Album")
        audio.save.assert_called_once()

    @mock.patch("mutagen.File")
    def test_none_audio_returns_silently(self, mock_file):
        mock_file.return_value = None
        output_path = Path(self.tmp.name) / "test.unknown"
        # Should not raise
        write_audio_tags(output_path, title="Test")

    @mock.patch("mutagen.File")
    def test_no_tags_does_not_crash(self, mock_file):
        audio = mock.MagicMock()
        audio.tags = None
        mock_file.return_value = audio
        output_path = Path(self.tmp.name) / "test.mp3"
        output_path.write_bytes(b"fake")
        # Should not raise
        write_audio_tags(output_path, title="Test")


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


class ConvertAudioFileCleanupTests(unittest.TestCase):
    """Tests for convert_audio_file exception cleanup in run_download_pipeline."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_path = Path(self.tmp.name) / "test.mp3"

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("music_fetch.pipeline.is_ffmpeg_available", return_value=True)
    @mock.patch("music_fetch.pipeline.convert_audio_file")
    @mock.patch("music_fetch.pipeline.download_song_with_fallback")
    def test_convert_failure_cleans_temp_files(self, fallback_mock, convert_mock, _ffmpeg_mock):
        from music_fetch.api import PlayableCandidate

        def fake_fallback(song_id, cookie, output_path, timeout, prefer_format, **kwargs):
            output_path.write_bytes(b"source_data")
            return PlayableCandidate(
                media_url="https://example.com/song.m4a",
                duration_ms=120000,
                level="standard",
                encode_type="m4a",
            )

        fallback_mock.side_effect = fake_fallback
        convert_mock.side_effect = OSError("ffmpeg failed")

        with self.assertRaises(OSError):
            run_download_pipeline(
                song_id="42",
                cookie="MUSIC_U=test",
                output_path=self.output_path,
                target_format="mp3",
                timeout=10,
                retry_count=0,
            )
        # output_path should be cleaned up on convert failure
        self.assertFalse(self.output_path.exists())
        # temp source should also be cleaned up
        source = self.output_path.with_name(f"{self.output_path.name}.source")
        self.assertFalse(source.exists())


if __name__ == "__main__":
    unittest.main()