import unittest

from music_fetch.csv_utils import safe_csv_text


class SafeCsvTextTests(unittest.TestCase):
    def test_plain_text_is_unchanged(self):
        self.assertEqual(safe_csv_text("hello world"), "hello world")
        self.assertEqual(safe_csv_text("夜曲 - 周杰伦"), "夜曲 - 周杰伦")

    def test_leading_formula_characters_are_neutralized(self):
        self.assertEqual(safe_csv_text("=1+1"), "'=1+1")
        self.assertEqual(safe_csv_text("+SUM(A1:A2)"), "'+SUM(A1:A2)")
        self.assertEqual(safe_csv_text("-cmd"), "'-cmd")
        self.assertEqual(safe_csv_text("@payload"), "'@payload")

    def test_leading_whitespace_is_ignored_for_detection(self):
        # The quote must be prepended to the ORIGINAL text (leading whitespace included).
        self.assertEqual(safe_csv_text("  =1+1"), "'  =1+1")
        self.assertEqual(safe_csv_text("\t@x"), "'\t@x")

    def test_empty_and_none_become_empty_text(self):
        self.assertEqual(safe_csv_text(""), "")
        self.assertEqual(safe_csv_text(None), "")

    def test_non_string_values_are_stringified(self):
        self.assertEqual(safe_csv_text(123), "123")
        self.assertEqual(safe_csv_text(True), "True")


if __name__ == "__main__":
    unittest.main()
