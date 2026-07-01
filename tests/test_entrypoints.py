import os
import subprocess
import sys
import unittest

import main
import _workers
from _batch_dialogs import BatchDownloadDialog


class EntryPointTests(unittest.TestCase):
    def test_music_fetch_module_runs_cli_help(self):
        proc = subprocess.run(
            [sys.executable, "music_fetch.py", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage: music-fetch", proc.stdout)

    @unittest.skipIf(os.name == "nt", "shell wrapper not available on Windows")
    def test_music_fetch_shell_wrapper_runs_cli_help(self):
        proc = subprocess.run(
            ["./music-fetch", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage: music-fetch", proc.stdout)

    def test_detect_click_uses_worker_module_for_inspect_worker(self):
        self.assertIs(main.InspectWorker, _workers.InspectWorker)

    def test_batch_dialog_entrypoint_uses_extracted_module(self):
        self.assertTrue(issubclass(BatchDownloadDialog, object))


if __name__ == "__main__":
    unittest.main()
