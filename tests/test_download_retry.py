import unittest
from pathlib import Path

from music_fetch.app_settings import DEFAULT_GUI_TARGET_FORMAT
from music_fetch.download_retry import can_retry_status, retry_target_format


class DownloadRetryTests(unittest.TestCase):
    def test_can_retry_only_failed_status(self):
        self.assertTrue(can_retry_status("failed"))
        self.assertFalse(can_retry_status("success"))
        self.assertFalse(can_retry_status("canceled"))

    def test_retry_target_format_uses_known_suffix(self):
        self.assertEqual(retry_target_format(Path("/tmp/demo.flac")), "flac")

    def test_retry_target_format_falls_back_to_default(self):
        self.assertEqual(retry_target_format(Path("/tmp/demo.unknown")), DEFAULT_GUI_TARGET_FORMAT)


if __name__ == "__main__":
    unittest.main()
