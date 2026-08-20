import re
import unittest

from music_fetch.app_settings import (
    APP_NAME,
    APP_VERSION,
    URL_IN_TEXT_PATTERN,
    TRAILING_URL_PUNCTUATION,
    SHORT_LINK_HOSTS,
    SUPPORTED_AUDIO_FORMATS,
    DEFAULT_GUI_TARGET_FORMAT,
)


class AppSettingsTests(unittest.TestCase):
    def test_app_name(self):
        self.assertEqual(APP_NAME, "music-fetch")

    def test_app_version(self):
        parts = APP_VERSION.split(".")
        self.assertEqual(len(parts), 3)
        for part in parts:
            self.assertTrue(part.isdigit())

    def test_url_pattern_matches_http(self):
        match = URL_IN_TEXT_PATTERN.search("text https://music.163.com/song?id=1 more")
        assert match is not None
        self.assertEqual(match.group(0), "https://music.163.com/song?id=1")

    def test_url_pattern_matches_https(self):
        match = URL_IN_TEXT_PATTERN.search("text https://163cn.tv/abc more")
        assert match is not None
        self.assertEqual(match.group(0), "https://163cn.tv/abc")

    def test_url_pattern_no_match(self):
        self.assertIsNone(URL_IN_TEXT_PATTERN.search("no url here"))

    def test_trailing_punctuation_strips_chars(self):
        url = "https://music.163.com/song?id=1)"
        cleaned = url.rstrip(TRAILING_URL_PUNCTUATION)
        self.assertEqual(cleaned, "https://music.163.com/song?id=1")

    def test_short_link_hosts(self):
        self.assertIn("163cn.tv", SHORT_LINK_HOSTS)
        self.assertIn("www.163cn.tv", SHORT_LINK_HOSTS)

    def test_supported_audio_formats(self):
        self.assertIn("mp3", SUPPORTED_AUDIO_FORMATS)
        self.assertIn("flac", SUPPORTED_AUDIO_FORMATS)
        self.assertEqual(DEFAULT_GUI_TARGET_FORMAT, "mp3")


if __name__ == "__main__":
    unittest.main()
