"""Tests for music_fetch.version_check.py — version_key and fetch_latest_project_version."""

import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest import mock
from urllib import error
from urllib.error import URLError

from music_fetch.version_check import (
    check_for_updates_cached,
    fetch_latest_project_version,
    fetch_release_download_url,
    version_key,
)


class VersionKeyTests(unittest.TestCase):
    def test_simple_version(self):
        self.assertEqual(version_key("1.2.3"), (1, 2, 3))

    def test_single_digit(self):
        self.assertEqual(version_key("5"), (5,))

    def test_empty_string(self):
        self.assertEqual(version_key(""), (0,))

    def test_none(self):
        self.assertEqual(version_key(None), (0,))

    def test_v_prefix(self):
        self.assertEqual(version_key("v0.10.0"), (0, 10, 0))

    def test_comparison(self):
        self.assertGreater(version_key("1.0.0"), version_key("0.9.9"))
        self.assertGreater(version_key("0.10.0"), version_key("0.9.0"))


class FetchLatestVersionTests(unittest.TestCase):
    def test_release_endpoint_returns_tag(self):
        mock_resp = mock.MagicMock()
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=None)
        mock_resp.read.return_value = json.dumps({
            "tag_name": "v0.12.0",
            "html_url": "https://github.com/test/releases/tag/v0.12.0",
        }).encode("utf-8")

        with mock.patch("music_fetch.version_check.request.urlopen", return_value=mock_resp):
            tag, url = fetch_latest_project_version(timeout=3)
            self.assertEqual(tag, "v0.12.0")
            self.assertIn("github.com", url)

    def test_release_endpoint_fails_falls_back_to_tags(self):
        from urllib.error import URLError

        call_count = [0]

        def urlopen_side_effect(req, timeout):
            call_count[0] += 1
            if call_count[0] == 1:
                raise URLError("timeout")
            mock_resp = mock.MagicMock()
            mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
            mock_resp.__exit__ = mock.MagicMock(return_value=None)
            mock_resp.read.return_value = json.dumps([
                {"name": "v0.11.0"},
            ]).encode("utf-8")
            return mock_resp

        with mock.patch("music_fetch.version_check.request.urlopen", side_effect=urlopen_side_effect):
            tag, url = fetch_latest_project_version(timeout=3)
            self.assertEqual(tag, "v0.11.0")

    def test_both_endpoints_fail_raises(self):
        from urllib.error import URLError

        with mock.patch("music_fetch.version_check.request.urlopen", side_effect=URLError("timeout")):
            with self.assertRaises(RuntimeError):
                fetch_latest_project_version(timeout=3)

    def test_rate_limit_403_raises_actionable_message(self):
        headers = Message()
        headers["X-RateLimit-Remaining"] = "0"
        http_err = error.HTTPError("url", 403, "rate limit exceeded", headers, None)

        with mock.patch(
            "music_fetch.version_check.request.urlopen", side_effect=[http_err, http_err]
        ):
            with self.assertRaises(RuntimeError) as raised:
                fetch_latest_project_version(timeout=3)
        self.assertIn("请求频率已达上限", str(raised.exception))
        self.assertIn("MUSIC_FETCH_GITHUB_TOKEN", str(raised.exception))


class FetchLatestProjectVersionTagFallbackTests(unittest.TestCase):
    """Test fallback to tags API when release API fails."""

    def test_falls_back_to_tags(self):
        from music_fetch.version_check import fetch_latest_project_version
        # Release API returns 404, tags API returns a list
        http_err = error.HTTPError("url", 404, "Not Found", Message(), None)
        tags_resp = mock.MagicMock()
        tags_resp.__enter__.return_value = tags_resp
        tags_resp.read.return_value = b'[{"name": "v1.0.0"}]'

        with mock.patch("music_fetch.version_check.request.urlopen", side_effect=[http_err, tags_resp]):
            tag_name, url = fetch_latest_project_version(timeout=3)
        self.assertEqual(tag_name, "v1.0.0")

    def test_json_decode_error_falls_back(self):
        from music_fetch.version_check import fetch_latest_project_version
        # Release API returns invalid JSON, tags API works
        bad_resp = mock.MagicMock()
        bad_resp.__enter__.return_value = bad_resp
        bad_resp.read.return_value = b"not json"
        tags_resp = mock.MagicMock()
        tags_resp.__enter__.return_value = tags_resp
        tags_resp.read.return_value = b'[{"name": "v2.0.0"}]'

        with mock.patch("music_fetch.version_check.request.urlopen", side_effect=[bad_resp, tags_resp]):
            tag_name, url = fetch_latest_project_version(timeout=3)
        self.assertEqual(tag_name, "v2.0.0")

    def test_release_empty_tag_name_falls_back(self):
        from music_fetch.version_check import fetch_latest_project_version
        # Release API returns tag_name=""
        release_resp = mock.MagicMock()
        release_resp.__enter__.return_value = release_resp
        release_resp.read.return_value = b'{"tag_name": "", "html_url": "http://a"}'
        tags_resp = mock.MagicMock()
        tags_resp.__enter__.return_value = tags_resp
        tags_resp.read.return_value = b'[{"name": "v3.0.0"}]'

        with mock.patch("music_fetch.version_check.request.urlopen", side_effect=[release_resp, tags_resp]):
            tag_name, url = fetch_latest_project_version(timeout=3)
        self.assertEqual(tag_name, "v3.0.0")


