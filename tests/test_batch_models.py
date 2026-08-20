"""Tests for music_fetch.batch_models.py — format_duration, format_bytes,
probe_media_size_bytes, and BatchDetectRow."""

import unittest
from email.message import Message
from unittest import mock

from music_fetch.batch_models import (
    BatchDetectRow,
    format_bytes,
    format_duration,
    probe_media_size_bytes,
)


class FormatDurationTests(unittest.TestCase):
    def test_none_returns_unknown(self):
        self.assertEqual(format_duration(None), "未知")

    def test_zero_ms(self):
        self.assertEqual(format_duration(0), "00:00")

    def test_seconds_only(self):
        self.assertEqual(format_duration(45000), "00:45")

    def test_minutes_and_seconds(self):
        self.assertEqual(format_duration(185000), "03:05")

    def test_hours(self):
        self.assertEqual(format_duration(3723000), "01:02:03")

    def test_negative_clamped_to_zero(self):
        self.assertEqual(format_duration(-1000), "00:00")


class FormatBytesTests(unittest.TestCase):
    def test_zero_bytes(self):
        self.assertEqual(format_bytes(0), "0.0B")

    def test_bytes(self):
        self.assertEqual(format_bytes(512), "512.0B")

    def test_kilobytes(self):
        self.assertEqual(format_bytes(1536), "1.5KB")

    def test_megabytes(self):
        self.assertEqual(format_bytes(1572864), "1.5MB")

    def test_gigabytes(self):
        self.assertEqual(format_bytes(1610612736), "1.5GB")

    def test_negative_clamped_to_zero(self):
        self.assertEqual(format_bytes(-100), "0.0B")


class ProbeMediaSizeBytesTests(unittest.TestCase):
    def test_empty_url_returns_zero(self):
        self.assertEqual(probe_media_size_bytes(""), 0)

    def test_head_request_returns_content_length(self):
        with mock.patch("music_fetch.batch_models.request.urlopen") as mock_urlopen:
            mock_resp = mock.MagicMock()
            mock_resp.headers = {"Content-Length": "12345"}
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            result = probe_media_size_bytes("https://example.com/song.mp4")
            self.assertEqual(result, 12345)

    def test_head_request_non_digit_does_range_fallback(self):
        with mock.patch("music_fetch.batch_models.request.urlopen") as mock_urlopen:
            mock_resp = mock.MagicMock()
            mock_resp.headers = {"Content-Length": "unknown"}
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            result = probe_media_size_bytes("https://example.com/song.mp4")
            self.assertEqual(result, 0)

    def test_head_request_404_does_range_fallback(self):
        from urllib.error import HTTPError

        call_count = [0]

        def urlopen_side_effect(req, timeout):
            call_count[0] += 1
            if call_count[0] == 1:
                raise HTTPError("url", 404, "Not Found", Message(), None)
            mock_resp = mock.MagicMock()
            mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = mock.MagicMock(return_value=None)
            mock_resp.headers = {"Content-Range": "bytes 0-0/99999"}
            return mock_resp

        with mock.patch("music_fetch.batch_models.request.urlopen", side_effect=urlopen_side_effect):
            result = probe_media_size_bytes("https://example.com/song.mp4")
            self.assertEqual(result, 99999)

    def test_both_requests_fail_returns_zero(self):
        from urllib.error import URLError

        with mock.patch("music_fetch.batch_models.request.urlopen", side_effect=URLError("timeout")):
            result = probe_media_size_bytes("https://example.com/song.mp4")
            self.assertEqual(result, 0)


class BatchDetectRowTests(unittest.TestCase):
    def test_default_values(self):
        row = BatchDetectRow(raw_input="https://music.163.com/song?id=1")
        self.assertEqual(row.raw_input, "https://music.163.com/song?id=1")
        self.assertEqual(row.source_type, "unknown")
        self.assertEqual(row.source_label, "")
        self.assertEqual(row.song_id, "")
        self.assertEqual(row.song_name, "")
        self.assertEqual(row.status, "failed")
        self.assertEqual(row.message, "")
        self.assertEqual(row.media_size_bytes, 0)
        self.assertFalse(row.selected)

    def test_full_construction(self):
        row = BatchDetectRow(
            raw_input="https://music.163.com/song?id=42",
            source_type="song",
            source_label="歌曲-Test",
            song_id="42",
            song_name="Test Song",
            status="ready",
            message="",
            media_size_bytes=1024000,
            selected=True,
        )
        self.assertEqual(row.song_id, "42")
        self.assertEqual(row.status, "ready")
        self.assertTrue(row.selected)
        self.assertEqual(row.media_size_bytes, 1024000)


if __name__ == "__main__":
    unittest.main()