import re
import unittest
from unittest import mock

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
        self.assertEqual(len(captured), 4)  # header + separator + 2 rows
        # Data rows must line up: identical display width.  (The header's last
        # cell loses its trailing pad via rstrip, which is invisible, so only
        # the data rows are compared here.)
        widths = {tui_utils._display_width(_plain(line)) for line in captured[2:]}
        self.assertEqual(len(widths), 1)


if __name__ == "__main__":
    unittest.main()
