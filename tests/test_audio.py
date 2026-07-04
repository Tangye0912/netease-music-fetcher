"""Tests for music_fetch.audio.py download stream logic."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import music_fetch.audio
from music_fetch.api import DownloadCanceled, MusicFetchError


class DownloadAudioStreamTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.output_path = Path(self.tmpdir.name) / "song.mp3"

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_build_attempt_headers_without_cookie(self):
        attempts = music_fetch.audio._build_download_attempt_headers("")
        self.assertEqual(len(attempts), 3)
        for headers in attempts:
            self.assertIn("User-Agent", headers)
            self.assertIn("Accept", headers)
            self.assertIn("Range", headers)

    def test_build_attempt_headers_with_cookie(self):
        attempts = music_fetch.audio._build_download_attempt_headers("MUSIC_U=abc")
        self.assertEqual(len(attempts), 4)
        cookie_attempt = attempts[-1]
        self.assertIn("Cookie", cookie_attempt)
        self.assertEqual(cookie_attempt["Cookie"], "MUSIC_U=abc")

    def test_candidate_media_urls_adds_http_fallback_for_https_cdn(self):
        urls = music_fetch.audio._candidate_media_urls("https://m801.music.126.net/abc.mp3")
        self.assertEqual(len(urls), 2)
        self.assertEqual(urls[0], "https://m801.music.126.net/abc.mp3")
        self.assertEqual(urls[1], "http://m801.music.126.net/abc.mp3")

    def test_candidate_media_urls_no_fallback_for_non_cdn(self):
        urls = music_fetch.audio._candidate_media_urls("https://example.com/abc.mp3")
        self.assertEqual(len(urls), 1)
        self.assertEqual(urls[0], "https://example.com/abc.mp3")

    def test_candidate_media_urls_http_no_double(self):
        # HTTP CDN URL gets normalized to HTTPS first, then HTTP fallback is added
        urls = music_fetch.audio._candidate_media_urls("http://m801.music.126.net/abc.mp3")
        # normalize_media_url upgrades http->https, then candidate adds http fallback
        self.assertEqual(urls[0], "https://m801.music.126.net/abc.mp3")
        self.assertEqual(urls[1], "http://m801.music.126.net/abc.mp3")
        self.assertEqual(len(urls), 2)

    def test_download_success_first_attempt(self):
        fake_resp = mock.MagicMock()
        fake_resp.status = 200
        fake_resp.getcode.return_value = 200
        fake_resp.__enter__.return_value = fake_resp
        fake_resp.__exit__.return_value = False
        fake_resp.headers = {"Content-Length": "100"}
        fake_resp.read.side_effect = [b"aaaa", b""]

        with mock.patch("urllib.request.urlopen", return_value=fake_resp):
            music_fetch.audio._download_audio_stream(
                "https://m801.music.126.net/abc.mp3",
                self.output_path,
                timeout=10,
                progress_callback=None,
                cancel_checker=None,
                cookie="",
            )

        self.assertTrue(self.output_path.exists())
        self.assertEqual(self.output_path.read_bytes(), b"aaaa")
        self.assertFalse(self.output_path.with_name(f"{self.output_path.name}.part").exists())

    def test_download_403_retries_with_next_header(self):
        import urllib.error
        fake_403 = urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
        fake_403.read.return_value = b""

        fake_ok = mock.MagicMock()
        fake_ok.status = 200
        fake_ok.getcode.return_value = 200
        fake_ok.__enter__.return_value = fake_ok
        fake_ok.__exit__.return_value = False
        fake_ok.headers = {}
        fake_ok.read.side_effect = [b"bbbb", b""]

        with mock.patch("urllib.request.urlopen", side_effect=[fake_403, fake_ok]):
            music_fetch.audio._download_audio_stream(
                "https://m801.music.126.net/abc.mp3",
                self.output_path,
                timeout=10,
                progress_callback=None,
                cancel_checker=None,
                cookie="",
            )

        self.assertTrue(self.output_path.exists())
        self.assertEqual(self.output_path.read_bytes(), b"bbbb")

    def test_download_all_403_raises(self):
        import urllib.error
        fake_403 = urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
        fake_403.read.return_value = b""

        with mock.patch("urllib.request.urlopen", side_effect=fake_403):
            with self.assertRaises(MusicFetchError) as ctx:
                music_fetch.audio._download_audio_stream(
                    "https://m801.music.126.net/abc.mp3",
                    self.output_path,
                    timeout=10,
                    progress_callback=None,
                    cancel_checker=None,
                    cookie="",
                )
            self.assertEqual(ctx.exception.code, "DOWNLOAD_FAILED")
            self.assertIn("HTTP 403", ctx.exception.message)

    def test_download_cancel_raises_canceled(self):
        fake_resp = mock.MagicMock()
        fake_resp.status = 200
        fake_resp.getcode.return_value = 200
        fake_resp.__enter__.return_value = fake_resp
        fake_resp.__exit__.return_value = False
        fake_resp.headers = {}
        fake_resp.read.side_effect = [b"aaaa", b"bbbb", b""]

        cancel_count = [0]

        def canceller():
            cancel_count[0] += 1
            return cancel_count[0] >= 2  # cancel after 2 chunks

        with mock.patch("urllib.request.urlopen", return_value=fake_resp):
            with self.assertRaises(DownloadCanceled):
                music_fetch.audio._download_audio_stream(
                    "https://m801.music.126.net/abc.mp3",
                    self.output_path,
                    timeout=10,
                    progress_callback=None,
                    cancel_checker=canceller,
                    cookie="",
                )

        self.assertFalse(self.output_path.exists())
        self.assertFalse(self.output_path.with_name(f"{self.output_path.name}.part").exists())

    def test_download_network_error_retries(self):
        import urllib.error
        fake_net_err = urllib.error.URLError("connection refused")
        fake_net_err.__enter__ = mock.MagicMock(return_value=fake_net_err)
        fake_net_err.__exit__ = mock.MagicMock(return_value=False)

        fake_ok = mock.MagicMock()
        fake_ok.status = 200
        fake_ok.getcode.return_value = 200
        fake_ok.__enter__.return_value = fake_ok
        fake_ok.__exit__.return_value = False
        fake_ok.headers = {}
        fake_ok.read.side_effect = [b"cccc", b""]

        with mock.patch("urllib.request.urlopen", side_effect=[fake_net_err, fake_ok]):
            music_fetch.audio._download_audio_stream(
                "https://m801.music.126.net/abc.mp3",
                self.output_path,
                timeout=10,
                progress_callback=None,
                cancel_checker=None,
                cookie="",
            )

        self.assertTrue(self.output_path.exists())
        self.assertEqual(self.output_path.read_bytes(), b"cccc")

    def test_url_for_log_masks_tokens(self):
        url = "https://m801.music.126.net/abc.mp3?token=secret123&expire=1000&authsecret=abc"
        safe = music_fetch.audio._url_for_log(url)
        self.assertIn("token=***", safe)
        self.assertIn("authsecret=***", safe)
        self.assertNotIn("secret123", safe)
        self.assertNotIn("abc", safe.split("authsecret")[1] if "authsecret" in safe else "")

    def test_download_uses_http_fallback_when_https_fails(self):
        import urllib.error
        fake_403 = urllib.error.HTTPError("url", 403, "Forbidden", {}, None)
        fake_403.read.return_value = b""

        fake_ok = mock.MagicMock()
        fake_ok.status = 200
        fake_ok.getcode.return_value = 200
        fake_ok.__enter__.return_value = fake_ok
        fake_ok.__exit__.return_value = False
        fake_ok.headers = {}
        fake_ok.read.side_effect = [b"dddd", b""]

        # 3 header attempts on https URL all fail (403) -> then 3 more on http URL
        # First http attempt succeeds
        with mock.patch("urllib.request.urlopen", side_effect=[
            fake_403, fake_403, fake_403,  # https attempts
            fake_ok,  # http first attempt succeeds
        ]):
            music_fetch.audio._download_audio_stream(
                "https://m801.music.126.net/abc.mp3",
                self.output_path,
                timeout=10,
                progress_callback=None,
                cancel_checker=None,
                cookie="",
            )

        self.assertTrue(self.output_path.exists())
        self.assertEqual(self.output_path.read_bytes(), b"dddd")


if __name__ == "__main__":
    unittest.main()