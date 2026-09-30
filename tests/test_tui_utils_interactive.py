"""Coverage for the interactive helpers and narrow-window table rendering."""

import contextlib
import io
import unittest
from unittest import mock

import music_fetch.tui_utils as U
from music_fetch.tui_utils import format_table


class ClearScreenTests(unittest.TestCase):
    def test_clear_screen_asks_for_the_ansi_sequence(self):
        # Prompt_toolkit's ANSI() consumes the escapes into styling, so assert
        # what clear_screen hands to the printer instead of the rendered output
        # (which also depends on the platform and on stdout being an fd).
        with mock.patch("music_fetch.tui_utils._safe_print_formatted") as safe_mock:
            U.clear_screen()
        self.assertIn("\x1b[2J", safe_mock.call_args.args[0])

    def test_safe_print_falls_back_to_plain_text_without_a_console(self):
        # CI runners and piped stdout take this branch: ANSI must be stripped and
        # characters the console cannot encode must not raise.
        with mock.patch(
            "music_fetch.tui_utils.print_formatted_text", side_effect=RuntimeError("no console")
        ), mock.patch("builtins.print") as print_mock:
            U.print_info("\x1b[32m✓ 完成\x1b[0m")
        printed = str(print_mock.call_args)
        self.assertIn("完成", printed)
        self.assertNotIn("\x1b", printed)


class AskHelperTests(unittest.TestCase):
    def test_ask_required_retries_until_something_is_typed(self):
        # Whitespace-only input is rejected: "required" must mean non-blank.
        with mock.patch("music_fetch.tui_utils.ask", side_effect=["", "   ", " value "]) as ask_mock, mock.patch(
            "music_fetch.tui_utils.print_warning"
        ) as warning_mock:
            self.assertEqual(U.ask_required("prompt"), " value ")
        self.assertEqual(ask_mock.call_count, 3)
        self.assertEqual(warning_mock.call_count, 2)

    def test_ask_int_rejects_non_numbers_and_out_of_range(self):
        with mock.patch("music_fetch.tui_utils.ask", side_effect=["abc", "99", "5"]) as ask_mock, mock.patch(
            "music_fetch.tui_utils.print_warning"
        ) as warning_mock:
            self.assertEqual(U.ask_int("prompt", default=1, minimum=1, maximum=10), 5)
        self.assertEqual(ask_mock.call_count, 3)
        self.assertEqual(warning_mock.call_count, 2)

    def test_confirm_maps_every_answer(self):
        cases = [("", True, True), ("", False, False), ("y", False, True), ("YES", False, True),
                 ("n", True, False), ("no", True, False)]
        for raw, default, expected in cases:
            with self.subTest(raw=raw, default=default), mock.patch(
                "music_fetch.tui_utils.ask", return_value=raw
            ):
                self.assertEqual(U.confirm("question", default=default), expected)

    def test_confirm_retries_on_an_unrecognised_answer(self):
        with mock.patch("music_fetch.tui_utils.ask", side_effect=["maybe", "y"]) as ask_mock, mock.patch(
            "music_fetch.tui_utils.print_warning"
        ) as warning_mock:
            self.assertTrue(U.confirm("question"))
        self.assertEqual(ask_mock.call_count, 2)
        warning_mock.assert_called_once()

    def test_multiselect_without_options_warns(self):
        with mock.patch("music_fetch.tui_utils.print_warning") as warning_mock:
            self.assertEqual(U.multiselect("title", []), [])
        warning_mock.assert_called_once()


class SpinnerTests(unittest.TestCase):
    def test_spinner_animates_and_cleans_up_its_line(self):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            with U.spinner("working", delay=0.01):
                pass
        output = buffer.getvalue()
        self.assertIn("working", output)
        self.assertTrue(output.endswith("\r"))  # the spinner line is cleared


class FormatTableTests(unittest.TestCase):
    def test_no_headers_renders_nothing(self):
        self.assertEqual(format_table([], [["x"]]), "")

    def test_narrow_windows_shrink_and_truncate_cells(self):
        headers = ["#", "歌曲", "状态"]
        rows = [["1", "一首名字特别长的歌曲名称", "ready"]]

        rendered = format_table(headers, rows, max_width=24)

        self.assertIn("…", rendered)                       # a cell was truncated
        self.assertIn("部分内容已截断", rendered)          # and the reader is told
        self.assertIn("歌曲", rendered)                    # headers stay intact

    def test_wide_windows_keep_values_intact(self):
        rendered = format_table(["#", "歌"], [["1", "短"]], max_width=80)
        self.assertNotIn("…", rendered)
        self.assertNotIn("部分内容已截断", rendered)
