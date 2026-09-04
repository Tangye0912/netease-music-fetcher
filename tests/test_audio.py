"""Tests for music_fetch.audio.py download stream logic."""
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

import music_fetch.audio
from music_fetch.api import DownloadCanceled, MusicFetchError
from music_fetch.audio import sanitize_filename


class SanitizeFilenameTests(unittest.TestCase):
    def test_replaces_invalid_characters(self):
        self.assertEqual(sanitize_filename('a/b\\c:d*e?f"g<h>i|j'), "a_b_c_d_e_f_g_h_i_j")

    def test_strips_dots_and_whitespace(self):
        self.assertEqual(sanitize_filename("  .name. "), "name")
        self.assertEqual(sanitize_filename("a  b"), "a b")

    def test_empty_falls_back_to_song(self):
        self.assertEqual(sanitize_filename("   "), "song")
        self.assertEqual(sanitize_filename("..."), "song")

    def test_windows_reserved_names_get_prefixed(self):
        self.assertEqual(sanitize_filename("CON"), "_CON")
        self.assertEqual(sanitize_filename("con.mp3"), "_con.mp3")
        self.assertEqual(sanitize_filename("Com1"), "_Com1")
        self.assertEqual(sanitize_filename("lpt9"), "_lpt9")
        # Names merely containing a reserved word are untouched.
        self.assertEqual(sanitize_filename("console"), "console")
        self.assertEqual(sanitize_filename("AUX_x"), "AUX_x")

    def test_control_characters_removed(self):
        self.assertEqual(sanitize_filename("a\x00b\x1fc"), "abc")


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
        fake_403 = urllib.error.HTTPError("url", 403, "Forbidden", Message(), None)
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
        fake_403 = urllib.error.HTTPError("url", 403, "Forbidden", Message(), None)
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
        fake_403 = urllib.error.HTTPError("url", 403, "Forbidden", Message(), None)
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


class DownloadStreamResumeTests(unittest.TestCase):
    """Test _download_audio_stream resume / partial download logic."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_path = Path(self.tmp.name) / "song.mp3"

    def tearDown(self):
        self.tmp.cleanup()

    def test_resume_from_partial(self):
        """When a .part file exists, resume from its offset."""
        part_path = self.output_path.with_name("song.mp3.part")
        part_path.write_bytes(b"aaaa")  # 4 bytes already downloaded

        # Mock a response that returns 206 + "bbbb"
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 206
        mock_resp.headers = {"Content-Length": "4"}
        # Simulate reading 4 more bytes
        mock_resp.read.side_effect = [b"bbbb", b""]

        with mock.patch("music_fetch.audio.request.urlopen", return_value=mock_resp):
            music_fetch.audio._download_audio_stream(
                "https://example.com/song.mp3",
                self.output_path, timeout=10,
                progress_callback=None, cancel_checker=None, cookie="",
            )
        self.assertTrue(self.output_path.exists())
        self.assertEqual(self.output_path.read_bytes(), b"aaaabbbb")

    def test_server_ignores_range_restarts(self):
        """If server returns 200 instead of 206 for a Range request, restart from scratch."""
        part_path = self.output_path.with_name("song.mp3.part")
        part_path.write_bytes(b"aaaa")

        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200  # Server ignored Range
        mock_resp.headers = {"Content-Length": "4"}
        mock_resp.read.side_effect = [b"bbbb", b""]

        with mock.patch("music_fetch.audio.request.urlopen", return_value=mock_resp):
            music_fetch.audio._download_audio_stream(
                "https://example.com/song.mp3",
                self.output_path, timeout=10,
                progress_callback=None, cancel_checker=None, cookie="",
            )
        self.assertTrue(self.output_path.exists())
        # Should overwrite, not append
        self.assertEqual(self.output_path.read_bytes(), b"bbbb")


class ConvertAudioFileTests(unittest.TestCase):
    """Test convert_audio_file for all format branches."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source = Path(self.tmp.name) / "test.m4a"
        self.source.write_bytes(b"dummy")

    def tearDown(self):
        self.tmp.cleanup()

    @mock.patch("music_fetch.audio.shutil.which", return_value="/usr/bin/ffmpeg")
    @mock.patch("music_fetch.audio.subprocess.run")
    def test_convert_to_mp3(self, run_mock, _which_mock):
        run_mock.return_value = mock.MagicMock(returncode=0, stderr="")
        target = Path(self.tmp.name) / "test.mp3"
        music_fetch.audio.convert_audio_file(self.source, target, "mp3")
        args = run_mock.call_args[0][0]
        self.assertIn("libmp3lame", args)

    @mock.patch("music_fetch.audio.shutil.which", return_value="/usr/bin/ffmpeg")
    @mock.patch("music_fetch.audio.subprocess.run")
    def test_convert_to_m4a(self, run_mock, _which_mock):
        run_mock.return_value = mock.MagicMock(returncode=0, stderr="")
        target = Path(self.tmp.name) / "test.m4a"
        music_fetch.audio.convert_audio_file(self.source, target, "m4a")
        args = run_mock.call_args[0][0]
        self.assertIn("aac", args)

    @mock.patch("music_fetch.audio.shutil.which", return_value="/usr/bin/ffmpeg")
    @mock.patch("music_fetch.audio.subprocess.run")
    def test_convert_to_wav(self, run_mock, _which_mock):
        run_mock.return_value = mock.MagicMock(returncode=0, stderr="")
        target = Path(self.tmp.name) / "test.wav"
        music_fetch.audio.convert_audio_file(self.source, target, "wav")
        args = run_mock.call_args[0][0]
        self.assertIn("pcm_s16le", args)

    @mock.patch("music_fetch.audio.shutil.which", return_value="/usr/bin/ffmpeg")
    @mock.patch("music_fetch.audio.subprocess.run")
    def test_convert_to_flac(self, run_mock, _which_mock):
        run_mock.return_value = mock.MagicMock(returncode=0, stderr="")
        target = Path(self.tmp.name) / "test.flac"
        music_fetch.audio.convert_audio_file(self.source, target, "flac")
        args = run_mock.call_args[0][0]
        self.assertIn("flac", args)

    @mock.patch("music_fetch.audio.shutil.which", return_value="/usr/bin/ffmpeg")
    def test_convert_timeout(self, _which_mock):
        import subprocess
        with mock.patch("music_fetch.audio.subprocess.run", side_effect=subprocess.TimeoutExpired("ffmpeg", 240)):
            target = Path(self.tmp.name) / "test.mp3"
            with self.assertRaises(MusicFetchError) as ctx:
                music_fetch.audio.convert_audio_file(self.source, target, "mp3")
            self.assertEqual(ctx.exception.code, "CONVERT_FAILED")


