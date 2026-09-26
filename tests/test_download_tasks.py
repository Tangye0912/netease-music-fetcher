import unittest

from music_fetch.download_tasks import TASK_STATE_SUCCESS, is_valid_task_state


class DownloadTaskStateTests(unittest.TestCase):
    def test_known_states_are_valid(self):
        self.assertTrue(is_valid_task_state(TASK_STATE_SUCCESS))
        self.assertTrue(is_valid_task_state("downloading"))

    def test_unknown_state_is_rejected(self):
        self.assertFalse(is_valid_task_state("unknown"))
        self.assertFalse(is_valid_task_state(""))


if __name__ == "__main__":
    unittest.main()
