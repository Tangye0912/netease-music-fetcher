"""Tests for music_fetch.api pure-logic functions."""
import unittest
from email.message import Message
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
        assert url is not None
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
        http_err = error.HTTPError("https://163cn.tv/abc", 404, "Not Found", Message(), None)
        with mock.patch.object(http_err, "geturl", return_value="https://163cn.tv/abc"), mock.patch(
            "music_fetch.api.request.urlopen", side_effect=http_err
        ):
            with self.assertRaises(MusicFetchError):
                resolve_short_url("https://163cn.tv/abc")

    def test_http_error_different_url_returned(self):
        http_err = error.HTTPError("https://163cn.tv/abc", 302, "Found", Message(), None)
        with mock.patch.object(http_err, "geturl", return_value="https://music.163.com/song?id=42"), mock.patch(
            "music_fetch.api.request.urlopen", side_effect=http_err
        ):
            result = resolve_short_url("https://163cn.tv/abc")
        self.assertEqual(result, "https://music.163.com/song?id=42")

    def test_url_error_raises(self):
        with mock.patch("music_fetch.api.request.urlopen", side_effect=error.URLError("timeout")):
            with self.assertRaises(MusicFetchError):
                resolve_short_url("https://163cn.tv/abc")


class PerformRequestTests(unittest.TestCase):
    """Test _perform_request and JSON helpers via urlopen mocking."""

    def test_perform_json_get_success(self):
        from music_fetch.api import perform_json_get
        fake_body = b'{"code": 200, "data": {"ok": true}}'
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.read.return_value = fake_body
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            status, body = perform_json_get("https://example.com/api", {"User-Agent": "test"}, timeout=10)
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], 200)

    def test_perform_json_post_success(self):
        from music_fetch.api import perform_json_post
        fake_body = b'{"code": 200}'
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.read.return_value = fake_body
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            status, body = perform_json_post("https://example.com/api", {"key": "val"}, {"User-Agent": "test"}, timeout=10)
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], 200)

    def test_perform_request_http_error(self):
        from music_fetch.api import perform_json_get
        http_err = error.HTTPError("url", 403, "Forbidden", Message(), None)
        mock_resp = mock.MagicMock()
        mock_resp.read.return_value = b'{"code": 403}'
        with mock.patch("music_fetch.api.request.urlopen", side_effect=http_err) as mock_urlopen:
            status, body = perform_json_get("https://example.com/api", {}, timeout=10)
        self.assertEqual(status, 403)

    def test_perform_request_url_error(self):
        from music_fetch.api import perform_json_get, MusicFetchError
        with mock.patch("music_fetch.api.request.urlopen", side_effect=error.URLError("timeout")):
            with self.assertRaises(MusicFetchError):
                perform_json_get("https://example.com/api", {}, timeout=10)

    def test_decode_json_invalid(self):
        from music_fetch.api import perform_json_get, MusicFetchError
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.read.return_value = b"not json"
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            with self.assertRaises(MusicFetchError):
                perform_json_get("https://example.com/api", {}, timeout=10)


class CheckLoginStatusTests(unittest.TestCase):
    """Test check_login_status with mocked HTTP responses."""

    def test_no_music_u_returns_false(self):
        from music_fetch.api import check_login_status
        self.assertFalse(check_login_status("MUSIC_A=test"))

    def test_valid_login(self):
        from music_fetch.api import check_login_status
        fake_body = b'{"code": 200, "account": {"id": 1}, "profile": {"nickname": "test"}}'
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.read.return_value = fake_body
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            self.assertTrue(check_login_status("MUSIC_U=test"))

    def test_401_returns_false(self):
        from music_fetch.api import check_login_status
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 401
        mock_resp.read.return_value = b'{}'
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            self.assertFalse(check_login_status("MUSIC_U=test"))

    def test_code_301_returns_false(self):
        from music_fetch.api import check_login_status
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"code": 301}'
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            self.assertFalse(check_login_status("MUSIC_U=test"))


