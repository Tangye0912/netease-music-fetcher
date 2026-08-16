import pathlib
import tomllib
import unittest


class PackagingConfigTests(unittest.TestCase):
    def test_pyproject_declares_package_and_cli_script(self):
        data = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))
        self.assertEqual(data["build-system"]["build-backend"], "setuptools.build_meta")
        self.assertEqual(data["project"]["scripts"]["music-fetch"], "music_fetch.app:main")
        self.assertIn("music_fetch", data["tool"]["setuptools"]["packages"])

    def test_spec_builds_console_app(self):
        spec = pathlib.Path("music-fetch.spec").read_text(encoding="utf-8")
        self.assertIn("music_fetch/app.py", spec)
        self.assertIn("console=True", spec)

    def test_spec_collects_runtime_proxy_dependencies(self):
        spec = pathlib.Path("music-fetch.spec").read_text(encoding="utf-8")
        for module in ("requests", "socks", "urllib3.contrib.socks"):
            with self.subTest(module=module):
                self.assertIn(f"'{module}'", spec)


if __name__ == "__main__":
    unittest.main()
