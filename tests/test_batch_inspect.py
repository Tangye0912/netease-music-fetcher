import threading
import unittest
from unittest import mock

from music_fetch.api import MusicFetchError, SongDetectionResult
from music_fetch.batch_inspect import run_batch_detect


class BatchInspectTests(unittest.TestCase):
    def _detect_result(self, song_id: str, can_download: bool = True) -> SongDetectionResult:
        return SongDetectionResult(
            song_id=song_id,
            song_name=f"Song {song_id}",
            duration_ms=120000,
            media_url="https://example.com/song.mp3" if can_download else None,
            can_download=can_download,
            unavailable_reason="" if can_download else "VIP only",
            artist="",
            album_name="",
            cover_url=None,
        )

    @mock.patch("music_fetch.batch_inspect.probe_media_size_bytes", return_value=0)
    @mock.patch("music_fetch.batch_inspect.detect_song")
    def test_detects_single_song(self, mock_detect, _mock_probe):
        mock_detect.return_value = self._detect_result("100")
        rows = run_batch_detect("https://music.163.com/song?id=100", "MUSIC_U=test", timeout=5)
        ready = [r for r in rows if r.status == "ready"]
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].song_id, "100")

    @mock.patch("music_fetch.batch_inspect.detect_song")
    def test_detect_failure_creates_failed_row(self, mock_detect):
        mock_detect.side_effect = MusicFetchError("SONG_UNAVAILABLE", "not available")
        rows = run_batch_detect("https://music.163.com/song?id=200", "MUSIC_U=test", timeout=5)
        failed = [r for r in rows if r.status == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn("SONG_UNAVAILABLE", failed[0].message)

    @mock.patch("music_fetch.batch_inspect.probe_media_size_bytes", return_value=0)
    @mock.patch("music_fetch.batch_inspect.detect_song")
    def test_unavailable_song_marks_unavailable(self, mock_detect, _mock_probe):
        mock_detect.return_value = self._detect_result("300", can_download=False)
        rows = run_batch_detect("https://music.163.com/song?id=300", "MUSIC_U=test", timeout=5)
        unavailable = [r for r in rows if r.status == "unavailable"]
        self.assertEqual(len(unavailable), 1)
        self.assertFalse(unavailable[0].selected)

    def test_empty_input_returns_empty(self):
        self.assertEqual(run_batch_detect("", "MUSIC_U=test", timeout=5), [])

    @mock.patch("music_fetch.batch_inspect.probe_media_size_bytes", return_value=0)
    @mock.patch("music_fetch.batch_inspect.detect_song")
    def test_duplicate_song_ids_are_marked(self, mock_detect, _mock_probe):
        mock_detect.return_value = self._detect_result("100")
        # Two different URL forms that resolve to the same song id.
        raw = "\n".join([
            "https://music.163.com/song?id=100",
            "https://music.163.com/#/song?id=100",
        ])
        rows = run_batch_detect(raw, "MUSIC_U=test", timeout=5)
        ready = [r for r in rows if r.status == "ready"]
        duplicate = [r for r in rows if r.status == "duplicate"]
        self.assertEqual(len(ready), 1)
        self.assertEqual(len(duplicate), 1)

    @mock.patch("music_fetch.batch_inspect.probe_media_size_bytes", return_value=0)
    @mock.patch("music_fetch.batch_inspect.detect_song")
    def test_cancel_stops_queued_detection_and_preserves_completed_row(self, mock_detect, mock_probe):
        cancel_event = threading.Event()

        def detect_then_cancel(song_id, *_args, **_kwargs):
            cancel_event.set()
            return self._detect_result(song_id)

        mock_detect.side_effect = detect_then_cancel

        raw = "\n".join([
            "https://music.163.com/song?id=100",
            "https://music.163.com/song?id=200",
            "https://music.163.com/song?id=300",
        ])
        rows = run_batch_detect(
            raw, "MUSIC_U=test", timeout=5,
            detect_concurrency=1, cancel_event=cancel_event,
        )
        self.assertEqual(mock_detect.call_count, 1)
        self.assertEqual([row.song_id for row in rows if row.status == "ready"], ["100"])
        mock_probe.assert_not_called()

    @mock.patch("music_fetch.batch_inspect.probe_media_size_bytes", return_value=0)
    @mock.patch("music_fetch.batch_inspect.detect_song")
    def test_progress_callback_reports_completion(self, mock_detect, _mock_probe):
        mock_detect.return_value = self._detect_result("100")
        progress = []
        run_batch_detect(
            "https://music.163.com/song?id=100", "MUSIC_U=test", timeout=5,
            on_progress=lambda current, total, song_id: progress.append((current, total, song_id)),
        )
        self.assertEqual(progress, [(1, 1, "100")])


if __name__ == "__main__":
    unittest.main()
