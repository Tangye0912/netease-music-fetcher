import tempfile
import unittest
from pathlib import Path
from unittest import mock

import music_fetch


class CookieHelperTests(unittest.TestCase):
    def test_normalize_cookie_supports_multiline(self):
        raw = "MUSIC_U=abc;\n__csrf=def;\nfoo=bar;"
        normalized = music_fetch.normalize_cookie(raw)
        self.assertIn("MUSIC_U=abc", normalized)
        self.assertIn("__csrf=def", normalized)
        self.assertIn("foo=bar", normalized)

    def test_build_cookie_string_with_csrf(self):
        value = music_fetch.build_cookie_string("abc", "def")
        self.assertEqual(value, "MUSIC_U=abc; __csrf=def")


class PathHelperTests(unittest.TestCase):
    def test_resolve_output_path_dedupes(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            first = music_fetch.resolve_output_path(out_dir, song_id="1", song_name="song", rename="a", out_format="mp4")
            first.write_bytes(b"1")
            second = music_fetch.resolve_output_path(out_dir, song_id="1", song_name="song", rename="a", out_format="mp4")
            self.assertNotEqual(first, second)
            self.assertTrue(second.name.startswith("a_"))
            self.assertEqual(second.suffix, ".mp4")


class DownloadFallbackTests(unittest.TestCase):
    @mock.patch("music_fetch._download_audio_stream")
    @mock.patch("music_fetch.fetch_outer_media_url")
    @mock.patch("music_fetch.fetch_playable_candidates")
    def test_fallback_to_outer_url_after_candidate_403(self, candidates_mock, outer_mock, download_mock):
        candidates_mock.return_value = [
            music_fetch.PlayableCandidate(
                media_url="https://m704.music.126.net/a.mp3",
                duration_ms=1000,
                level="standard",
                encode_type="mp3",
            )
        ]
        outer_mock.return_value = "https://m801.music.126.net/b.mp3"

        def side_effect(media_url, *_args, **_kwargs):
            if media_url.endswith("a.mp3"):
                raise music_fetch.MusicFetchError("DOWNLOAD_FAILED", "Media request failed: HTTP 403.")

        download_mock.side_effect = side_effect

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "x.mp4"
            result = music_fetch.download_song_with_fallback(
                song_id="42",
                cookie="MUSIC_U=abc",
                output_path=output,
                timeout=10,
            )
            self.assertIsInstance(result, music_fetch.PlayableCandidate)
            self.assertEqual(result.level, "outer")
            self.assertEqual(download_mock.call_count, 2)

    def test_fetch_outer_media_url_returns_none_for_non_cdn(self):
        class FakeResp:
            def geturl(self):
                return "https://music.163.com/song/media/outer/url?id=1.mp3"

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

        with mock.patch("urllib.request.urlopen", return_value=FakeResp()):
            value = music_fetch.fetch_outer_media_url("1", timeout=3)
            self.assertIsNone(value)


class FormatHelperTests(unittest.TestCase):
    def test_infer_audio_format_from_url(self):
        self.assertEqual(music_fetch.infer_audio_format_from_url("https://a.com/foo/bar.m4a"), "m4a")
        self.assertEqual(music_fetch.infer_audio_format_from_url("https://a.com/foo/bar.mp4"), "m4a")
        self.assertIsNone(music_fetch.infer_audio_format_from_url("https://a.com/foo/bar.bin"))

    @mock.patch("music_fetch.shutil.which", return_value=None)
    def test_convert_audio_file_requires_ffmpeg(self, _which_mock):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "a.m4a"
            target = Path(tmp) / "b.mp3"
            source.write_bytes(b"dummy")
            with self.assertRaises(music_fetch.MusicFetchError) as ctx:
                music_fetch.convert_audio_file(source, target, "mp3")
            self.assertEqual(ctx.exception.code, "CONVERT_TOOL_MISSING")


if __name__ == "__main__":
    unittest.main()
