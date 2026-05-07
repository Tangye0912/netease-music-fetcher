import pathlib
import tomllib
import unittest


class PackagingConfigTests(unittest.TestCase):
    def test_pyproject_declares_flat_modules_and_cli_script(self):
        data = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["build-system"]["build-backend"], "setuptools.build_meta")
        self.assertEqual(data["project"]["scripts"]["music-fetch"], "_cli:main")
        modules = data["tool"]["setuptools"]["py-modules"]
        for module_name in ("music_fetch", "_api", "_audio", "_batch_dialogs", "_batch_results", "_cli", "main"):
            self.assertIn(module_name, modules)
        self.assertNotIn("packages", data["tool"]["setuptools"])


if __name__ == "__main__":
    unittest.main()
