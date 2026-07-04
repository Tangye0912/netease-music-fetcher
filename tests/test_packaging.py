import pathlib
import tomllib
import unittest


class PackagingConfigTests(unittest.TestCase):
    def test_pyproject_declares_package_and_cli_script(self):
        data = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["build-system"]["build-backend"], "setuptools.build_meta")
        self.assertEqual(data["project"]["scripts"]["music-fetch"], "music_fetch.cli:main")
        self.assertIn("music_fetch", data["tool"]["setuptools"]["packages"])


if __name__ == "__main__":
    unittest.main()