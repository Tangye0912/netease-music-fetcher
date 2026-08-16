import unittest

import music_fetch.ui_texts as T


class UiTextsTests(unittest.TestCase):
    def test_code_message(self):
        self.assertEqual(T.code_message("DOWNLOAD_FAILED", "boom"), "DOWNLOAD_FAILED: boom")

    def test_manager_status_text_mapping(self):
        self.assertEqual(T.manager_status_text("success"), T.MANAGER_FILTER_SUCCESS)
        self.assertEqual(T.manager_status_text("FAILED"), T.MANAGER_FILTER_FAILED)
        self.assertEqual(T.manager_status_text("canceled"), T.MANAGER_FILTER_CANCELED)
        self.assertEqual(T.manager_status_text("pending"), T.MANAGER_FILTER_PENDING)
        self.assertEqual(T.manager_status_text("downloading"), T.MANAGER_FILTER_DOWNLOADING)
        self.assertEqual(T.manager_status_text("weird"), "weird")

    def test_batch_detect_status_text_mapping(self):
        self.assertEqual(T.batch_detect_status_text("ready"), T.BATCH_STATUS_READY)
        self.assertEqual(T.batch_detect_status_text("unavailable"), T.BATCH_STATUS_UNAVAILABLE)
        self.assertEqual(T.batch_detect_status_text("duplicate"), T.BATCH_STATUS_DUPLICATE)
        self.assertEqual(T.batch_detect_status_text("download_success"), T.BATCH_STATUS_DOWNLOAD_SUCCESS)
        self.assertEqual(T.batch_detect_status_text("download_failed"), T.BATCH_STATUS_DOWNLOAD_FAILED)
        self.assertEqual(T.batch_detect_status_text("download_canceled"), T.BATCH_STATUS_DOWNLOAD_CANCELED)
        self.assertEqual(T.batch_detect_status_text(""), T.MSG_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
