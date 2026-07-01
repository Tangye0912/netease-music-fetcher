"""Tests for BatchDownloadDialog pure-logic methods and download scheduling."""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

# QApplication is needed for QWidget-based dialog; create a minimal instance.
from PySide6.QtWidgets import QApplication
_app = QApplication.instance()
if _app is None:
    _app = QApplication(["test"])

from _batch_dialogs import BatchDownloadDialog
from _workers import BatchDetectRow, DownloadWorker
from app_stores import DownloadHistoryStore, DownloadRecord
from download_tasks import TASK_STATE_FAILED, TASK_STATE_PENDING, TASK_STATE_SUCCESS


def _make_row(song_id: str, status: str = "ready", selected: bool = True) -> BatchDetectRow:
    return BatchDetectRow(
        raw_input=f"https://music.163.com/song?id={song_id}",
        source_type="song",
        source_label=f"song-{song_id}",
        song_id=song_id,
        song_name=f"Song {song_id}",
        status=status,
        selected=selected,
    )


class BatchDialogSelectionTests(unittest.TestCase):
    """Tests for row selection logic (no QApplication required beyond the
    module-level _app)."""

    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.history_path = Path(tmp) / "test_history.json"
        self.history_store = DownloadHistoryStore(self.history_path)
        self.dialog = BatchDownloadDialog(
            cookie="MUSIC_U=test",
            history_store=self.history_store,
            last_download_dir=str(Path(tmp).resolve()),
            detect_timeout_sec=5,
            download_timeout_sec=10,
            download_retry_count=1,
            download_concurrency=1,
        )

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()

    def test_selected_ready_rows_filters_correctly(self):
        self.dialog.rows = [
            _make_row("1", status="ready", selected=True),
            _make_row("2", status="ready", selected=False),
            _make_row("3", status="unavailable", selected=True),
            _make_row("4", status="download_failed", selected=True),
        ]
        selected = self.dialog._selected_ready_rows()
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].song_id, "1")

    def test_input_changed_since_detect_returns_false_initially(self):
        self.assertFalse(self.dialog._input_changed_since_detect())

    def test_input_changed_since_detect_detects_change(self):
        self.dialog._last_detect_signature = "old input"
        self.dialog.input_edit.setPlainText("new input")
        self.assertTrue(self.dialog._input_changed_since_detect())

    def test_select_all_toggles_selection(self):
        self.dialog.rows = [
            _make_row("1", status="ready", selected=True),
            _make_row("2", status="ready", selected=False),
            _make_row("3", status="ready", selected=False),
        ]
        # Not all ready are selected -> should select all
        self.dialog._on_select_all_ready()
        self.assertTrue(all(row.selected for row in self.dialog.rows if row.status == "ready"))

        # All ready are selected -> should clear all
        self.dialog._on_select_all_ready()
        self.assertFalse(any(row.selected for row in self.dialog.rows if row.status == "ready"))

    def test_invert_selection_flips_all(self):
        self.dialog.rows = [
            _make_row("1", status="ready", selected=True),
            _make_row("2", status="ready", selected=False),
            _make_row("3", status="ready", selected=True),
        ]
        self.dialog._on_invert_ready_selection()
        self.assertFalse(self.dialog.rows[0].selected)
        self.assertTrue(self.dialog.rows[1].selected)
        self.assertFalse(self.dialog.rows[2].selected)

    def test_select_all_skips_non_ready_rows(self):
        self.dialog.rows = [
            _make_row("1", status="ready", selected=True),
            _make_row("2", status="unavailable", selected=False),
            _make_row("3", status="failed", selected=False),
        ]
        self.dialog._on_select_all_ready()
        self.assertFalse(self.dialog.rows[0].selected)
        self.assertFalse(self.dialog.rows[1].selected)  # unchanged
        self.assertFalse(self.dialog.rows[2].selected)  # unchanged


