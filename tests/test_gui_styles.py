"""Tests for music_fetch/gui_styles.py — build_app_stylesheet, build_dark_stylesheet."""

import unittest

from music_fetch.gui_styles import (
    build_app_stylesheet,
    build_dark_stylesheet,
)


class BuildAppStylesheetTests(unittest.TestCase):
    def test_contains_key_selectors(self):
        sheet = build_app_stylesheet(14)
        self.assertIn("QWidget", sheet)
        self.assertIn("QPushButton", sheet)
        self.assertIn("QLineEdit", sheet)
        self.assertIn("QComboBox", sheet)
        self.assertIn("QProgressBar", sheet)

    def test_font_size_in_output(self):
        sheet = build_app_stylesheet(16)
        self.assertIn("16px", sheet)

    def test_primary_button_role(self):
        sheet = build_app_stylesheet(14)
        self.assertIn('QPushButton[role="primary"]', sheet)

    def test_label_states(self):
        sheet = build_app_stylesheet(14)
        self.assertIn('QLabel[state="success"]', sheet)
        self.assertIn('QLabel[state="error"]', sheet)
        self.assertIn('QLabel[state="muted"]', sheet)


class BuildDarkStylesheetTests(unittest.TestCase):
    def test_contains_key_selectors(self):
        sheet = build_dark_stylesheet(14)
        self.assertIn("QWidget", sheet)
        self.assertIn("QPushButton", sheet)
        self.assertIn("QTableWidget", sheet)
        self.assertIn("QScrollBar", sheet)
        self.assertIn("QToolTip", sheet)
        self.assertIn("QStatusBar", sheet)
        self.assertIn("QMenu", sheet)
        self.assertIn("QCheckBox", sheet)
        self.assertIn("QGroupBox", sheet)

    def test_uses_dark_colors(self):
        sheet = build_dark_stylesheet(14)
        self.assertIn("#1e1e2e", sheet)
        self.assertIn("#cdd6f4", sheet)
        self.assertIn("#313244", sheet)

    def test_primary_button_dark(self):
        sheet = build_dark_stylesheet(14)
        self.assertIn('QPushButton[role="primary"]', sheet)
        self.assertIn("#89b4fa", sheet)


if __name__ == "__main__":
    unittest.main()