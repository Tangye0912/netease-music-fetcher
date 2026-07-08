"""Tests for music_fetch.api pure-logic functions."""
import unittest
from unittest import mock
from urllib import error

from music_fetch.api import (
    MusicFetchError,
    ErrorCode,
    build_cookie_string,
    extract_csrf,
    extract_url_from_input,
    is_netease_music_host,
    normalize_cookie,
    normalize_media_url,
    parse_cookie_fields,
    parse_input_resource,
    parse_playlist_id,
    parse_song_id,
    resolve_short_url,
    _pick_first_digit,
)


class ParseSongIdTests(unittest.TestCase):
    def test_numeric_id_returns_directly(self):
        self.assertEqual(parse_song_id("12345"), "12345")

    def test_song_url_extracts_id(self):
        url = "https://music.163.com/song?id=33894312"
        self.assertEqual(parse_song_id(url), "33894312")

    def test_song_url_with_fragment(self):
        url = "https://music.163.com/#/song?id=33894312"
        self.assertEqual(parse_song_id(url), "33894312")

    def test_playlist_url_raises(self):
        with self.assertRaises(MusicFetchError) as ctx:
            parse_song_id("https://music.163.com/playlist?id=123")
        self.assertEqual(ctx.exception.code, "INVALID_URL")


class ParsePlaylistIdTests(unittest.TestCase):
    def test_playlist_url_extracts_id(self):
        url = "https://music.163.com/playlist?id=60198"
        self.assertEqual(parse_playlist_id(url), "60198")

    def test_song_url_raises(self):
        with self.assertRaises(MusicFetchError):
            parse_playlist_id("https://music.163.com/song?id=123")


class ParseInputResourceTests(unittest.TestCase):
    def test_numeric_returns_song(self):
        rt, rid = parse_input_resource("12345")
        self.assertEqual(rt, "song")
        self.assertEqual(rid, "12345")

    def test_song_url(self):
        rt, rid = parse_input_resource("https://music.163.com/song?id=42")
        self.assertEqual(rt, "song")
        self.assertEqual(rid, "42")

    def test_playlist_url(self):
        rt, rid = parse_input_resource("https://music.163.com/playlist?id=99")
        self.assertEqual(rt, "playlist")
        self.assertEqual(rid, "99")

    def test_fragment_playlist_url(self):
        rt, rid = parse_input_resource("https://music.163.com/#/playlist?id=77")
        self.assertEqual(rt, "playlist")
        self.assertEqual(rid, "77")

    def test_non_netease_url_raises(self):
        with self.assertRaises(MusicFetchError):
            parse_input_resource("https://example.com/song?id=1")

    def test_share_text_extracts_url(self):
        text = "分享歌曲：https://music.163.com/song?id=100 挺好听的"
        rt, rid = parse_input_resource(text)
        self.assertEqual(rt, "song")
        self.assertEqual(rid, "100")


class ExtractUrlFromInputTests(unittest.TestCase):
    def test_extracts_url_from_text(self):
        text = "看看这首歌 https://music.163.com/song?id=123"
        url = extract_url_from_input(text)
        self.assertIsNotNone(url)
        self.assertIn("music.163.com", url)

    def test_returns_none_for_no_url(self):
        self.assertIsNone(extract_url_from_input("just text"))


class NeteaseHostTests(unittest.TestCase):
    def test_music_163_com(self):
        self.assertTrue(is_netease_music_host("music.163.com"))

    def test_subdomain(self):
        self.assertTrue(is_netease_music_host("api.music.163.com"))

    def test_unrelated_host(self):
        self.assertFalse(is_netease_music_host("example.com"))


