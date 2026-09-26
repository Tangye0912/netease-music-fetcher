import unittest

from music_fetch.app_settings import (
    APP_NAME,
    APP_VERSION,
    URL_IN_TEXT_PATTERN,
    TRAILING_URL_PUNCTUATION,
    SHORT_LINK_HOSTS,
    SUPPORTED_AUDIO_FORMATS,
    DEFAULT_TARGET_FORMAT,
    clean_extracted_url,
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
        self.assertEqual(DEFAULT_TARGET_FORMAT, "mp3")


class CleanExtractedUrlTests(unittest.TestCase):
    """Share copy glues CJK text onto the URL; it must be cut off."""

    def test_share_copy_suffix_is_removed(self):
        self.assertEqual(
            clean_extracted_url("https://163cn.tv/3S7kCzr（@网易云音乐"),
            "https://163cn.tv/3S7kCzr",
        )

    def test_full_width_closing_bracket_is_removed(self):
        self.assertEqual(
            clean_extracted_url("https://music.163.com/song?id=1）"),
            "https://music.163.com/song?id=1",
        )

    def test_ascii_url_is_unchanged(self):
        url = "https://music.163.com/song?id=185809&x=1"
        self.assertEqual(clean_extracted_url(url), url)

    def test_ascii_trailing_punctuation_is_still_stripped(self):
        self.assertEqual(
            clean_extracted_url("https://music.163.com/song?id=1)."),
            "https://music.163.com/song?id=1",
        )

    def test_result_never_contains_non_ascii(self):
        cleaned = clean_extracted_url("https://163cn.tv/abc）】》")
        self.assertTrue(cleaned.isascii())
        self.assertEqual(cleaned, "https://163cn.tv/abc")

    def test_empty_input(self):
        self.assertEqual(clean_extracted_url(""), "")


if __name__ == "__main__":
    unittest.main()
