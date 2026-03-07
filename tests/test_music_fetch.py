import tempfile
import unittest
from pathlib import Path
from unittest import mock

import music_fetch


class ParseSongIdTests(unittest.TestCase):
    def test_parse_numeric_id(self):
        self.assertEqual(music_fetch.parse_song_id("123456"), "123456")

    def test_parse_query_url(self):
        url = "https://music.163.com/song?id=7654321"
        self.assertEqual(music_fetch.parse_song_id(url), "7654321")

    def test_parse_hash_url(self):
        url = "https://music.163.com/#/song?id=2345678"
        self.assertEqual(music_fetch.parse_song_id(url), "2345678")

    def test_parse_share_text_with_full_url(self):
        text = "分享歌曲《测试》https://music.163.com/song?id=24680 (@网易云音乐)"
        self.assertEqual(music_fetch.parse_song_id(text), "24680")

    @mock.patch("music_fetch.resolve_short_url")
    def test_parse_share_text_with_short_url(self, resolve_mock):
        resolve_mock.return_value = "https://music.163.com/#/song?id=33894312"
        text = "分享银河快递的单曲《另一个我》https://163cn.tv/2MxARR6 (@网易云音乐)"
        self.assertEqual(music_fetch.parse_song_id(text), "33894312")
        resolve_mock.assert_called_once()

    def test_invalid_domain_raises(self):
        with self.assertRaises(music_fetch.MusicFetchError) as ctx:
            music_fetch.parse_song_id("https://example.com/song?id=1")
        self.assertEqual(ctx.exception.code, "INVALID_URL")


class CookieTests(unittest.TestCase):
    def test_cookie_file_requires_music_u(self):
        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            cookie_file.write_text("__csrf=abc", encoding="utf-8")
            with self.assertRaises(music_fetch.MusicFetchError) as ctx:
                music_fetch.load_cookie(cookie_file)
            self.assertEqual(ctx.exception.code, "AUTH_EXPIRED")


class PlayerApiTests(unittest.TestCase):
    @mock.patch("music_fetch.perform_json_post")
    def test_auth_expired_from_http_status(self, post_mock):
        post_mock.return_value = (401, {"code": 401})
        with self.assertRaises(music_fetch.MusicFetchError) as ctx:
            music_fetch.fetch_playable_url("123", "MUSIC_U=abc; __csrf=def", timeout=5)
        self.assertEqual(ctx.exception.code, "AUTH_EXPIRED")

    @mock.patch("music_fetch.perform_json_post")
    def test_song_unavailable_when_url_missing(self, post_mock):
        post_mock.return_value = (200, {"code": 200, "data": [{"url": None}]})
        with self.assertRaises(music_fetch.MusicFetchError) as ctx:
            music_fetch.fetch_playable_url("123", "MUSIC_U=abc; __csrf=def", timeout=5)
        self.assertEqual(ctx.exception.code, "SONG_UNAVAILABLE")


class AccountProfileTests(unittest.TestCase):
    @mock.patch("music_fetch.perform_json_get")
    def test_fetch_account_profile_success(self, get_mock):
        get_mock.return_value = (
            200,
            {
                "code": 200,
                "profile": {
                    "userId": 123,
                    "nickname": "tester",
                    "avatarUrl": "https://example.com/a.jpg",
                    "vipType": 11,
                },
            },
        )
        profile = music_fetch.fetch_account_profile("MUSIC_U=abc; __csrf=def", timeout=5)
        self.assertEqual(profile.user_id, 123)
        self.assertEqual(profile.nickname, "tester")
        self.assertTrue(profile.is_vip)

    @mock.patch("music_fetch.perform_json_get")
    def test_fetch_account_profile_auth_expired(self, get_mock):
        get_mock.return_value = (401, {"code": 401})
        with self.assertRaises(music_fetch.MusicFetchError) as ctx:
            music_fetch.fetch_account_profile("MUSIC_U=abc", timeout=5)
        self.assertEqual(ctx.exception.code, "AUTH_EXPIRED")


class RunDownloadTests(unittest.TestCase):
    @mock.patch("music_fetch.download_audio_with_progress")
    @mock.patch("music_fetch.fetch_song_metadata")
    @mock.patch("music_fetch.fetch_playable_url")
    def test_run_download_success(self, playable_mock, meta_mock, download_mock):
        playable_mock.return_value = ("https://example.com/media.mp4", 120000)
        meta_mock.return_value = ("Track Name", 130000)

        def write_file(media_url, output_path, timeout, progress_callback, cancel_checker, cookie):
            _ = media_url, timeout, progress_callback, cancel_checker, cookie
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"abc123")

        download_mock.side_effect = write_file

        with tempfile.TemporaryDirectory() as tmp:
            cookie_file = Path(tmp) / "cookies.txt"
            out_dir = Path(tmp) / "downloads"
            cookie_file.write_text("MUSIC_U=abc; __csrf=def", encoding="utf-8")
            result = music_fetch.run_download(
                song_url="https://music.163.com/song?id=42",
                out_dir=out_dir,
                cookie_file=cookie_file,
                out_format="mp4",
                timeout=10,
            )

            self.assertTrue(result.output_path.exists())
            self.assertEqual(result.output_path.suffix, ".mp4")
            self.assertEqual(result.size_bytes, 6)
            self.assertEqual(result.duration_ms, 130000)


if __name__ == "__main__":
    unittest.main()
