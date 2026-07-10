"""Tests for music_fetch/gui_styles.py — Material Design theme integration."""

import unittest

from music_fetch.gui_styles import (
    build_app_stylesheet,
    clamp_ui_font_size,
    MATERIAL_THEME_LIGHT,
    MATERIAL_THEME_DARK,
    set_button_role,
    set_label_state,
    set_back_button,
    set_secondary_button,
)


class MaterialThemeTests(unittest.TestCase):
    def test_theme_constants_defined(self):
        self.assertIsInstance(MATERIAL_THEME_LIGHT, str)
        self.assertIsInstance(MATERIAL_THEME_DARK, str)
        self.assertTrue(MATERIAL_THEME_LIGHT.endswith(".xml"))
        self.assertTrue(MATERIAL_THEME_DARK.endswith(".xml"))

    def test_light_and_dark_are_different(self):
        self.assertNotEqual(MATERIAL_THEME_LIGHT, MATERIAL_THEME_DARK)

    def test_custom_stylesheet_has_app_surfaces_and_semantic_states(self):
        stylesheet = build_app_stylesheet("light")
        self.assertIn("QFrame#heroPanel", stylesheet)
        self.assertIn('QPushButton[role="primary"]', stylesheet)
        self.assertIn('QLabel#statusLabel[state="error"]', stylesheet)

    def test_custom_dark_theme_uses_distinct_palette(self):
        self.assertNotEqual(build_app_stylesheet("light"), build_app_stylesheet("dark"))


class ClampFontSizeTests(unittest.TestCase):
    def test_normal_value(self):
        self.assertEqual(clamp_ui_font_size(14), 14)

    def test_below_min(self):
        self.assertEqual(clamp_ui_font_size(8), 12)

    def test_above_max(self):
        self.assertEqual(clamp_ui_font_size(30), 20)

    def test_invalid_type(self):
        self.assertEqual(clamp_ui_font_size("abc"), 14)  # default


class BackwardCompatTests(unittest.TestCase):
    """Verify that button/label helper functions are still importable."""

    def test_functions_exist(self):
        # These functions are still part of the public API, just no longer
        # building QSS from scratch — they set Qt properties for qt-material.
        self.assertTrue(callable(set_button_role))
        self.assertTrue(callable(set_label_state))
        self.assertTrue(callable(set_back_button))
        self.assertTrue(callable(set_secondary_button))


if __name__ == "__main__":
    unittest.main()
