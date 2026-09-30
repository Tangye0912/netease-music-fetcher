"""Extra branch coverage for music_fetch.api."""

import unittest
from unittest import mock

from music_fetch.api import (
    ErrorCode,
    MusicFetchError,
    _extract_resource_id,
    fetch_lyric,
    fetch_playable_candidates,
    fetch_playlist_song_ids,
    fetch_song_metadata,
    parse_input_resource,
)
from urllib import parse


class ResourceIdFallbackTests(unittest.TestCase):
    def test_fallback_pattern_recovers_the_id(self):
        # parse_qs already handles "?id=…", so the regex fallback is only
        # reachable for input without a query string; the previous version of
        # this test took the parse_qs path and never covered the fallback.
        self.assertEqual(_extract_resource_id(parse.urlparse("id=42"), "id=42"), "42")

    def test_returns_empty_when_no_id_is_present(self):
        url = "https://music.163.com/playlist"
        self.assertEqual(_extract_resource_id(parse.urlparse(url), url), "")

    def test_parse_input_resource_uses_the_fallback(self):
        self.assertEqual(parse_input_resource("id=99"), ("song", "99"))


class PlayableCandidateBranchTests(unittest.TestCase):
    def test_candidate_size_is_parsed_and_invalid_values_become_zero(self):
        body = {
            "code": 200,
            "data": [{"url": "https://cdn/a.mp3", "level": "standard", "encodeType": "mp3", "size": 4200000}],
        }
        with mock.patch("music_fetch.api.perform_json_post", return_value=(200, body)):
            candidates = fetch_playable_candidates("42", "MUSIC_U=test", timeout=5)
        self.assertEqual(candidates[0].size_bytes, 4200000)

        for raw_size in (None, 0, -5, "123", True, 1.5):
            with self.subTest(size=raw_size):
                payload = {
                    "code": 200,
                    "data": [{
                        "url": "https://cdn/a.mp3", "level": "standard",
                        "encodeType": "mp3", "size": raw_size,
                    }],
                }
                with mock.patch("music_fetch.api.perform_json_post", return_value=(200, payload)):
                    candidate = fetch_playable_candidates("42", "MUSIC_U=test", timeout=5)[0]
                # "123" and True are not sizes; 1.5 is truncated, 0/-5 mean unknown.
                self.assertIn(candidate.size_bytes, (0, 1))

    def test_detect_song_reports_the_chosen_candidate_size(self):
        from music_fetch.api import PlayableCandidate, detect_song

        candidates = [
            PlayableCandidate("https://cdn/standard.mp3", 1000, "standard", "mp3", 3_000_000),
            PlayableCandidate("https://cdn/hires.flac", 2000, "hires", "flac", 30_000_000),
        ]
        with mock.patch("music_fetch.api.parse_song_id", return_value="42"), mock.patch(
            "music_fetch.api.fetch_song_metadata", return_value=("Song", 2000, None, None, None)
        ), mock.patch("music_fetch.api.fetch_playable_candidates", return_value=candidates):
            result = detect_song("https://music.163.com/song?id=42", "MUSIC_U=test")
        # The size must describe the same candidate as the reported level.
        self.assertEqual(result.level, "hires")
        self.assertEqual(result.size_bytes, 30_000_000)

    def test_candidates_without_urls_end_up_as_unavailable(self):
        # Every profile answers with an empty url: the song must be reported as
        # unavailable rather than silently producing no candidates.
        body = {"code": 200, "data": [{"url": None, "level": "standard", "encodeType": "mp3"}]}
        with mock.patch("music_fetch.api.perform_json_post", return_value=(200, body)):
            with self.assertRaises(MusicFetchError) as ctx:
                fetch_playable_candidates("42", "MUSIC_U=test", timeout=5)
        self.assertEqual(ctx.exception.code, "SONG_UNAVAILABLE")

    def test_metadata_failure_returns_empty_values(self):
        with mock.patch(
            "music_fetch.api.perform_json_get", side_effect=MusicFetchError(ErrorCode.NETWORK_ERROR, "boom")
        ):
            self.assertEqual(fetch_song_metadata("42", "MUSIC_U=test", timeout=5), (None, None, None, None, None))


