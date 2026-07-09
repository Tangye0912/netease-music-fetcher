import unittest
from unittest import mock

from music_fetch.api import MusicFetchError, UserPlaylist
from music_fetch.playlist_dialog import PlaylistFetchWorker


class PlaylistFetchWorkerTests(unittest.TestCase):
    """Test PlaylistFetchWorker (QThread) — mock fetch_user_playlists, verify signals."""

    def setUp(self):
        self.worker = PlaylistFetchWorker("MUSIC_U=test", timeout=10)

    @mock.patch("music_fetch.playlist_dialog.fetch_user_playlists")
    def test_succeeded_emits_playlists(self, fetch_mock):
        playlists = [
            UserPlaylist(playlist_id="1", name="My List", song_count=50, cover_url="", creator="Me"),
            UserPlaylist(playlist_id="2", name="Favorites", song_count=30, cover_url="", creator="Me"),
        ]
        fetch_mock.return_value = playlists
        emitted = []

        def on_succeeded(data):
            emitted.append(data)

        self.worker.succeeded.connect(on_succeeded)
        self.worker.run()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0], playlists)

    @mock.patch("music_fetch.playlist_dialog.fetch_user_playlists")
    def test_failed_emits_code_and_message(self, fetch_mock):
        fetch_mock.side_effect = MusicFetchError("AUTH_EXPIRED", "expired")
        emitted = []

        def on_failed(code, message):
            emitted.append((code, message))

        self.worker.failed.connect(on_failed)
        self.worker.run()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0][0], "AUTH_EXPIRED")

    @mock.patch("music_fetch.playlist_dialog.fetch_user_playlists")
    def test_failed_unexpected_error(self, fetch_mock):
        fetch_mock.side_effect = ValueError("bad data")
        emitted = []

        def on_failed(code, message):
            emitted.append((code, message))

        self.worker.failed.connect(on_failed)
        self.worker.run()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0][0], "UNKNOWN_ERROR")

    @mock.patch("music_fetch.playlist_dialog.fetch_user_playlists")
    def test_worker_passes_cookie_and_timeout(self, fetch_mock):
        fetch_mock.return_value = []
        self.worker.run()
        fetch_mock.assert_called_once_with("MUSIC_U=test", timeout=10)