class FetchOuterMediaUrlTests(unittest.TestCase):
    """Test fetch_outer_media_url."""

    def test_redirects_to_cdn(self):
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.geturl.return_value = "https://m10.music.126.net/song.mp3"
        with mock.patch("music_fetch.audio.request.urlopen", return_value=mock_resp):
            result = music_fetch.audio.fetch_outer_media_url("42")
        assert result is not None
        self.assertIn("music.126.net", result)

    def test_redirects_to_non_cdn(self):
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.geturl.return_value = "https://music.163.com/404"
        with mock.patch("music_fetch.audio.request.urlopen", return_value=mock_resp):
            result = music_fetch.audio.fetch_outer_media_url("42")
        self.assertIsNone(result)

    def test_http_error(self):
        from urllib import error
        with mock.patch("music_fetch.audio.request.urlopen", side_effect=error.HTTPError("url", 404, "Not Found", Message(), None)):
            result = music_fetch.audio.fetch_outer_media_url("42")
        self.assertIsNone(result)


class DownloadPreviewToTempTests(unittest.TestCase):
    def _candidate(self, level: str, encode_type: str, url: str) -> mock.Mock:
        candidate = mock.Mock()
        candidate.level = level
        candidate.encode_type = encode_type
        candidate.media_url = url
        return candidate

    def test_picks_lowest_level_candidate_and_downloads_to_temp(self):
        candidates = [
            self._candidate("exhigh", "aac", "https://cdn/x.aac"),
            self._candidate("standard", "mp3", "https://cdn/x.mp3"),
            self._candidate("higher", "aac", "https://cdn/x2.aac"),
        ]
        with mock.patch("music_fetch.audio.fetch_playable_candidates", return_value=candidates), mock.patch(
            "music_fetch.audio._download_audio_stream"
        ) as stream_mock, mock.patch(
            "music_fetch.audio.tempfile.gettempdir", return_value="/tmp"
        ):
            path = music_fetch.audio.download_preview_to_temp("42", "天下", "MUSIC_U=x", timeout=5)
        self.assertEqual(Path(path).parent, Path("/tmp") / "music-fetch-previews")
        self.assertEqual(Path(path).suffix, ".mp3")
        media_url = stream_mock.call_args.args[0]
        self.assertEqual(media_url, "https://cdn/x.mp3")

    def test_no_candidates_raises_unavailable(self):
        with mock.patch("music_fetch.audio.fetch_playable_candidates", return_value=[]):
            with self.assertRaises(MusicFetchError) as raised:
                music_fetch.audio.download_preview_to_temp("42", "天下", "MUSIC_U=x", timeout=5)
        self.assertEqual(raised.exception.code, "SONG_UNAVAILABLE")