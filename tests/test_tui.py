import tempfile
import unittest
from pathlib import Path
from unittest import mock

import music_fetch.tui
from music_fetch.app import main as app_main
from music_fetch.app_stores import DownloadHistoryStore, SessionStore
from music_fetch.tui import TuiApp
from music_fetch.tui_utils import render_qr_ascii


class AppRoutingTests(unittest.TestCase):
    @mock.patch("music_fetch.tui.main")
    def test_no_args_opens_tui(self, tui_main_mock):
        tui_main_mock.return_value = 0
        result = app_main([])
        self.assertEqual(result, 0)
        tui_main_mock.assert_called_once_with()

    @mock.patch("music_fetch.cli.main")
    def test_args_route_to_cli(self, cli_main_mock):
        cli_main_mock.return_value = 0
        result = app_main(["--url", "42"])
        self.assertEqual(result, 0)
        cli_main_mock.assert_called_once_with(["--url", "42"])


class RenderQrAsciiTests(unittest.TestCase):
    def test_renders_block_art_with_border(self):
        art = render_qr_ascii("https://music.163.com/login?codekey=abc123")
        lines = art.splitlines()
        self.assertGreater(len(lines), 20)
        self.assertIn("██", art)
        # Every line must be the same width (block chars are 2 columns each).
        widths = {len(line) for line in lines}
        self.assertEqual(len(widths), 1)

    def test_different_inputs_render_different_art(self):
        self.assertNotEqual(render_qr_ascii("aaaa"), render_qr_ascii("bbbb"))


class TuiAppHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.session_store = SessionStore(base / "session.json")
        self.history_store = DownloadHistoryStore(base / "history.json")
        self.app = TuiApp(session_store=self.session_store, history_store=self.history_store)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_login_label_states(self):
        self.assertEqual(self.app._login_label(), "未登录")
        self.app.session.cookie = "MUSIC_U=abc"
        self.assertEqual(self.app._login_label(), "已登录")
        self.app._nickname = "测试用户"
        self.assertEqual(self.app._login_label(), "测试用户")

    def test_filter_label_mapping(self):
        self.assertEqual(TuiApp._filter_label("all"), "全部")
        self.assertEqual(TuiApp._filter_label("failed"), "失败")
        self.assertEqual(TuiApp._filter_label("weird"), "weird")

    def test_add_record_persists_history(self):
        self.app._add_record(
            song_id="42",
            song_name="测试歌曲",
            output_path="/tmp/song.mp3",
            size_bytes=123,
            status="success",
        )
        records = self.history_store.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].song_id, "42")
        self.assertEqual(records[0].song_name, "测试歌曲")

    def test_invalid_stored_proxy_falls_back_to_direct(self):
        from music_fetch.network import get_proxy_config

        self.app.session.proxy_type = "socks5"
        self.app.session.proxy_host = "127.0.0.1"
        self.app.session.proxy_port = 0  # invalid port
        self.app._apply_proxy()
        self.assertFalse(get_proxy_config().enabled)


class TuiMainTests(unittest.TestCase):
    @mock.patch("music_fetch.tui.setup_logging")
    @mock.patch("music_fetch.tui.TuiApp")
    def test_main_runs_and_returns_exit_code(self, app_mock, _log_mock):
        instance = app_mock.return_value
        instance.run.return_value = 0
        self.assertEqual(music_fetch.tui.main(), 0)
        instance.run.assert_called_once()

    @mock.patch("music_fetch.tui.setup_logging")
    @mock.patch("music_fetch.tui.TuiApp")
    def test_main_handles_keyboard_interrupt(self, app_mock, _log_mock):
        instance = app_mock.return_value
        instance.run.side_effect = KeyboardInterrupt()
        self.assertEqual(music_fetch.tui.main(), 0)


if __name__ == "__main__":
    unittest.main()