class FetchAccountProfileTests(unittest.TestCase):
    """Test fetch_account_profile with mocked HTTP responses."""

    def test_no_music_u_raises(self):
        from music_fetch.api import fetch_account_profile, MusicFetchError
        with self.assertRaises(MusicFetchError):
            fetch_account_profile("MUSIC_A=bad")

    def test_success(self):
        from music_fetch.api import fetch_account_profile
        fake_body = b'{"code": 200, "account": {"id": 1}, "profile": {"nickname": "test", "avatarUrl": "http://a", "vipType": 0}}'
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.read.return_value = fake_body
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            profile = fetch_account_profile("MUSIC_U=test")
        self.assertEqual(profile.nickname, "test")
        self.assertFalse(profile.is_vip)

    def test_vip_user(self):
        from music_fetch.api import fetch_account_profile
        fake_body = b'{"code": 200, "account": {"id": 1}, "profile": {"nickname": "vip", "avatarUrl": "http://a", "vipType": 11}}'
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.read.return_value = fake_body
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            profile = fetch_account_profile("MUSIC_U=test")
        self.assertTrue(profile.is_vip)

    def test_auth_expired(self):
        from music_fetch.api import fetch_account_profile, MusicFetchError
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 401
        mock_resp.read.return_value = b'{}'
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            with self.assertRaises(MusicFetchError):
                fetch_account_profile("MUSIC_U=test")


class SearchSongsTests(unittest.TestCase):
    """Test search_songs with mocked HTTP responses."""

    def test_empty_keyword(self):
        from music_fetch.api import search_songs
        self.assertEqual(search_songs("", "cookie"), [])

    def test_success(self):
        from music_fetch.api import search_songs
        fake_body = b'{"code": 200, "result": {"songs": [{"id": 1, "name": "Song A", "artists": [{"name": "Artist"}], "album": {"name": "Album"}, "duration": 240000}]}}'
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.read.return_value = fake_body
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            results = search_songs("test", "cookie")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].song_name, "Song A")

    def test_network_error_returns_empty(self):
        from music_fetch.api import search_songs
        with mock.patch("music_fetch.api.request.urlopen", side_effect=error.URLError("timeout")):
            results = search_songs("test", "cookie")
        self.assertEqual(results, [])

    def test_result_null_returns_empty(self):
        # {"result": null} must not raise AttributeError (default {} only
        # applies when the key is missing, not when its value is None).
        from music_fetch.api import search_songs
        fake_body = b'{"code": 200, "result": null}'
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.read.return_value = fake_body
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            results = search_songs("test", "cookie")
        self.assertEqual(results, [])


class FetchLyricTests(unittest.TestCase):
    """Test fetch_lyric with mocked HTTP responses."""

    def _mock_response(self, body: bytes) -> mock.MagicMock:
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.read.return_value = body
        return mock_resp

    def test_success_with_translation(self):
        from music_fetch.api import fetch_lyric
        body = b'{"code": 200, "lrc": {"lyric": "[00:01.00]hello"}, "tlyric": {"lyric": "[00:01.00]\\u4f60\\u597d"}}'
        with mock.patch("music_fetch.api.request.urlopen", return_value=self._mock_response(body)):
            result = fetch_lyric("1")
        self.assertEqual(result.lyric, "[00:01.00]hello")
        self.assertEqual(result.translated_lyric, "[00:01.00]你好")

    def test_null_lrc_objects_return_empty_strings(self):
        # {"lrc": null} must not raise AttributeError.
        from music_fetch.api import fetch_lyric
        body = b'{"code": 200, "lrc": null, "tlyric": null}'
        with mock.patch("music_fetch.api.request.urlopen", return_value=self._mock_response(body)):
            result = fetch_lyric("1")
        self.assertEqual(result.lyric, "")
        self.assertEqual(result.translated_lyric, "")


class FetchUserPlaylistsTests(unittest.TestCase):
    """Test fetch_user_playlists with mocked HTTP responses."""

    def test_no_music_u_raises(self):
        from music_fetch.api import fetch_user_playlists, MusicFetchError
        with self.assertRaises(MusicFetchError):
            fetch_user_playlists("bad_cookie")

    def test_success(self):
        from music_fetch.api import fetch_user_playlists
        account_body = b'{"code": 200, "account": {"id": 123}}'
        playlist_body = b'{"code": 200, "playlist": [{"id": 1, "name": "My List", "trackCount": 10, "coverImgUrl": "", "creator": {"nickname": "Me"}}]}'
        mock_resp1 = mock.MagicMock()
        mock_resp1.__enter__.return_value = mock_resp1
        mock_resp1.status = 200
        mock_resp1.read.return_value = account_body
        mock_resp2 = mock.MagicMock()
        mock_resp2.__enter__.return_value = mock_resp2
        mock_resp2.status = 200
        mock_resp2.read.return_value = playlist_body
        with mock.patch("music_fetch.api.request.urlopen", side_effect=[mock_resp1, mock_resp2]):
            results = fetch_user_playlists("MUSIC_U=test")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "My List")