class BatchDialogDownloadSchedulingTests(unittest.TestCase):
    """Tests for download scheduling logic using mock workers."""

    def setUp(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.history_path = Path(tmp) / "test_history.json"
        self.history_store = DownloadHistoryStore(self.history_path)
        self.dialog = BatchDownloadDialog(
            cookie="MUSIC_U=test",
            history_store=self.history_store,
            last_download_dir=str(Path(tmp).resolve()),
            detect_timeout_sec=5,
            download_timeout_sec=10,
            download_retry_count=1,
            download_concurrency=2,
        )

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()

    def test_start_download_rows_initializes_state(self):
        rows = [_make_row("1"), _make_row("2"), _make_row("3")]
        self.dialog.out_dir_input.setText("/tmp/test")
        # Mock _dispatch_download_workers to avoid actually starting workers
        self.dialog._dispatch_download_workers = mock.MagicMock()

        self.dialog._start_download_rows(rows)

        self.assertTrue(self.dialog._downloading)
        self.assertEqual(self.dialog._download_total, 3)
        self.assertEqual(self.dialog._download_cursor, 0)
        self.assertEqual(self.dialog._download_next_index, 0)
        self.assertEqual(self.dialog._download_success, 0)
        self.assertEqual(self.dialog._download_failed, 0)
        self.assertEqual(self.dialog._download_canceled, 0)
        self.assertEqual(len(self.dialog._download_queue), 3)
        self.assertEqual(len(self.dialog._download_workers), 0)
        self.assertFalse(self.dialog.input_edit.isEnabled())
        # cancel_download_button visibility: setVisible(True) is called,
        # but isVisible() may be False if the dialog itself isn't shown yet.
        self.assertFalse(self.dialog.cancel_download_button.isHidden())
        self.dialog._dispatch_download_workers.assert_called_once()

    def test_stop_download_flow_cleans_up_state(self):
        self.dialog._downloading = True
        self.dialog._download_total = 5
        self.dialog._download_cursor = 3
        self.dialog._download_success = 2
        self.dialog._download_failed = 1
        self.dialog._download_canceled = 0
        self.dialog._download_workers = {1: mock.MagicMock()}
        self.dialog._download_queue = [_make_row("1")]
        self.dialog._download_next_index = 3

        self.dialog._stop_download_flow(stopped=False)

        self.assertFalse(self.dialog._downloading)
        self.assertEqual(len(self.dialog._download_workers), 0)
        self.assertEqual(len(self.dialog._download_queue), 0)
        self.assertEqual(self.dialog._download_next_index, 0)
        self.assertTrue(self.dialog.input_edit.isEnabled())
        self.assertFalse(self.dialog.cancel_download_button.isVisible())

    def test_stop_download_flow_stopped_shows_pending(self):
        self.dialog._downloading = True
        self.dialog._download_total = 5
        self.dialog._download_cursor = 2
        self.dialog.rows = []

        self.dialog._stop_download_flow(stopped=True)

        self.assertIn("3", self.dialog.status_label.text())  # pending = 5-2 = 3

    def test_finalize_download_worker_increments_cursor_and_dispatches(self):
        row = _make_row("1")
        self.dialog._downloading = True
        self.dialog._download_total = 1
        self.dialog._download_cursor = 0
        self.dialog._download_next_index = 1
        worker = mock.MagicMock(spec=DownloadWorker)
        key = id(worker)
        self.dialog._download_workers = {key: worker}
        self.dialog._worker_rows = {key: row}
        self.dialog._worker_output_paths = {key: Path("/tmp/test/1.mp3")}
        self.dialog._dispatch_download_workers = mock.MagicMock()

        self.dialog._finalize_download_worker(worker)

        self.assertEqual(self.dialog._download_cursor, 1)
        self.assertNotIn(key, self.dialog._download_workers)
        self.assertNotIn(key, self.dialog._worker_rows)
        self.assertNotIn(key, self.dialog._worker_output_paths)
        # Since cursor >= total and no workers, _stop_download_flow should be called
        # (dispatched via _dispatch_download_workers check at the end of _finalize)

    def test_on_download_succeeded_updates_row_and_history(self):
        row = _make_row("1", selected=True)
        self.dialog.rows = [row]
        self.dialog._downloading = True
        self.dialog._download_total = 1
        self.dialog._download_cursor = 0
        self.dialog._download_success = 0
        worker = mock.MagicMock(spec=DownloadWorker)
        key = id(worker)
        output_path = "/tmp/test/1.mp3"
        self.dialog._download_workers = {key: worker}
        self.dialog._worker_rows = {key: row}
        self.dialog._worker_output_paths = {key: Path(output_path)}
        self.dialog._finalize_download_worker = mock.MagicMock()

        self.dialog._on_download_succeeded(worker, output_path, 12345)

        self.assertEqual(row.status, "download_success")
        self.assertFalse(row.selected)
        self.assertEqual(row.media_size_bytes, 12345)
        self.assertEqual(row.message, "1.mp3")
        self.assertEqual(self.dialog._download_success, 1)
        self.dialog._finalize_download_worker.assert_called_once_with(worker)
        # Verify history was recorded
        records = self.history_store.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, TASK_STATE_SUCCESS)
        self.assertEqual(records[0].song_id, "1")

    def test_on_download_failed_updates_row_and_history(self):
        row = _make_row("1", selected=True)
        self.dialog.rows = [row]
        self.dialog._downloading = True
        self.dialog._download_total = 1
        self.dialog._download_failed = 0
        worker = mock.MagicMock(spec=DownloadWorker)
        key = id(worker)
        output_path = Path("/tmp/test/1.mp3")
        self.dialog._download_workers = {key: worker}
        self.dialog._worker_rows = {key: row}
        self.dialog._worker_output_paths = {key: output_path}
        self.dialog._finalize_download_worker = mock.MagicMock()

        self.dialog._on_download_failed(worker, "NETWORK_ERROR", "timeout")

        self.assertEqual(row.status, "download_failed")
        self.assertFalse(row.selected)
        self.assertEqual(self.dialog._download_failed, 1)
        self.dialog._finalize_download_worker.assert_called_once_with(worker)
        records = self.history_store.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, TASK_STATE_FAILED)
        self.assertEqual(records[0].error_code, "NETWORK_ERROR")

    def test_on_download_canceled_updates_row_and_history(self):
        row = _make_row("1", selected=True)
        self.dialog.rows = [row]
        self.dialog._downloading = True
        self.dialog._download_total = 1
        self.dialog._download_canceled = 0
        worker = mock.MagicMock(spec=DownloadWorker)
        key = id(worker)
        output_path = Path("/tmp/test/1.mp3")
        self.dialog._download_workers = {key: worker}
        self.dialog._worker_rows = {key: row}
        self.dialog._worker_output_paths = {key: output_path}
        self.dialog._finalize_download_worker = mock.MagicMock()

        self.dialog._on_download_canceled(worker)

        self.assertEqual(row.status, "download_canceled")
        self.assertFalse(row.selected)
        self.assertEqual(self.dialog._download_canceled, 1)
        self.dialog._finalize_download_worker.assert_called_once_with(worker)
        records = self.history_store.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, "canceled")

    def test_on_download_worker_finished_defensive_cleanup(self):
        row = _make_row("1", selected=True)
        row.status = "downloading"
        self.dialog._downloading = True
        self.dialog._download_total = 1
        self.dialog._download_failed = 0
        worker = mock.MagicMock(spec=DownloadWorker)
        key = id(worker)
        output_path = Path("/tmp/test/1.mp3")
        self.dialog._download_workers = {key: worker}
        self.dialog._worker_rows = {key: row}
        self.dialog._worker_output_paths = {key: output_path}
        self.dialog._finalize_download_worker = mock.MagicMock()

        self.dialog._on_download_worker_finished(worker)

        self.assertEqual(row.status, "download_failed")
        self.assertEqual(self.dialog._download_failed, 1)
        self.dialog._finalize_download_worker.assert_called_once_with(worker)
        records = self.history_store.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, TASK_STATE_FAILED)
        self.assertEqual(records[0].error_code, "UNKNOWN_ERROR")

    def test_on_download_worker_finished_already_handled_is_noop(self):
        # Worker already removed from _download_workers (by succeeded/failed callback)
        worker = mock.MagicMock(spec=DownloadWorker)
        self.dialog._download_failed = 0
        self.dialog._finalize_download_worker = mock.MagicMock()

        self.dialog._on_download_worker_finished(worker)

        self.assertEqual(self.dialog._download_failed, 0)
        self.dialog._finalize_download_worker.assert_not_called()

    def test_cancel_download_requests_all_workers(self):
        w1 = mock.MagicMock(spec=DownloadWorker)
        w2 = mock.MagicMock(spec=DownloadWorker)
        self.dialog._downloading = True
        self.dialog._download_workers = {id(w1): w1, id(w2): w2}

        self.dialog._on_cancel_download_clicked()

        self.assertTrue(self.dialog._download_cancel_requested)
        w1.request_cancel.assert_called_once()
        w2.request_cancel.assert_called_once()

    def test_cancel_download_with_no_workers_stops_flow(self):
        self.dialog._downloading = True
        self.dialog._download_workers = {}
        self.dialog._stop_download_flow = mock.MagicMock()

        self.dialog._on_cancel_download_clicked()

        self.dialog._stop_download_flow.assert_called_once_with(stopped=True)


if __name__ == "__main__":
    unittest.main()