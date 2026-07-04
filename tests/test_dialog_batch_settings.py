"""Tests for _dialog_batch_settings.py — BatchRuntimeSettingsDialog."""

import unittest

from PySide6.QtWidgets import QApplication
_app = QApplication.instance()
if _app is None:
    _app = QApplication(["test"])

from PySide6.QtWidgets import QDialog

from _dialog_batch_settings import BatchRuntimeSettingsDialog


class BatchRuntimeSettingsDialogTests(unittest.TestCase):
    def test_creates_with_defaults(self):
        dlg = BatchRuntimeSettingsDialog(
            detect_timeout_sec=5,
            download_timeout_sec=10,
            download_retry_count=1,
            download_concurrency=2,
        )
        self.assertIsInstance(dlg, QDialog)
        self.assertEqual(dlg.detect_timeout_sec, 5)
        self.assertEqual(dlg.download_timeout_sec, 10)
        self.assertEqual(dlg.download_retry_count, 1)
        self.assertEqual(dlg.download_concurrency, 2)
        dlg.close()

    def test_clamps_extreme_values(self):
        dlg = BatchRuntimeSettingsDialog(
            detect_timeout_sec=9999,
            download_timeout_sec=9999,
            download_retry_count=9999,
            download_concurrency=9999,
        )
        from app_settings import (
            MAX_DETECT_TIMEOUT_SEC,
            MAX_DOWNLOAD_CONCURRENCY,
            MAX_DOWNLOAD_RETRY_COUNT,
            MAX_DOWNLOAD_TIMEOUT_SEC,
        )
        self.assertLessEqual(dlg.detect_timeout_sec, MAX_DETECT_TIMEOUT_SEC)
        self.assertLessEqual(dlg.download_timeout_sec, MAX_DOWNLOAD_TIMEOUT_SEC)
        self.assertLessEqual(dlg.download_retry_count, MAX_DOWNLOAD_RETRY_COUNT)
        self.assertLessEqual(dlg.download_concurrency, MAX_DOWNLOAD_CONCURRENCY)
        dlg.close()

    def test_save_updates_values(self):
        dlg = BatchRuntimeSettingsDialog(
            detect_timeout_sec=5,
            download_timeout_sec=10,
            download_retry_count=1,
            download_concurrency=2,
        )
        # Simulate changing combo values and saving
        dlg._on_save()
        self.assertEqual(dlg.result(), QDialog.Accepted)
        dlg.close()


if __name__ == "__main__":
    unittest.main()