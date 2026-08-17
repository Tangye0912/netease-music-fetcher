import tempfile
import unittest
from pathlib import Path
from unittest import mock

import music_fetch.tui
from music_fetch.api import QR_STATUS_REJECTED, MusicFetchError, QrLoginPollResult
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

    @mock.patch("music_fetch.tui.U.menu")
    @mock.patch("music_fetch.tui.U.print_header")
    def test_login_menu_offers_only_qr_and_return(self, header_mock, menu_mock):
        menu_mock.return_value = 2
        self.app._screen_login()
        header_mock.assert_called_once_with("登录")
        menu_mock.assert_called_once_with("登录方式", ["扫码登录（终端显示二维码）", "返回"])
        self.assertFalse(hasattr(self.app, "_login_with_browser"))
        self.assertFalse(hasattr(self.app, "_login_with_cookie"))

    @mock.patch("music_fetch.tui.U.menu")
    @mock.patch("music_fetch.tui.U.print_header")
    def test_login_menu_routes_to_qr(self, header_mock, menu_mock):
        menu_mock.return_value = 1
        with mock.patch.object(self.app, "_login_with_qr") as qr_mock:
            self.app._screen_login()
        qr_mock.assert_called_once_with()

    @mock.patch("music_fetch.tui.poll_qr_login_status")
    @mock.patch("music_fetch.tui.U.render_qr_ascii", return_value="<QR>")
    @mock.patch("music_fetch.tui.build_qr_login_url", return_value="https://example.invalid/qr")
    @mock.patch("music_fetch.tui.fetch_qr_unikey", return_value="unikey-1")
    def test_qr_rejection_does_not_ask_for_browser_cookie(
        self, unikey_mock, url_mock, qr_mock, poll_mock
    ):
        poll_mock.return_value = QrLoginPollResult(status=QR_STATUS_REJECTED, message="risk")
        error_messages: list[str] = []
        info_messages: list[str] = []
        with mock.patch("music_fetch.tui.U.print_error", side_effect=error_messages.append), \
             mock.patch("music_fetch.tui.U.print_info", side_effect=info_messages.append):
            self.app._login_with_qr()
        self.assertIn("风控", error_messages[0])
        self.assertFalse(any("手动粘贴 Cookie" in text for text in info_messages))
        self.assertFalse(any("开发者工具" in text for text in info_messages))
        self.assertTrue(any("不会读取或要求你从浏览器复制 Cookie" in text for text in info_messages))

    @mock.patch("music_fetch.tui.fetch_account_profile")
    def test_accept_cookie_saves_session(self, profile_mock):
        from music_fetch.api import AccountProfile
        profile_mock.return_value = AccountProfile(
            user_id=1, nickname="测试用户", avatar_url="", vip_type=0, is_vip=False,
        )
        self.app._accept_cookie("MUSIC_U=abc; __csrf=def")
        self.assertIn("MUSIC_U=abc", self.app.session.cookie)
        self.assertEqual(self.app._nickname, "测试用户")
        self.assertIn("MUSIC_U=abc", self.session_store.load().cookie)

    @mock.patch("music_fetch.tui.fetch_account_profile")
    def test_accept_cookie_rejects_missing_music_u(self, profile_mock):
        self.app._accept_cookie("__csrf=only")
        profile_mock.assert_not_called()
        self.assertEqual(self.app.session.cookie, "")

    @mock.patch("music_fetch.tui.fetch_account_profile", side_effect=MusicFetchError("AUTH_EXPIRED", "expired"))
    def test_accept_cookie_rejects_invalid_cookie(self, _profile_mock):
        self.app._accept_cookie("MUSIC_U=bad")
        self.assertEqual(self.app.session.cookie, "")

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
