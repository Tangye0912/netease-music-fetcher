"""Tests for _version_check.py — version_key and fetch_latest_project_version."""

import json
import unittest
from unittest import mock

from _version_check import fetch_latest_project_version, version_key


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

        with mock.patch("_version_check.request.urlopen", return_value=mock_resp):
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

        with mock.patch("_version_check.request.urlopen", side_effect=urlopen_side_effect):
            tag, url = fetch_latest_project_version(timeout=3)
            self.assertEqual(tag, "v0.11.0")

    def test_both_endpoints_fail_raises(self):
        from urllib.error import URLError

        with mock.patch("_version_check.request.urlopen", side_effect=URLError("timeout")):
            with self.assertRaises(RuntimeError):
                fetch_latest_project_version(timeout=3)


if __name__ == "__main__":
    unittest.main()