"""Tests for music_fetch.audio.py download stream logic."""
import socketserver
import tempfile
import threading
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock

import music_fetch.audio
from music_fetch.api import DownloadCanceled, MusicFetchError
from music_fetch.audio import merge_bilingual_lyric, sanitize_filename


class MergeBilingualLyricTests(unittest.TestCase):
    ORIGINAL = "[ti:Song]\n[00:01.00]hello\n[00:05.50]world\n"
    TRANSLATION = "[00:01.00]你好\n[00:05.50]世界\n"

    def test_merges_aligned_timestamps(self):
        merged = merge_bilingual_lyric(self.ORIGINAL, self.TRANSLATION)
        lines = merged.splitlines()
        self.assertEqual(lines[0], "[ti:Song]")
        self.assertEqual(lines[1], "[00:01.00]hello")
        self.assertEqual(lines[2], "[00:01.00]你好")
        self.assertEqual(lines[3], "[00:05.50]world")
        self.assertEqual(lines[4], "[00:05.50]世界")

    def test_empty_translation_returns_original(self):
        self.assertEqual(merge_bilingual_lyric(self.ORIGINAL, ""), self.ORIGINAL)
        self.assertEqual(merge_bilingual_lyric(self.ORIGINAL, "   \n"), self.ORIGINAL)

    def test_translation_without_timestamps_returns_original(self):
        self.assertEqual(merge_bilingual_lyric(self.ORIGINAL, "你好\n世界\n"), self.ORIGINAL)

    def test_untranslated_lines_kept_once(self):
        merged = merge_bilingual_lyric(self.ORIGINAL, "[00:01.00]你好\n")
        lines = merged.splitlines()
        self.assertEqual(lines[1], "[00:01.00]hello")
        self.assertEqual(lines[2], "[00:01.00]你好")
        self.assertEqual(lines[3], "[00:05.50]world")

    def test_translation_only_timestamp_ignored(self):
        merged = merge_bilingual_lyric(self.ORIGINAL, "[00:09.00]额外\n")
        self.assertEqual(merged.splitlines(), self.ORIGINAL.splitlines())

    def test_multi_timestamp_line(self):
        original = "[00:01.00][00:09.00]副歌\n"
        translation = "[00:01.00]重复\n"
        merged = merge_bilingual_lyric(original, translation)
        lines = merged.splitlines()
        # The original line is kept once; the translation follows it with the
        # first matched timestamp.
        self.assertEqual(lines[0], original.strip())
        self.assertEqual(lines[1], "[00:01.00]重复")
        self.assertEqual(len(lines), 2)


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

    def test_long_ascii_name_is_truncated(self):
        name = sanitize_filename("a" * 400)
        self.assertLessEqual(len(name), 120)
        self.assertTrue(name)

    def test_long_cjk_name_stays_within_byte_budget(self):
        # CJK costs 3 UTF-8 bytes per character, so ext4's 255-byte cap bites early.
        name = sanitize_filename("歌" * 200)
        self.assertLessEqual(len(name.encode("utf-8")), 200)
        self.assertTrue(name)

    def test_should_skip_existing_only_for_skip_policy(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "a.mp3"
            self.assertFalse(music_fetch.audio.should_skip_existing(target, "skip"))  # missing
            target.write_bytes(b"")
            self.assertFalse(music_fetch.audio.should_skip_existing(target, "skip"))  # interrupted write
            target.write_bytes(b"audio")
            self.assertTrue(music_fetch.audio.should_skip_existing(target, "skip"))
            self.assertFalse(music_fetch.audio.should_skip_existing(target, "rename"))
            self.assertFalse(music_fetch.audio.should_skip_existing(target, "overwrite"))

    def test_path_too_long_detection(self):
        import errno

        class WinPathError(OSError):
            winerror = 206

        self.assertTrue(music_fetch.audio.is_path_too_long_error(WinPathError("too long")))
        self.assertTrue(music_fetch.audio.is_path_too_long_error(OSError(errno.ENAMETOOLONG, "too long")))
        self.assertFalse(music_fetch.audio.is_path_too_long_error(OSError(errno.ENOENT, "missing")))

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

    def _response(self, headers, chunks, status=200):
        response = mock.MagicMock()
        response.status = status
        response.getcode.return_value = status
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.headers = headers
        response.read.side_effect = list(chunks)
        return response

    def test_download_success_first_attempt(self):
        fake_resp = mock.MagicMock()
        fake_resp.status = 200
        fake_resp.getcode.return_value = 200
        fake_resp.__enter__.return_value = fake_resp
        fake_resp.__exit__.return_value = False
        fake_resp.headers = {"Content-Length": "4"}
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

    def test_truncated_body_resumes_instead_of_publishing_a_short_file(self):
        # Content-Length says 100 but the connection drops after 4 bytes.
        # http.client does not raise IncompleteRead for a short Content-Length
        # body, so the stream must detect it and resume on the next attempt.
        first = self._response({"Content-Length": "100"}, [b"aaaa", b""])
        second = self._response({"Content-Length": "96"}, [b"b" * 96, b""], status=206)

        with mock.patch("urllib.request.urlopen", side_effect=[first, second]) as urlopen:
            music_fetch.audio._download_audio_stream(
                "https://m801.music.126.net/abc.mp3",
                self.output_path,
                timeout=10,
                progress_callback=None,
                cancel_checker=None,
                cookie="",
            )

        self.assertEqual(urlopen.call_count, 2)
        self.assertEqual(self.output_path.read_bytes(), b"aaaa" + b"b" * 96)
        self.assertFalse(self.output_path.with_name(f"{self.output_path.name}.part").exists())

    def test_all_truncated_attempts_raise_network_error_and_clean_up(self):
        def always_short(*_args, **_kwargs):
            return self._response({"Content-Length": "100"}, [b"aaaa", b""])

        with mock.patch("urllib.request.urlopen", side_effect=always_short):
            with self.assertRaises(music_fetch.MusicFetchError) as ctx:
                music_fetch.audio._download_audio_stream(
                    "https://m801.music.126.net/abc.mp3",
                    self.output_path,
                    timeout=10,
                    progress_callback=None,
                    cancel_checker=None,
                    cookie="",
                )
        self.assertEqual(ctx.exception.code, "NETWORK_ERROR")
        self.assertFalse(self.output_path.exists())
        self.assertFalse(self.output_path.with_name(f"{self.output_path.name}.part").exists())

    def test_fsync_runs_before_the_part_file_is_published(self):
        fake_resp = self._response({"Content-Length": "4"}, [b"aaaa", b""])
        with mock.patch("urllib.request.urlopen", return_value=fake_resp), mock.patch(
            "music_fetch.audio.os.fsync"
        ) as fsync_mock:
            music_fetch.audio._download_audio_stream(
                "https://m801.music.126.net/abc.mp3",
                self.output_path,
                timeout=10,
                progress_callback=None,
                cancel_checker=None,
                cookie="",
            )
        self.assertTrue(self.output_path.exists())
        fsync_mock.assert_called_once()

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

    def test_socket_read_timeout_is_retried_as_network_error(self):
        """A mid-body read timeout surfaces as OSError, not URLError."""
        fake_timeout = mock.MagicMock()
        fake_timeout.status = 200
        fake_timeout.getcode.return_value = 200
        fake_timeout.__enter__.return_value = fake_timeout
        fake_timeout.__exit__.return_value = False
        fake_timeout.headers = {}
        fake_timeout.read.side_effect = TimeoutError("timed out")

        fake_ok = mock.MagicMock()
        fake_ok.status = 200
        fake_ok.getcode.return_value = 200
        fake_ok.__enter__.return_value = fake_ok
        fake_ok.__exit__.return_value = False
        fake_ok.headers = {}
        fake_ok.read.side_effect = [b"dddd", b""]

        with mock.patch("urllib.request.urlopen", side_effect=[fake_timeout, fake_ok]):
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

    def test_all_socket_timeouts_raise_network_error(self):
        """Timeouts must not degrade into an unknown-error report."""
        fake_timeout = mock.MagicMock()
        fake_timeout.status = 200
        fake_timeout.getcode.return_value = 200
        fake_timeout.__enter__.return_value = fake_timeout
        fake_timeout.__exit__.return_value = False
        fake_timeout.headers = {}
        fake_timeout.read.side_effect = TimeoutError("timed out")

        with mock.patch("urllib.request.urlopen", return_value=fake_timeout):
            with self.assertRaises(music_fetch.MusicFetchError) as ctx:
                music_fetch.audio._download_audio_stream(
                    "https://m801.music.126.net/abc.mp3",
                    self.output_path,
                    timeout=10,
                    progress_callback=None,
                    cancel_checker=None,
                    cookie="",
                )
        self.assertEqual(ctx.exception.code, "NETWORK_ERROR")
        self.assertFalse(self.output_path.exists())

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


    def _ok_response(self, chunks):
        response = mock.MagicMock()
        response.status = 200
        response.getcode.return_value = 200
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        response.headers = {}
        response.read.side_effect = list(chunks) + [b""]
        return response

    def test_pause_blocks_the_read_until_resumed(self):
        checks: list[int] = []

        def pause_checker() -> bool:
            checks.append(1)
            return len(checks) <= 2  # pause for the first two checks, then resume

        with mock.patch("urllib.request.urlopen", return_value=self._ok_response([b"paused-bytes"])):
            music_fetch.audio._download_audio_stream(
                "https://m801.music.126.net/abc.mp3",
                self.output_path,
                timeout=10,
                progress_callback=None,
                cancel_checker=None,
                pause_checker=pause_checker,
                cookie="",
            )

        self.assertEqual(self.output_path.read_bytes(), b"paused-bytes")
        self.assertGreaterEqual(len(checks), 3)

    def test_cancel_while_paused_aborts_the_download(self):
        cancel_calls: list[int] = []

        def cancel_checker() -> bool:
            cancel_calls.append(1)
            return len(cancel_calls) >= 2  # pass the pre-read check, cancel inside the pause

        with mock.patch("urllib.request.urlopen", return_value=self._ok_response([b"never-written"])):
            with self.assertRaises(music_fetch.DownloadCanceled):
                music_fetch.audio._download_audio_stream(
                    "https://m801.music.126.net/abc.mp3",
                    self.output_path,
                    timeout=10,
                    progress_callback=None,
                    cancel_checker=cancel_checker,
                    pause_checker=lambda: True,
                    cookie="",
                )

        self.assertFalse(self.output_path.exists())


class DownloadStreamResumeTests(unittest.TestCase):
    """Test _download_audio_stream resume / partial download logic."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.output_path = Path(self.tmp.name) / "song.mp3"

    def tearDown(self):
        self.tmp.cleanup()

    def test_resume_from_partial(self):
        """When a .part file exists with a matching sidecar, resume from its offset."""
        part_path = self.output_path.with_name("song.mp3.part")
        part_path.write_bytes(b"aaaa")  # 4 bytes already downloaded
        sidecar = self.output_path.with_name("song.mp3.part.src")
        sidecar.write_text("https://example.com/song.mp3", encoding="utf-8")

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
        # The sidecar is consumed once the download completes.
        self.assertFalse(sidecar.exists())

    def test_server_ignores_range_restarts(self):
        """If server returns 200 instead of 206 for a Range request, restart from scratch."""
        part_path = self.output_path.with_name("song.mp3.part")
        part_path.write_bytes(b"aaaa")
        sidecar = self.output_path.with_name("song.mp3.part.src")
        sidecar.write_text("https://example.com/song.mp3", encoding="utf-8")

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

    def test_stale_part_from_different_url_restarts(self):
        """A .part whose sidecar names a different resource must not be resumed."""
        part_path = self.output_path.with_name("song.mp3.part")
        part_path.write_bytes(b"stale-bytes")
        sidecar = self.output_path.with_name("song.mp3.part.src")
        sidecar.write_text("https://example.com/other-song.mp3", encoding="utf-8")

        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.headers = {"Content-Length": "4"}
        mock_resp.read.side_effect = [b"bbbb", b""]

        with mock.patch("music_fetch.audio.request.urlopen", return_value=mock_resp):
            music_fetch.audio._download_audio_stream(
                "https://example.com/song.mp3",
                self.output_path, timeout=10,
                progress_callback=None, cancel_checker=None, cookie="",
            )
        # Overwritten from scratch — no appended stale bytes.
        self.assertEqual(self.output_path.read_bytes(), b"bbbb")

    def test_part_without_sidecar_restarts(self):
        """A .part without a sidecar (crash before first write, legacy file) is discarded."""
        part_path = self.output_path.with_name("song.mp3.part")
        part_path.write_bytes(b"stale-bytes")

        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.headers = {"Content-Length": "4"}
        mock_resp.read.side_effect = [b"bbbb", b""]

        with mock.patch("music_fetch.audio.request.urlopen", return_value=mock_resp):
            music_fetch.audio._download_audio_stream(
                "https://example.com/song.mp3",
                self.output_path, timeout=10,
                progress_callback=None, cancel_checker=None, cookie="",
            )
        self.assertEqual(self.output_path.read_bytes(), b"bbbb")

    def test_query_token_difference_still_resumes(self):
        """CDN tokens live in the query string — same host+path stays resumable."""
        part_path = self.output_path.with_name("song.mp3.part")
        part_path.write_bytes(b"aaaa")
        sidecar = self.output_path.with_name("song.mp3.part.src")
        sidecar.write_text("https://example.com/song.mp3?wsSecret=old&wsTime=1", encoding="utf-8")

        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 206
        mock_resp.headers = {"Content-Length": "4"}
        mock_resp.read.side_effect = [b"bbbb", b""]

        with mock.patch("music_fetch.audio.request.urlopen", return_value=mock_resp) as urlopen_mock:
            music_fetch.audio._download_audio_stream(
                "https://example.com/song.mp3?wsSecret=fresh&wsTime=2",
                self.output_path, timeout=10,
                progress_callback=None, cancel_checker=None, cookie="",
            )
        self.assertEqual(self.output_path.read_bytes(), b"aaaabbbb")
        request_headers = urlopen_mock.call_args[0][0].headers
        self.assertEqual(request_headers.get("Range"), "bytes=4-")


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

    def test_unexpected_transport_error_means_no_outer_url(self):
        # Best-effort fallback: a plain OSError (socket reset/TLS) must not escape
        # and hide the real per-candidate error from the caller.
        with mock.patch("music_fetch.audio.request.urlopen", side_effect=ConnectionResetError("reset")):
            self.assertIsNone(music_fetch.audio.fetch_outer_media_url("42"))


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

    def test_api_encode_type_cannot_escape_the_preview_directory(self):
        # encode_type comes from the API response; it must not add a path
        # separator to the temp file name.
        candidates = [self._candidate("standard", "../../evil", "https://cdn/x.mp3")]
        with mock.patch("music_fetch.audio.fetch_playable_candidates", return_value=candidates), mock.patch(
            "music_fetch.audio._download_audio_stream"
        ), mock.patch("music_fetch.audio.tempfile.gettempdir", return_value="/tmp"):
            path = music_fetch.audio.download_preview_to_temp("42", "天下", "MUSIC_U=x", timeout=5)
        self.assertEqual(Path(path).parent, Path("/tmp") / "music-fetch-previews")
        self.assertEqual(Path(path).suffix, ".evil")
        self.assertNotIn("/", Path(path).name)

    def test_no_candidates_raises_unavailable(self):
        with mock.patch("music_fetch.audio.fetch_playable_candidates", return_value=[]):
            with self.assertRaises(MusicFetchError) as raised:
                music_fetch.audio.download_preview_to_temp("42", "天下", "MUSIC_U=x", timeout=5)
        self.assertEqual(raised.exception.code, "SONG_UNAVAILABLE")


class LyricFileAndTagTests(unittest.TestCase):
    """Lyric sidecar and embedding, checked against real containers."""

    FIXTURES = Path(__file__).resolve().parent / "fixtures"
    LYRICS = "[00:01.00]第一行\n[00:05.00]第二行"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _fixture_copy(self, name: str) -> Path:
        target = Path(self.tmp.name) / name
        target.write_bytes((self.FIXTURES / name).read_bytes())
        return target

    def test_save_lyric_file_writes_lrc_next_to_the_audio(self):
        target = self._fixture_copy("silence.mp3")
        music_fetch.audio.save_lyric_file(target, self.LYRICS)
        lrc = Path(self.tmp.name) / "silence.lrc"
        self.assertEqual(lrc.read_text(encoding="utf-8"), self.LYRICS)

    def test_save_lyric_file_ignores_empty_lyrics(self):
        target = self._fixture_copy("silence.mp3")
        music_fetch.audio.save_lyric_file(target, "   \n")
        self.assertFalse((Path(self.tmp.name) / "silence.lrc").exists())

    def test_embed_lyric_in_mp3_uses_a_uslt_frame(self):
        from mutagen.id3 import ID3

        target = self._fixture_copy("silence.mp3")
        music_fetch.audio.embed_lyric_tag(target, self.LYRICS)
        frames = ID3(str(target)).getall("USLT")
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].text, self.LYRICS)

    def test_embed_lyric_replaces_previous_mp3_lyrics(self):
        from mutagen.id3 import ID3

        target = self._fixture_copy("silence.mp3")
        music_fetch.audio.embed_lyric_tag(target, self.LYRICS)
        music_fetch.audio.embed_lyric_tag(target, "新歌词")
        frames = ID3(str(target)).getall("USLT")
        self.assertEqual(len(frames), 1)
        self.assertEqual(frames[0].text, "新歌词")

    def test_embed_lyric_in_m4a(self):
        from mutagen.mp4 import MP4

        target = self._fixture_copy("silence.m4a")
        music_fetch.audio.embed_lyric_tag(target, self.LYRICS)
        self.assertEqual(MP4(str(target)).tags["\xa9lyr"], [self.LYRICS])

    def test_embed_lyric_in_flac(self):
        from mutagen.flac import FLAC

        target = self._fixture_copy("silence.flac")
        music_fetch.audio.embed_lyric_tag(target, self.LYRICS)
        self.assertEqual(FLAC(str(target))["lyrics"], [self.LYRICS])

    def test_embed_lyric_ignores_empty_text_and_unknown_containers(self):
        target = Path(self.tmp.name) / "song.wav"
        target.write_bytes(b"not really audio")
        music_fetch.audio.embed_lyric_tag(target, self.LYRICS)  # unsupported suffix
        music_fetch.audio.embed_lyric_tag(target, "")           # nothing to embed
        self.assertEqual(target.read_bytes(), b"not really audio")


class TruncatedResponseIntegrationTests(unittest.TestCase):
    """End-to-end check against a real HTTP server that closes mid-body.

    http.client deliberately does not raise IncompleteRead when a
    Content-Length body ends early, so only an integration test proves the
    downloader notices the short body.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.output_path = Path(self.tmp.name) / "song.m4a"

    def test_short_body_is_never_published(self):
        payload = b"\x00\x00\x00\x20ftypM4A " + b"A" * (847 - 12)

        class Handler(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.recv(4096)
                head = (
                    b"HTTP/1.1 200 OK\r\nContent-Type: audio/mp4\r\n"
                    b"Content-Length: 847\r\nConnection: close\r\n\r\n"
                )
                self.request.sendall(head + payload[:512])
                self.request.shutdown(1)
                self.request.close()

        with socketserver.TCPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(MusicFetchError) as ctx:
                    music_fetch.audio._download_audio_stream(
                        f"http://127.0.0.1:{server.server_address[1]}/x.m4a",
                        self.output_path,
                        timeout=5,
                        progress_callback=None,
                        cancel_checker=None,
                        cookie="",
                    )
            finally:
                server.shutdown()
                thread.join(timeout=2)

        self.assertEqual(ctx.exception.code, "NETWORK_ERROR")
        self.assertFalse(self.output_path.exists())


class ExistingTargetDecisionTests(unittest.TestCase):
    """Which pre-existing targets the queue may replace vs. must protect."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "song.mp3"

    def test_overwrite_policy_always_replaces(self):
        self.path.write_bytes(b"old")
        self.assertTrue(music_fetch.audio.should_replace_existing(self.path, "overwrite"))
        self.path.unlink()
        self.assertTrue(music_fetch.audio.should_replace_existing(self.path, "overwrite"))

    def test_skip_policy_protects_a_real_file(self):
        self.path.write_bytes(b"old")
        self.assertFalse(music_fetch.audio.should_replace_existing(self.path, "skip"))

    def test_zero_byte_leftover_is_replaced_even_under_rename(self):
        self.path.write_bytes(b"")
        self.assertTrue(music_fetch.audio.should_replace_existing(self.path, "rename"))

    def test_missing_target_is_not_a_replacement(self):
        self.assertFalse(music_fetch.audio.should_replace_existing(self.path, "rename"))


class PlausibleCompleteAudioTests(unittest.TestCase):
    """Only a parseable container counts as a finished download."""

    FIXTURES = Path(__file__).resolve().parent / "fixtures"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def _copy(self, name: str) -> Path:
        target = self.dir / name
        target.write_bytes((self.FIXTURES / name).read_bytes())
        return target

    def test_real_container_is_complete(self):
        for name in ("silence.mp3", "silence.m4a", "silence.flac"):
            with self.subTest(name=name):
                self.assertTrue(music_fetch.audio.is_plausible_complete_audio(self._copy(name)))

    def test_truncated_container_is_not_complete(self):
        payload = (self.FIXTURES / "silence.m4a").read_bytes()
        target = self.dir / "half.m4a"
        target.write_bytes(payload[: len(payload) // 2])
        self.assertFalse(music_fetch.audio.is_plausible_complete_audio(target))

    def test_missing_empty_and_garbage_are_not_complete(self):
        self.assertFalse(music_fetch.audio.is_plausible_complete_audio(self.dir / "missing.mp3"))
        empty = self.dir / "empty.mp3"
        empty.write_bytes(b"")
        self.assertFalse(music_fetch.audio.is_plausible_complete_audio(empty))
        garbage = self.dir / "garbage.mp3"
        garbage.write_bytes(b"just some text")
        self.assertFalse(music_fetch.audio.is_plausible_complete_audio(garbage))
