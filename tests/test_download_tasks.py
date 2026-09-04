import unittest

from music_fetch.download_tasks import (
    TASK_STATE_SUCCESS,
    build_task_id,
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


if __name__ == "__main__":
    unittest.main()