class FetchReleaseDownloadUrlTests(unittest.TestCase):
    """Test fetch_release_download_url."""

    def test_returns_exe_url(self):
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b'{"assets": [{"name": "music-fetch.exe", "browser_download_url": "http://dl.exe"}]}'
        with mock.patch("music_fetch.version_check.request.urlopen", return_value=mock_resp):
            result = fetch_release_download_url(timeout=3)
        self.assertEqual(result, "http://dl.exe")

    def test_returns_dmg_url(self):
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b'{"assets": [{"name": "music-fetch.dmg", "browser_download_url": "http://dl.dmg"}]}'
        with mock.patch("music_fetch.version_check.request.urlopen", return_value=mock_resp):
            result = fetch_release_download_url(timeout=3)
        self.assertEqual(result, "http://dl.dmg")

    def test_network_error_returns_none(self):
        with mock.patch("music_fetch.version_check.request.urlopen", side_effect=URLError("timeout")):
            result = fetch_release_download_url(timeout=3)
        self.assertIsNone(result)


class CheckForUpdatesCachedTests(unittest.TestCase):
    """The TUI caches update checks for a day to respect the anonymous
    GitHub API rate limit (60 requests/hour)."""

    def _fake_success(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = b'{"tag_name": "v3.3.0", "html_url": "https://example.test"}'
        return resp

    def test_second_call_within_ttl_reuses_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "update_check.json"
            with mock.patch(
                "music_fetch.version_check.open_url", return_value=self._fake_success()
            ) as open_mock:
                first = check_for_updates_cached(timeout=3, cache_file=cache_file)
                second = check_for_updates_cached(timeout=3, cache_file=cache_file)
            self.assertEqual(first, ("v3.3.0", "https://example.test"))
            self.assertEqual(second, first)
            self.assertEqual(open_mock.call_count, 1)  # cached, no new request

    def test_error_is_cached_and_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "update_check.json"
            with mock.patch(
                "music_fetch.version_check.open_url", side_effect=error.URLError("offline")
            ) as open_mock:
                with self.assertRaises(RuntimeError) as first_raise:
                    check_for_updates_cached(timeout=3, cache_file=cache_file)
                calls_after_first = open_mock.call_count
                with self.assertRaises(RuntimeError) as second_raise:
                    check_for_updates_cached(timeout=3, cache_file=cache_file)
            # The cached error is replayed without any new network request.
            self.assertEqual(open_mock.call_count, calls_after_first)
            self.assertGreater(calls_after_first, 0)
            self.assertEqual(str(second_raise.exception), str(first_raise.exception))

    def test_expired_cache_refetches(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "update_check.json"
            with mock.patch(
                "music_fetch.version_check.open_url", return_value=self._fake_success()
            ) as open_mock:
                check_for_updates_cached(timeout=3, cache_file=cache_file)
                check_for_updates_cached(timeout=3, ttl_seconds=0, cache_file=cache_file)
            self.assertEqual(open_mock.call_count, 2)

    def test_corrupt_cache_file_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache_file = Path(tmp) / "update_check.json"
            cache_file.write_text("not json", encoding="utf-8")
            with mock.patch(
                "music_fetch.version_check.open_url", return_value=self._fake_success()
            ):
                latest, _url = check_for_updates_cached(timeout=3, cache_file=cache_file)
            self.assertEqual(latest, "v3.3.0")


if __name__ == "__main__":
    unittest.main()
