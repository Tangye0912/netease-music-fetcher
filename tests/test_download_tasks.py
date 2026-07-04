import unittest
from pathlib import Path

from music_fetch.download_tasks import (
    TASK_STATE_CANCELED,
    TASK_STATE_DOWNLOADING,
    TASK_STATE_FAILED,
    TASK_STATE_PENDING,
    TASK_STATE_SUCCESS,
    DownloadTaskSnapshot,
    build_task_id,
    next_task_snapshot,
    normalize_task_state,
)


class DownloadTaskStateTests(unittest.TestCase):
    def test_build_task_id_uses_song_id_and_timestamp(self):
        self.assertEqual(build_task_id("321", now_ms=99), "321-99")

    def test_normalize_state_success(self):
        self.assertEqual(normalize_task_state(" SUCCESS "), TASK_STATE_SUCCESS)

    def test_normalize_state_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            normalize_task_state("unknown")

    def test_next_task_snapshot_creates_new_task_id(self):
        snapshot = next_task_snapshot(
            None,
            song_id="123",
            output_path=Path("/tmp/a.mp3"),
            state=TASK_STATE_PENDING,
            now_ms=1000,
        )
        self.assertEqual(snapshot.task_id, "123-1000")
        self.assertEqual(snapshot.state, TASK_STATE_PENDING)

    def test_next_task_snapshot_reuses_task_id_for_same_song(self):
        first = DownloadTaskSnapshot(
            task_id="123-1000",
            song_id="123",
            output_path="/tmp/a.mp3",
            state=TASK_STATE_PENDING,
        )
        second = next_task_snapshot(
            first,
            song_id="123",
            output_path=Path("/tmp/a.mp3"),
            state=TASK_STATE_DOWNLOADING,
        )
        self.assertEqual(second.task_id, first.task_id)
        self.assertEqual(second.state, TASK_STATE_DOWNLOADING)

    def test_next_task_snapshot_generates_new_task_for_new_song(self):
        first = DownloadTaskSnapshot(
            task_id="123-1000",
            song_id="123",
            output_path="/tmp/a.mp3",
            state=TASK_STATE_SUCCESS,
        )
        second = next_task_snapshot(
            first,
            song_id="456",
            output_path=Path("/tmp/b.mp3"),
            state=TASK_STATE_FAILED,
            error_code="NETWORK_ERROR",
            now_ms=2000,
        )
        self.assertEqual(second.task_id, "456-2000")
        self.assertEqual(second.error_code, "NETWORK_ERROR")

    def test_next_task_snapshot_can_mark_canceled(self):
        snapshot = DownloadTaskSnapshot(
            task_id="123-1000",
            song_id="123",
            output_path="/tmp/a.mp3",
            state=TASK_STATE_DOWNLOADING,
        )
        canceled = next_task_snapshot(
            snapshot,
            song_id="123",
            output_path=Path("/tmp/a.mp3"),
            state=TASK_STATE_CANCELED,
        )
        self.assertEqual(canceled.state, TASK_STATE_CANCELED)


if __name__ == "__main__":
    unittest.main()
