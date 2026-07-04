"""Tests for music_fetch.app_logging.py — setup_logging, get_logger, mask_value, default_log_path."""

import logging
import tempfile
import unittest
from pathlib import Path

from music_fetch.app_logging import (
    default_log_path,
    get_logger,
    mask_value,
    setup_logging,
)


class DefaultLogPathTests(unittest.TestCase):
    def test_returns_path(self):
        path = default_log_path()
        self.assertIsInstance(path, Path)
        self.assertIn("music-fetch", str(path))


class GetLoggerTests(unittest.TestCase):
    def test_returns_logger(self):
        logger = get_logger("music_fetch.test")
        self.assertIsInstance(logger, logging.Logger)
        self.assertEqual(logger.name, "music_fetch.test")


class MaskValueTests(unittest.TestCase):
    def test_empty_string(self):
        self.assertEqual(mask_value(""), "")

    def test_none(self):
        self.assertEqual(mask_value(None), "")

    def test_short_value(self):
        self.assertEqual(mask_value("abc"), "***")

    def test_normal_value(self):
        result = mask_value("MUSIC_U=abc123def456")
        self.assertTrue(result.startswith("MUSI"))
        self.assertTrue(result.endswith("f456"))
        self.assertIn("***", result)

    def test_exact_length_boundary(self):
        # 8 chars = keep_prefix(4) + keep_suffix(4) => masked entirely
        result = mask_value("12345678")
        self.assertEqual(result, "********")


class SetupLoggingTests(unittest.TestCase):
    def setUp(self):
        self._saved_handlers = list(logging.getLogger("music_fetch").handlers)

    def tearDown(self):
        root = logging.getLogger("music_fetch")
        for h in root.handlers[:]:
            if h not in self._saved_handlers:
                h.close()
                root.removeHandler(h)

    def test_sets_up_file_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "test.log"
            result = setup_logging(log_path)
            self.assertEqual(result, log_path)
            self.assertTrue(log_path.exists())
            # Close handlers so tempdir can be cleaned up on Windows
            root = logging.getLogger("music_fetch")
            for h in root.handlers[:]:
                if h not in self._saved_handlers:
                    h.close()
                    root.removeHandler(h)

    def test_returns_default_when_none(self):
        import music_fetch.app_logging
        old_default = music_fetch.app_logging._DEFAULT_LOG_PATH
        with tempfile.TemporaryDirectory() as tmp:
            try:
                music_fetch.app_logging._DEFAULT_LOG_PATH = Path(tmp) / "default.log"
                result = setup_logging()
                self.assertTrue(result.exists())
            finally:
                music_fetch.app_logging._DEFAULT_LOG_PATH = old_default
                root = logging.getLogger("music_fetch")
                for h in root.handlers[:]:
                    if h not in self._saved_handlers:
                        h.close()
                        root.removeHandler(h)

    def test_does_not_duplicate_handler(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "test.log"
            setup_logging(log_path)
            root = logging.getLogger("music_fetch")
            handler_count_before = len(root.handlers)
            setup_logging(log_path)
            self.assertEqual(len(root.handlers), handler_count_before)
            for h in root.handlers[:]:
                if h not in self._saved_handlers:
                    h.close()
                    root.removeHandler(h)


if __name__ == "__main__":
    unittest.main()