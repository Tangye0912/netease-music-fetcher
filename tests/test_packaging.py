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

    def test_spec_does_not_reference_removed_modules(self):
        """Guard against the frozen build re-importing deleted modules."""
        spec = pathlib.Path("music-fetch.spec").read_text(encoding="utf-8")
        for removed in ("batch_download", "music_fetch.cli", "weapi", "qrcode"):
            with self.subTest(removed=removed):
                self.assertNotIn(removed, spec)

    def test_spec_collects_cjk_width_dependency(self):
        """wcwidth is imported directly by tui_utils, so the freeze needs it."""
        spec = pathlib.Path("music-fetch.spec").read_text(encoding="utf-8")
        self.assertIn("'wcwidth'", spec)


if __name__ == "__main__":
    unittest.main()
