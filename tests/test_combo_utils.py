import unittest

try:
    from PySide6.QtWidgets import QApplication
    _app = QApplication.instance() or QApplication([])
except ImportError:
    _app = None

from music_fetch.combo_utils import build_value_combo, build_options_combo, set_combo_value, combo_int_value


class ComboUtilsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if _app is None:
            raise unittest.SkipTest("PySide6 not available")

    def test_build_value_combo_range(self):
        combo = build_value_combo(1, 3, "s")
        self.assertEqual(combo.count(), 3)
        self.assertEqual(combo.itemText(0), "1 s")
        self.assertEqual(combo.itemData(0), 1)
        self.assertEqual(combo.itemText(2), "3 s")
        self.assertEqual(combo.itemData(2), 3)

    def test_build_options_combo(self):
        combo = build_options_combo((1, 3, 5), "s")
        self.assertEqual(combo.count(), 3)
        self.assertEqual(combo.itemData(0), 1)
        self.assertEqual(combo.itemData(1), 3)
        self.assertEqual(combo.itemData(2), 5)

    def test_set_combo_value_finds_exact_match(self):
        combo = build_value_combo(1, 5, "x")
        set_combo_value(combo, 3)
        self.assertEqual(combo.currentData(), 3)

    def test_set_combo_value_finds_nearest_match(self):
        combo = build_options_combo((1, 5, 10), "s")
        set_combo_value(combo, 7)
        self.assertEqual(combo.currentData(), 5)

    def test_set_combo_value_uses_first_when_equidistant(self):
        combo = build_options_combo((1, 3, 5), "s")
        set_combo_value(combo, 4)
        self.assertIn(combo.currentData(), (3, 5))

    def test_combo_int_value_returns_int(self):
        combo = build_options_combo((1, 3, 5), "s")
        combo.setCurrentIndex(1)
        self.assertEqual(combo_int_value(combo, 0), 3)

    def test_combo_int_value_fallback(self):
        combo = build_value_combo(1, 3, "s")
        combo.clear()
        self.assertEqual(combo_int_value(combo, 99), 99)


if __name__ == "__main__":
    unittest.main()
