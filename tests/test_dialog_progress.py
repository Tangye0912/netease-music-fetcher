"""Tests for dialog_progress.py — button state and callback logic."""
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication
_app = QApplication.instance()
if _app is None:
    _app = QApplication(["test"])

from music_fetch.dialog_progress import DownloadProgressDialog
from music_fetch.download_tasks import (
    TASK_STATE_CANCELED,
    TASK_STATE_DOWNLOADING,
    TASK_STATE_FAILED,
    TASK_STATE_PENDING,
    TASK_STATE_SUCCESS,
)


def _make_dialog(notify_each_result: bool = False) -> DownloadProgressDialog:
    """Create a dialog with worker creation mocked out."""
    with mock.patch("music_fetch.workers.DownloadWorker"):
        dialog = DownloadProgressDialog(
            task_id="test-task",
            song_id="12345",
            output_path=Path("/tmp/test.mp3"),
            cookie="MUSIC_U=test",
            target_format="mp3",
            timeout=10,
            retry_count=1,
            notify_each_result=notify_each_result,
        )
    return dialog


class DownloadProgressDialogButtonTests(unittest.TestCase):
    def setUp(self):
        self.dialog = _make_dialog()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()

    def test_initial_state(self):
        self.assertEqual(self.dialog.result_state, TASK_STATE_DOWNLOADING)
        self.assertTrue(self.dialog._pause_button_is_pause)
        self.assertEqual(self.dialog.error_code, "")

    def test_pause_button_toggles_text(self):
        # Pause
        self.dialog._on_pause_resume()
        self.assertFalse(self.dialog._pause_button_is_pause)
        self.dialog.worker.request_pause.assert_called_once()

        # Resume
        self.dialog._on_pause_resume()
        self.assertTrue(self.dialog._pause_button_is_pause)
        self.dialog.worker.request_resume.assert_called_once()

    def test_cancel_disables_buttons(self):
        self.dialog._on_cancel()
        self.assertFalse(self.dialog.cancel_button.isEnabled())
        self.assertFalse(self.dialog.pause_button.isEnabled())
        self.assertEqual(self.dialog.result_state, TASK_STATE_CANCELED)
        self.dialog.worker.request_cancel.assert_called_once()

    def test_on_failed_disables_pause_and_sets_state(self):
        self.dialog._on_failed("DOWNLOAD_FAILED", "error msg")
        self.assertEqual(self.dialog.result_state, TASK_STATE_FAILED)
        self.assertEqual(self.dialog.error_code, "DOWNLOAD_FAILED")
        self.assertFalse(self.dialog.pause_button.isEnabled())

    def test_on_canceled_disables_pause_and_sets_state(self):
        self.dialog._on_canceled()
        self.assertEqual(self.dialog.result_state, TASK_STATE_CANCELED)
        self.assertFalse(self.dialog.pause_button.isEnabled())

    def test_on_succeeded_disables_pause_and_sets_state(self):
        self.dialog._on_succeeded("/tmp/test.mp3", 12345)
        self.assertEqual(self.dialog.result_state, TASK_STATE_SUCCESS)
        self.assertFalse(self.dialog.pause_button.isEnabled())
        self.assertEqual(self.dialog.output_path, Path("/tmp/test.mp3"))

    def test_on_progress_with_total(self):
        self.dialog._on_progress(50, 100, 1024.0)
        self.assertEqual(self.dialog.progress_bar.maximum(), 100)
        self.assertEqual(self.dialog.progress_bar.value(), 50)

    def test_on_progress_unknown_total(self):
        self.dialog._on_progress(50, 0, 512.0)
        self.assertEqual(self.dialog.progress_bar.maximum(), 0)  # busy indicator


if __name__ == "__main__":
    unittest.main()
