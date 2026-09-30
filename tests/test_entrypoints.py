import importlib
import os
import subprocess
import unittest
from pathlib import Path

import tomllib

# Resolve repo files from this file's location so the suite passes regardless of
# the working directory pytest is invoked from.
REPO_ROOT = Path(__file__).resolve().parents[1]


class EntryPointTests(unittest.TestCase):
    def test_app_module_is_importable(self):
        spec = importlib.util.find_spec("music_fetch.app")
        self.assertIsNotNone(spec, "music_fetch.app module should be importable")

    def test_cli_module_removed(self):
        spec = importlib.util.find_spec("music_fetch.cli")
        self.assertIsNone(spec, "music_fetch.cli module should no longer exist")

    def test_eapi_module_removed(self):
        spec = importlib.util.find_spec("music_fetch.eapi")
        self.assertIsNone(spec, "music_fetch.eapi was dead code and should be gone")

    def test_pyproject_script_points_to_app_main(self):
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["project"]["scripts"]["music-fetch"], "music_fetch.app:main")

    def test_pyproject_has_no_qt_dependencies(self):
        data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        deps = data["project"]["dependencies"]
        for dep in deps:
            self.assertNotIn("PySide6", dep)
            self.assertNotIn("qt-material", dep)
        self.assertIn("prompt-toolkit", " ".join(deps).lower())

    @unittest.skipIf(os.name == "nt", "shell wrapper not available on Windows")
    def test_music_fetch_shell_wrapper_reports_script_mode_removed(self):
        proc = subprocess.run(
            [str(REPO_ROOT / "music-fetch"), "--help"],
            capture_output=True,
            text=True,
            check=False,
            cwd=str(REPO_ROOT),
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("脚本模式已在 v3.4 移除", proc.stderr)


if __name__ == "__main__":
    unittest.main()
