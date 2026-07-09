#!/usr/bin/env python3
"""
GUI style helpers: Material Design via qt-material, plus button role/label state
helpers for semantic coloring.

Extracted from music_fetch.dialogs.py to reduce module size and centralize visual
appearance logic.
"""

from __future__ import annotations

from typing import Optional

from music_fetch.app_settings import (
    DEFAULT_UI_FONT_SIZE,
    MAX_UI_FONT_SIZE,
    MIN_UI_FONT_SIZE,
    clamp,
)

try:
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
except ImportError as err:
    raise SystemExit(
        "Missing dependency: PySide6. Install it with `python3 -m pip install PySide6` before running main.py."
    ) from err

# Material Design theme names — light and dark variants.
MATERIAL_THEME_LIGHT = "light_blue.xml"
MATERIAL_THEME_DARK = "dark_cyan.xml"

__all__ = [
    "apply_app_style",
    "clamp_ui_font_size",
    "set_back_button",
    "set_button_role",
    "set_label_state",
    "set_secondary_button",
    "MATERIAL_THEME_LIGHT",
    "MATERIAL_THEME_DARK",
]


def clamp_ui_font_size(value: object) -> int:
    return clamp(value, DEFAULT_UI_FONT_SIZE, MIN_UI_FONT_SIZE, MAX_UI_FONT_SIZE)


def _apply_material_stylesheet(app: QApplication, theme: str, font_size: int) -> None:
    """Apply a qt-material theme with custom font size."""
    from qt_material import apply_stylesheet

    extra: dict[str, object] = {
        "font_size": font_size,
        "font_family": '"Microsoft YaHei", "PingFang SC", "Helvetica Neue", sans-serif',
        "density_scale": 0,
    }
    apply_stylesheet(app, theme=theme, extra=extra)


def apply_app_style(app: QApplication, font_size: int, theme: str = "light") -> int:
    """Apply Material Design theme to the app. Returns normalized font size."""
    normalized = clamp_ui_font_size(font_size)
    material_theme = MATERIAL_THEME_DARK if theme == "dark" else MATERIAL_THEME_LIGHT
    _apply_material_stylesheet(app, material_theme, normalized)
    return normalized


def set_button_role(button: QPushButton, role: Optional[str]) -> None:
    """Set a semantic role on a button (primary, secondary, etc.)."""
    button.setProperty("role", role or "")
    button.style().unpolish(button)
    button.style().polish(button)
    if role == "primary":
        button.setDefault(True)
        button.setAutoDefault(True)


def set_back_button(button: QPushButton) -> None:
    """Style a button as a back/cancel navigation button."""
    button.setProperty("navRole", "back")
    button.setAutoDefault(False)
    button.setDefault(False)
    button.style().unpolish(button)
    button.style().polish(button)


def set_secondary_button(button: QPushButton) -> None:
    """Style a button as a secondary action."""
    button.setAutoDefault(False)
    button.setDefault(False)
    button.style().unpolish(button)
    button.style().polish(button)


def set_label_state(label: QLabel, state: str) -> None:
    """Set a semantic state on a label (success, warning, error, muted)."""
    label.setProperty("state", state)
    label.style().unpolish(label)
    label.style().polish(label)