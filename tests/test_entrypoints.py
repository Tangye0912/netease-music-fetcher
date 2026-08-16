import importlib
import os
import subprocess
import unittest
from pathlib import Path

import tomllib


class EntryPointTests(unittest.TestCase):
    def test_app_module_is_importable(self):
        spec = importlib.util.find_spec("music_fetch.app")
        self.assertIsNotNone(spec, "music_fetch.app module should be importable")

    def test_cli_module_still_importable(self):
        spec = importlib.util.find_spec("music_fetch.cli")
        self.assertIsNotNone(spec, "music_fetch.cli module should be importable")

    def test_pyproject_script_points_to_app_main(self):
        data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["scripts"]["music-fetch"], "music_fetch.app:main")

    def test_pyproject_has_no_qt_dependencies(self):
        data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
        deps = data["project"]["dependencies"]
        for dep in deps:
            self.assertNotIn("PySide6", dep)
            self.assertNotIn("qt-material", dep)
        self.assertIn("prompt-toolkit", " ".join(deps).lower())

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


if __name__ == "__main__":
    unittest.main()