class CookieHelperTests(unittest.TestCase):
    def test_build_cookie_string_with_csrf(self):
        c = build_cookie_string("abc", "def")
        self.assertEqual(c, "MUSIC_U=abc; __csrf=def")

    def test_build_cookie_string_without_csrf(self):
        c = build_cookie_string("abc")
        self.assertEqual(c, "MUSIC_U=abc")

    def test_build_cookie_string_empty_music_u(self):
        self.assertEqual(build_cookie_string(""), "")

    def test_parse_cookie_fields(self):
        fields = parse_cookie_fields("MUSIC_U=abc; __csrf=def; foo=bar")
        self.assertEqual(fields["MUSIC_U"], "abc")
        self.assertEqual(fields["__csrf"], "def")
        self.assertEqual(fields["foo"], "bar")

    def test_parse_cookie_fields_empty(self):
        self.assertEqual(parse_cookie_fields(""), {})

    def test_parse_cookie_fields_malformed(self):
        self.assertEqual(parse_cookie_fields("abc; =val; key="), {"key": ""})

    def test_normalize_cookie(self):
        c = normalize_cookie("MUSIC_U=abc; __csrf=def")
        self.assertEqual(c, "MUSIC_U=abc; __csrf=def")

    def test_normalize_cookie_empty(self):
        self.assertEqual(normalize_cookie(""), "")

    def test_extract_csrf(self):
        self.assertEqual(extract_csrf("MUSIC_U=abc; __csrf=tok123"), "tok123")

    def test_extract_csrf_missing(self):
        self.assertEqual(extract_csrf("MUSIC_U=abc"), "")


class NormalizeMediaUrlTests(unittest.TestCase):
    def test_http_music_126_net_upgraded_to_https(self):
        url = "http://p1.music.126.net/abc/song.mp3"
        result = normalize_media_url(url)
        self.assertTrue(result.startswith("https://"))

    def test_https_url_unchanged(self):
        url = "https://p1.music.126.net/abc/song.mp3"
        self.assertEqual(normalize_media_url(url), url)

    def test_non_music_126_net_unchanged(self):
        url = "http://example.com/song.mp3"
        self.assertEqual(normalize_media_url(url), url)


class PickFirstDigitTests(unittest.TestCase):
    def test_picks_first_digit(self):
        self.assertEqual(_pick_first_digit(["320", "128", "192"]), "320")

    def test_empty_list(self):
        self.assertIsNone(_pick_first_digit([]))

    def test_none(self):
        self.assertIsNone(_pick_first_digit(None))

    def test_non_digit_values(self):
        self.assertIsNone(_pick_first_digit(["abc", "xyz"]))


class ResolveShortUrlTests(unittest.TestCase):
    def test_successful_redirect(self):
        mock_resp = mock.MagicMock()
        mock_resp.__enter__ = mock.MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = mock.MagicMock(return_value=False)
        mock_resp.geturl.return_value = "https://music.163.com/song?id=123"
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            result = resolve_short_url("https://163cn.tv/abc")
        self.assertEqual(result, "https://music.163.com/song?id=123")

    def test_http_error_same_url_ignored(self):
        http_err = error.HTTPError("https://163cn.tv/abc", 404, "Not Found", {}, None)
        http_err.geturl = mock.MagicMock(return_value="https://163cn.tv/abc")
        with mock.patch("music_fetch.api.request.urlopen", side_effect=http_err):
            with self.assertRaises(MusicFetchError):
                resolve_short_url("https://163cn.tv/abc")

    def test_http_error_different_url_returned(self):
        http_err = error.HTTPError("https://163cn.tv/abc", 302, "Found", {}, None)
        http_err.geturl = mock.MagicMock(return_value="https://music.163.com/song?id=42")
        with mock.patch("music_fetch.api.request.urlopen", side_effect=http_err):
            result = resolve_short_url("https://163cn.tv/abc")
        self.assertEqual(result, "https://music.163.com/song?id=42")

    def test_url_error_raises(self):
        with mock.patch("music_fetch.api.request.urlopen", side_effect=error.URLError("timeout")):
            with self.assertRaises(MusicFetchError):
                resolve_short_url("https://163cn.tv/abc")


if __name__ == "__main__":
    unittest.main()