class PlaylistPagingBranchTests(unittest.TestCase):
    def test_partial_results_are_kept_when_a_later_page_fails(self):
        first = {"code": 200, "playlist": {"trackIds": [{"id": index} for index in range(1, 1001)]}}
        with mock.patch(
            "music_fetch.api.perform_json_get",
            side_effect=[(200, first), MusicFetchError(ErrorCode.NETWORK_ERROR, "boom")],
        ) as get_mock:
            ids = fetch_playlist_song_ids("7", "MUSIC_U=test")
        self.assertEqual(len(ids), 1000)
        self.assertEqual(ids[0], "1")
        # The cursor must really advance, otherwise a stuck offset would look
        # like a successful partial fetch.
        self.assertEqual(get_mock.call_count, 2)
        self.assertIn("s=1000", get_mock.call_args_list[1].args[0])

    def test_the_first_page_failure_still_raises(self):
        with mock.patch(
            "music_fetch.api.perform_json_get", side_effect=MusicFetchError(ErrorCode.NETWORK_ERROR, "boom")
        ):
            with self.assertRaises(MusicFetchError) as ctx:
                fetch_playlist_song_ids("7", "MUSIC_U=test")
        # The code matters: the later "playlist is empty" path raises the same
        # exception class, so a bare assertRaises would also pass on it.
        self.assertEqual(ctx.exception.code, "NETWORK_ERROR")

    def test_legacy_tracks_field_is_used_when_track_ids_are_missing(self):
        body = {"code": 200, "playlist": {"trackIds": [], "tracks": [{"id": 11}, {"id": 12}, {"id": "skip"}]}}
        with mock.patch("music_fetch.api.perform_json_get", return_value=(200, body)):
            self.assertEqual(fetch_playlist_song_ids("7", "MUSIC_U=test"), ["11", "12"])


class LyricFailureTests(unittest.TestCase):
    def test_fetch_failure_returns_an_empty_lyric(self):
        with mock.patch(
            "music_fetch.api.perform_json_get", side_effect=MusicFetchError(ErrorCode.NETWORK_ERROR, "boom")
        ):
            result = fetch_lyric("42")
        self.assertEqual(result.lyric, "")


class InvalidSongIdTests(unittest.TestCase):
    """A bad song id must fail as MusicFetchError, not as a raw ValueError.

    The TUI only catches MusicFetchError, so a ValueError here would escape into
    main()'s last-resort handler and close the whole app.
    """

    def test_superscript_digit_id_is_rejected_before_any_request(self):
        with mock.patch("music_fetch.api.perform_json_post") as post_mock:
            with self.assertRaises(MusicFetchError) as ctx:
                fetch_playable_candidates("\u00b2", "MUSIC_U=test", timeout=5)
        self.assertEqual(ctx.exception.code, "INVALID_URL")
        post_mock.assert_not_called()

    def test_absurdly_long_id_is_rejected_before_any_request(self):
        with mock.patch("music_fetch.api.perform_json_post") as post_mock:
            with self.assertRaises(MusicFetchError) as ctx:
                fetch_playable_candidates("9" * 5000, "MUSIC_U=test", timeout=5)
        self.assertEqual(ctx.exception.code, "INVALID_URL")
        post_mock.assert_not_called()

    def test_parse_input_resource_rejects_non_ascii_digits(self):
        with self.assertRaises(MusicFetchError) as ctx:
            parse_input_resource("\u00b2")
        self.assertEqual(ctx.exception.code, "INVALID_URL")


class SafeIntTests(unittest.TestCase):
    def test_integer_strings_are_converted_exactly(self):
        from music_fetch.api import _safe_int

        big = "109951169929593913"
        self.assertEqual(_safe_int(big), 109951169929593913)  # a float round-trip loses 7

    def test_unusable_values_become_zero(self):
        from music_fetch.api import _safe_int

        for value in (None, True, "", "   ", "abc", "\u00b2", "1e999", "nan", "inf", [], {}, b"x"):
            with self.subTest(value=value):
                self.assertEqual(_safe_int(value), 0)

    def test_other_numeric_shapes_still_work(self):
        from music_fetch.api import _safe_int

        self.assertEqual(_safe_int(42), 42)
        self.assertEqual(_safe_int(-7), -7)
        self.assertEqual(_safe_int("-7"), -7)
        self.assertEqual(_safe_int(" 42 "), 42)
        self.assertEqual(_safe_int("1e3"), 1000)
        self.assertEqual(_safe_int(3.9), 3)
