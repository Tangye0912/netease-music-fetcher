import re
import unittest
from unittest import mock

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.keys import Keys

from music_fetch import tui_utils

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(line: str) -> str:
    return _ANSI_RE.sub("", line)


class DisplayWidthTests(unittest.TestCase):
    def test_cjk_wide_chars_count_as_two(self) -> None:
        self.assertEqual(tui_utils._display_width("张杰"), 4)
        self.assertEqual(tui_utils._display_width("ab"), 2)
        self.assertEqual(tui_utils._display_width("明天过后 03:57"), 14)

    def test_truncate_respects_display_width(self) -> None:
        # "崩坏星穹铁道" is 6 CJK chars (display width 12); capped at 10, the
        # result keeps only the first 5 chars (width 10).
        self.assertEqual(tui_utils._truncate_to_width("崩坏星穹铁道-不眠之夜", 10), "崩坏星穹铁")
        self.assertEqual(tui_utils._truncate_to_width("abcdef", 3), "abc")


class PrintTableTests(unittest.TestCase):
    def test_print_table_aligns_cjk_columns(self) -> None:
        captured: list[str] = []
        with mock.patch("music_fetch.tui_utils.print_info", side_effect=captured.append):
            tui_utils.print_table(
                ["#", "歌名", "时长"],
                [["1", "明天过后", "03:57"], ["2", "天下", "03:41"]],
                max_width=80,
            )
        self.assertEqual(len(captured), 6)  # top + header + separator + 2 rows + bottom
        self.assertTrue(_plain(captured[0]).startswith("┌"))
        self.assertTrue(_plain(captured[-1]).startswith("└"))
        # Every bordered row must occupy the same display width.
        widths = {tui_utils._display_width(_plain(line)) for line in captured}
        self.assertEqual(len(widths), 1)


class ThemeRenderingTests(unittest.TestCase):
    def test_header_centers_cjk_title_to_terminal_width(self) -> None:
        captured: list[str] = []
        with mock.patch("music_fetch.tui_utils.print_info", side_effect=captured.append), mock.patch(
            "music_fetch.tui_utils.shutil.get_terminal_size", return_value=mock.Mock(columns=40)
        ):
            tui_utils.print_header("音乐下载")
        self.assertEqual(captured[0], "")
        line = _plain(captured[1])
        self.assertEqual(tui_utils._display_width(line), 40)
        self.assertIn(" 音乐下载 ", line)
        self.assertTrue(line.startswith("─"))
        self.assertTrue(line.endswith("─"))

    def test_menu_renders_bordered_numbered_panel(self) -> None:
        captured: list[str] = []
        with mock.patch("music_fetch.tui_utils.print_info", side_effect=captured.append), mock.patch(
            "music_fetch.tui_utils.ask", return_value="2"
        ), mock.patch(
            "music_fetch.tui_utils.shutil.get_terminal_size", return_value=mock.Mock(columns=40)
        ):
            choice = tui_utils.menu("主菜单", ["单曲下载", "退出"])
        self.assertEqual(choice, 2)
        plain = [_plain(line) for line in captured]
        self.assertIn(" 主菜单 ", plain[1])
        self.assertTrue(plain[1].startswith("┌"))
        self.assertIn("01  单曲下载", plain[2])
        self.assertIn("02  退出", plain[3])
        self.assertTrue(plain[4].startswith("└"))
        self.assertTrue(all(tui_utils._display_width(line) == 40 for line in plain[1:5]))

    def test_status_band_is_full_width_and_contains_labels(self) -> None:
        captured: list[str] = []
        with mock.patch("music_fetch.tui_utils._safe_print_formatted", side_effect=captured.append), mock.patch(
            "music_fetch.tui_utils.shutil.get_terminal_size", return_value=mock.Mock(columns=50)
        ):
            tui_utils.print_status([("登录", "测试用户"), ("代理", "直连")])
        line = _plain(captured[0])
        self.assertEqual(tui_utils._display_width(line), 50)
        self.assertIn("登录: 测试用户", line)
        self.assertIn("代理: 直连", line)

    def test_status_messages_have_clear_symbols(self) -> None:
        captured: list[str] = []
        with mock.patch("music_fetch.tui_utils._safe_print_formatted", side_effect=captured.append):
            tui_utils.print_success("完成")
            tui_utils.print_warning("注意")
            tui_utils.print_error("失败")
        self.assertEqual([_plain(line) for line in captured], ["✓ 完成", "! 注意", "✕ 失败"])


class MultiselectKeyBindingTests(unittest.TestCase):
    def test_escape_exits_dialog_with_canceled_result(self) -> None:
        dialog: Application[list[str] | None] = mock.Mock(spec=Application)
        dialog.key_bindings = KeyBindings()
        tui_utils._bind_escape_to_cancel(dialog)

        bindings = dialog.key_bindings.get_bindings_for_keys((Keys.Escape,))
        self.assertEqual(len(bindings), 1)
        event = mock.Mock()
        bindings[0].handler(event)
        event.app.exit.assert_called_once_with(result=None)

    def test_multiselect_installs_escape_binding_before_run(self) -> None:
        dialog: Application[list[str] | None] = mock.Mock(spec=Application)
        dialog.key_bindings = KeyBindings()
        dialog.run.return_value = None
        with mock.patch("music_fetch.tui_utils.checkboxlist_dialog", return_value=dialog):
            self.assertEqual(tui_utils.multiselect("选择", [("歌曲", True)]), [])
        self.assertEqual(
            len(dialog.key_bindings.get_bindings_for_keys((Keys.Escape,))),
            1,
        )
        dialog.run.assert_called_once_with()


class MenuShortcutsTests(unittest.TestCase):
    def test_shortcut_key_returns_mapped_choice(self) -> None:
        with mock.patch.object(tui_utils, "print_info"), mock.patch.object(
            tui_utils, "ask", return_value="q"
        ):
            choice = tui_utils.menu("测试", ["登录", "退出"], shortcuts={"q": 2})
        self.assertEqual(choice, 2)

    def test_shortcut_hint_appears_in_footer(self) -> None:
        captured: list[str] = []
        with mock.patch.object(tui_utils, "print_info", side_effect=captured.append), mock.patch.object(
            tui_utils, "ask", return_value="1"
        ):
            tui_utils.menu("测试", ["登录 / 重新登录", "退出"], shortcuts={"q": 2})
        plain = [_plain(line) for line in captured]
        self.assertTrue(any("q 退出" in line for line in plain))

    def test_numeric_choice_still_works_with_shortcuts(self) -> None:
        with mock.patch.object(tui_utils, "print_info"), mock.patch.object(
            tui_utils, "ask", return_value="1"
        ):
            choice = tui_utils.menu("测试", ["登录", "退出"], shortcuts={"q": 2})
        self.assertEqual(choice, 1)


class PrintPanelTests(unittest.TestCase):
    def test_panel_renders_title_rows_and_border(self) -> None:
        captured: list[str] = []
        with mock.patch.object(tui_utils, "print_info", side_effect=captured.append):
            tui_utils.print_panel("歌曲信息", [("歌名", "天下"), ("音质", "较高")], max_width=40)
        plain = [_plain(line) for line in captured]
        self.assertIn("歌曲信息", plain[0])
        self.assertTrue(any("天下" in line for line in plain))
        self.assertEqual(plain[-1][:1], "└")


if __name__ == "__main__":
    unittest.main()
