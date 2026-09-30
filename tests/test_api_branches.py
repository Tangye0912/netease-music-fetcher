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
        parsed = parse.urlparse("https://music.163.com/playlist?id=42&userid=7")
        self.assertEqual(_extract_resource_id(parsed, "https://music.163.com/playlist?id=42&userid=7"), "42")

    def test_returns_empty_when_no_id_is_present(self):
        parsed = parse.urlparse("https://music.163.com/playlist")
        self.assertEqual(_extract_resource_id(parsed, "https://music.163.com/playlist"), "")

    def test_parse_input_resource_uses_the_fallback(self):
        resource_type, resource_id = parse_input_resource("https://music.163.com/album?id=99")
        self.assertEqual((resource_type, resource_id), ("album", "99"))


class PlayableCandidateBranchTests(unittest.TestCase):
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
        ):
            ids = fetch_playlist_song_ids("7", "MUSIC_U=test")
        self.assertEqual(len(ids), 1000)
        self.assertEqual(ids[0], "1")

    def test_the_first_page_failure_still_raises(self):
        with mock.patch(
            "music_fetch.api.perform_json_get", side_effect=MusicFetchError(ErrorCode.NETWORK_ERROR, "boom")
        ):
            with self.assertRaises(MusicFetchError):
                fetch_playlist_song_ids("7", "MUSIC_U=test")

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
