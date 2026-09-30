"""Coverage for the interactive helpers and narrow-window table rendering."""

import io
import threading
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
        # CI runners and piped stdout take this branch: ANSI must be stripped.
        # Assert on the real argument — str(call_args) is a repr, where a raw ESC
        # becomes the four characters "\x1b", so an assertNotIn("\x1b", repr)
        # could never fail (it did not, before this fix).
        with mock.patch(
            "music_fetch.tui_utils.print_formatted_text", side_effect=RuntimeError("no console")
        ), mock.patch("builtins.print") as print_mock:
            U.print_info("\x1b[32mOK\x1b[0m")
        printed = print_mock.call_args.args[0]
        self.assertEqual(printed, "OK")
        self.assertNotIn("\x1b", printed)

    def test_safe_print_replaces_characters_the_console_cannot_encode(self):
        # The fallback re-encodes with the console codec and errors="replace", so
        # a CJK string on a Western code page degrades instead of raising.
        fake_stdout = mock.Mock(encoding="ascii")
        with mock.patch(
            "music_fetch.tui_utils.print_formatted_text", side_effect=RuntimeError("no console")
        ), mock.patch("music_fetch.tui_utils.sys.stdout", fake_stdout), mock.patch(
            "builtins.print"
        ) as print_mock:
            U.print_info("完成")
        printed = print_mock.call_args.args[0]
        self.assertTrue(printed)
        self.assertLessEqual(set(printed), {"?"})


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
    def test_spinner_draws_frames_and_clears_its_line(self):
        # Event-driven instead of time-based: the worker must draw a second frame.
        # (Asserting "animates" from the initial frame + final clear proved nothing
        # — a no-op worker passed too.)
        buffer = io.StringIO()
        second_frame = threading.Event()
        frames = 0

        def recording_write(text: str) -> int:
            nonlocal frames
            frames += 1
            if frames >= 2:
                second_frame.set()
            return buffer.write(text)

        fake_stdout = mock.Mock(write=recording_write, flush=lambda: None)
        with mock.patch("music_fetch.tui_utils.sys.stdout", fake_stdout):
            with U.spinner("working", delay=0.01):
                self.assertTrue(second_frame.wait(2), "the spinner worker never drew a frame")
        self.assertIn("working", buffer.getvalue())
        self.assertTrue(buffer.getvalue().endswith("\r"))  # the line is cleared


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