class FetchPlayableCandidatesTests(unittest.TestCase):
    """Test fetch_playable_candidates with mocked HTTP responses."""

    def test_401_raises_auth_expired(self):
        from music_fetch.api import fetch_playable_candidates, MusicFetchError
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 401
        mock_resp.read.return_value = b'{}'
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            with self.assertRaises(MusicFetchError) as ctx:
                fetch_playable_candidates("42", "MUSIC_U=test; __csrf=csrf", timeout=10)
            self.assertEqual(ctx.exception.code, "AUTH_EXPIRED")

    def test_song_unavailable(self):
        from music_fetch.api import fetch_playable_candidates, MusicFetchError
        # All profiles return empty data — song unavailable
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"code": 200, "data": []}'
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            with self.assertRaises(MusicFetchError) as ctx:
                fetch_playable_candidates("42", "MUSIC_U=test; __csrf=csrf", timeout=10)
            self.assertEqual(ctx.exception.code, "SONG_UNAVAILABLE")

    def test_success(self):
        from music_fetch.api import fetch_playable_candidates
        mock_resp = mock.MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.status = 200
        mock_resp.read.return_value = (
            b'{"code": 200, "data": [{"url": "https://m10.music.126.net/song.mp3", "time": 240000}]}'
        )
        with mock.patch("music_fetch.api.request.urlopen", return_value=mock_resp):
            candidates = fetch_playable_candidates("42", "MUSIC_U=test; __csrf=csrf", timeout=10)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].encode_type, "mp3")


class DetectSongTests(unittest.TestCase):
    """Test detect_song with mocked HTTP responses."""

    def test_detect_success(self):
        from music_fetch.api import detect_song
        # Mock metadata response
        meta_resp = mock.MagicMock()
        meta_resp.__enter__.return_value = meta_resp
        meta_resp.status = 200
        meta_resp.read.return_value = (
            b'{"code": 200, "songs": [{"name": "Test Song", "dt": 240000, '
            b'"al": {"picUrl": "http://cover.jpg"}, "ar": [{"name": "Artist"}]}]}'
        )
        # Mock playable URL response — fetch_playable_candidates iterates 5 profiles
        player_resp = mock.MagicMock()
        player_resp.__enter__.return_value = player_resp
        player_resp.status = 200
        player_resp.read.return_value = (
            b'{"code": 200, "data": [{"url": "https://m10.music.126.net/song.mp3", "time": 240000}]}'
        )
        with mock.patch("music_fetch.api.request.urlopen", side_effect=[meta_resp] + [player_resp] * 5):
            result = detect_song("https://music.163.com/song?id=42", "MUSIC_U=test; __csrf=csrf", timeout=10)
        self.assertTrue(result.can_download)
        self.assertEqual(result.song_name, "Test Song")

    def test_detect_unavailable(self):
        from music_fetch.api import detect_song
        meta_resp = mock.MagicMock()
        meta_resp.__enter__.return_value = meta_resp
        meta_resp.status = 200
        meta_resp.read.return_value = (
            b'{"code": 200, "songs": [{"name": "Test", "dt": 240000}]}'
        )
        empty_resp = mock.MagicMock()
        empty_resp.__enter__.return_value = empty_resp
        empty_resp.status = 200
        empty_resp.read.return_value = b'{"code": 200, "data": []}'
        with mock.patch("music_fetch.api.request.urlopen", side_effect=[meta_resp] + [empty_resp] * 5):
            result = detect_song("https://music.163.com/song?id=42", "MUSIC_U=test; __csrf=csrf", timeout=10)
        self.assertFalse(result.can_download)


if __name__ == "__main__":
    unittest.main()
