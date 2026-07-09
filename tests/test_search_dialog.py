import unittest
from unittest import mock

from music_fetch.api import MusicFetchError, SearchResult
from music_fetch.search_dialog import SearchWorker


class SearchWorkerTests(unittest.TestCase):
    """Test SearchWorker (QThread) — mock search_songs, verify signals."""

    def setUp(self):
        self.worker = SearchWorker("test", "MUSIC_U=test", timeout=10)

    @mock.patch("music_fetch.search_dialog.search_songs")
    def test_succeeded_emits_results(self, search_mock):
        results = [
            SearchResult(song_id="1", song_name="A", artist="B", album="C", duration_ms=1000),
            SearchResult(song_id="2", song_name="D", artist="E", album="F", duration_ms=2000),
        ]
        search_mock.return_value = results
        emitted = []

        def on_succeeded(data):
            emitted.append(data)

        self.worker.succeeded.connect(on_succeeded)
        self.worker.run()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0], results)

    @mock.patch("music_fetch.search_dialog.search_songs")
    def test_failed_emits_code_and_message(self, search_mock):
        search_mock.side_effect = MusicFetchError("NETWORK_ERROR", "timeout")
        emitted = []

        def on_failed(code, message):
            emitted.append((code, message))

        self.worker.failed.connect(on_failed)
        self.worker.run()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0][0], "NETWORK_ERROR")

    @mock.patch("music_fetch.search_dialog.search_songs")
    def test_failed_unexpected_error(self, search_mock):
        search_mock.side_effect = OSError("connection refused")
        emitted = []

        def on_failed(code, message):
            emitted.append((code, message))

        self.worker.failed.connect(on_failed)
        self.worker.run()
        self.assertEqual(len(emitted), 1)
        self.assertEqual(emitted[0][0], "UNKNOWN_ERROR")

    @mock.patch("music_fetch.search_dialog.search_songs")
    def test_worker_passes_keyword_and_cookie(self, search_mock):
        search_mock.return_value = []
        self.worker.run()
        search_mock.assert_called_once_with("test", "MUSIC_U=test", timeout=10)