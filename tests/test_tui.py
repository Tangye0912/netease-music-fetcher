import tempfile
import unittest
from pathlib import Path
from unittest import mock

import music_fetch.tui
from music_fetch.api import MusicFetchError
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
    def test_renders_compact_half_block_art(self):
        art = render_qr_ascii("https://music.163.com/login?codekey=abc123")
        lines = art.splitlines()
        # Half-block rendering: two module rows per line — must fit a
        # normal 80-column terminal without resizing (bili-hardcore style).
        self.assertLessEqual(len(lines), 20)
        self.assertGreater(len(lines), 5)
        self.assertLessEqual(len(lines[0]), 40)
        self.assertTrue(any(char in art for char in ("▀", "▄", "█")))
        # Every line must be the same width.
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

    @mock.patch("music_fetch.tui.U.print_header")
    def test_login_menu_routes_to_browser(self, header_mock):
        with mock.patch.object(self.app, "_login_with_browser") as browser_mock:
            self.app._screen_login()
        header_mock.assert_called_once_with("登录")
        browser_mock.assert_called_once_with()

    @mock.patch("music_fetch.tui.U.print_info")
    @mock.patch("music_fetch.tui.U.print_header")
    @mock.patch("music_fetch.tui.U.clear_screen")
    def test_run_locks_menu_when_not_logged_in(self, clear_mock, header_mock, info_mock):
        with mock.patch.object(self.app, "_validate_session_login", return_value=False), mock.patch(
            "music_fetch.tui.U.menu", return_value=2
        ) as menu_mock:
            result = self.app.run()
        self.assertEqual(result, 0)
        # Not logged in -> the menu only offers 登录 / 退出.
        self.assertEqual(menu_mock.call_args.args[1], [music_fetch.tui.MENU_LOGIN, music_fetch.tui.MENU_QUIT])

    @mock.patch("music_fetch.tui.U.print_success")
    @mock.patch("music_fetch.tui.U.print_info")
    @mock.patch("music_fetch.tui.fetch_account_profile")
    def test_accept_cookie_saves_session(self, profile_mock, _print_info_mock, _print_success_mock):
        from music_fetch.api import AccountProfile
        profile_mock.return_value = AccountProfile(
            user_id=1, nickname="测试用户", avatar_url="", vip_type=0, is_vip=False,
        )
        self.app._accept_cookie("MUSIC_U=abc; __csrf=def")
        self.assertIn("MUSIC_U=abc", self.app.session.cookie)
        self.assertEqual(self.app._nickname, "测试用户")
        self.assertIn("MUSIC_U=abc", self.session_store.load().cookie)

    @mock.patch("music_fetch.tui.U.print_error")
    @mock.patch("music_fetch.tui.fetch_account_profile")
    def test_accept_cookie_rejects_missing_music_u(self, profile_mock, _print_error_mock):
        self.app._accept_cookie("__csrf=only")
        profile_mock.assert_not_called()
        self.assertEqual(self.app.session.cookie, "")

    @mock.patch("music_fetch.tui.U.print_info")
    @mock.patch("music_fetch.tui.U.print_error")
    @mock.patch("music_fetch.tui.fetch_account_profile", side_effect=MusicFetchError("AUTH_EXPIRED", "expired"))
    def test_accept_cookie_rejects_invalid_cookie(self, _profile_mock, _print_error_mock, _print_info_mock):
        self.app._accept_cookie("MUSIC_U=bad")
        self.assertEqual(self.app.session.cookie, "")

    def test_ask_with_cancel_zero_returns_none(self):
        with mock.patch("music_fetch.tui.U.ask", return_value="0"):
            self.assertIsNone(self.app._ask_with_cancel("提示", default="默认值"))

    def test_ask_with_cancel_empty_uses_default(self):
        with mock.patch("music_fetch.tui.U.ask", return_value=""):
            self.assertEqual(self.app._ask_with_cancel("提示", default="默认值"), "默认值")

    def test_ask_with_cancel_value_passes_through(self):
        with mock.patch("music_fetch.tui.U.ask", return_value="我的输入"):
            self.assertEqual(self.app._ask_with_cancel("提示", default="默认值"), "我的输入")

    @mock.patch("music_fetch.tui.U.print_warning")
    @mock.patch("music_fetch.tui.is_ffmpeg_available", return_value=False)
    @mock.patch("music_fetch.tui.U.menu", return_value=6)
    def test_pick_format_cancel_returns_none(self, _menu_mock, _ffmpeg_mock, _warning_mock):
        # Deterministic regardless of whether ffmpeg is installed / console exists.
        self.assertIsNone(self.app._pick_format())

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

    @mock.patch("music_fetch.tui.U.print_info")
    @mock.patch("music_fetch.tui.setup_logging")
    @mock.patch("music_fetch.tui.TuiApp")
    def test_main_handles_keyboard_interrupt(self, app_mock, _log_mock, _print_info_mock):
        instance = app_mock.return_value
        instance.run.side_effect = KeyboardInterrupt()
        self.assertEqual(music_fetch.tui.main(), 0)


if __name__ == "__main__":
    unittest.main()
