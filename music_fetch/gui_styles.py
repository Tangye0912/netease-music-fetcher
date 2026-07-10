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
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton
except ImportError as err:
    raise SystemExit(
        "Missing dependency: PySide6. Install it with `python3 -m pip install PySide6` before running main.py."
    ) from err

# Material Design theme names — light and dark variants.
# Use red accent to match NetEase Cloud Music branding.
MATERIAL_THEME_LIGHT = "light_red_500.xml"
MATERIAL_THEME_DARK = "dark_red.xml"

__all__ = [
    "apply_app_style",
    "build_app_stylesheet",
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


def build_app_stylesheet(theme: str = "light") -> str:
    """Build the application-specific layer placed on top of qt-material."""
    dark = theme == "dark"
    colors = {
        "background": "#101114" if dark else "#f6f7f9",
        "surface": "#1a1c21" if dark else "#ffffff",
        "surface_alt": "#22252b" if dark else "#f9fafb",
        "border": "#30343b" if dark else "#e5e7eb",
        "text": "#f5f6f7" if dark else "#17181c",
        "muted": "#a6abb4" if dark else "#69707d",
        "accent": "#ff5c61" if dark else "#e8393f",
        "accent_hover": "#ff7377" if dark else "#d92f35",
        "accent_soft": "#3a2023" if dark else "#fff0f1",
        "success": "#65d69e" if dark else "#168a55",
        "success_soft": "#183328" if dark else "#eaf8f1",
        "warning": "#f4bd63" if dark else "#a76509",
        "warning_soft": "#382d1c" if dark else "#fff6e6",
        "error": "#ff8589" if dark else "#c52d35",
        "error_soft": "#3b2023" if dark else "#fff0f1",
        "selection": "#5c282c" if dark else "#fde5e7",
    }
    return f"""
QMainWindow, QDialog, QWidget#appRoot {{
    background-color: {colors['background']};
    color: {colors['text']};
}}

QFrame#heroPanel, QFrame#toolbarPanel, QFrame#inputPanel {{
    background-color: {colors['surface']};
    border: 1px solid {colors['border']};
    border-radius: 14px;
}}

QFrame#accountPanel {{
    background-color: {colors['surface_alt']};
    border: 1px solid {colors['border']};
    border-radius: 12px;
}}

QLabel#brandEyebrow {{
    color: {colors['accent']};
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1px;
}}

QLabel#brandTitle {{
    color: {colors['text']};
    font-size: 25px;
    font-weight: 700;
}}

QLabel#brandSubtitle, QLabel#sectionSubtitle, QLabel#accountMeta,
QLabel#toolbarTitle, QLabel#footerLabel {{
    color: {colors['muted']};
}}

QLabel#sectionTitle {{
    color: {colors['text']};
    font-size: 17px;
    font-weight: 700;
}}

QLabel#accountName {{
    color: {colors['text']};
    font-weight: 650;
}}

QToolButton#avatarButton {{
    background-color: {colors['accent_soft']};
    color: {colors['accent']};
    border: 1px solid {colors['border']};
    border-radius: 24px;
    font-weight: 700;
}}

QToolButton#avatarButton:hover {{
    border-color: {colors['accent']};
}}

QPushButton {{
    min-height: 34px;
    padding: 0 14px;
    border: 1px solid {colors['border']};
    border-radius: 8px;
    background-color: {colors['surface_alt']};
    color: {colors['text']};
    font-weight: 600;
}}

QPushButton:hover {{
    border-color: {colors['accent']};
    background-color: {colors['accent_soft']};
    color: {colors['accent']};
}}

QPushButton:pressed {{
    background-color: {colors['selection']};
}}

QPushButton:disabled {{
    color: {colors['muted']};
    border-color: {colors['border']};
    background-color: {colors['surface_alt']};
}}

QPushButton[role="primary"] {{
    min-height: 42px;
    border: none;
    background-color: {colors['accent']};
    color: #ffffff;
    padding: 0 22px;
}}

QPushButton[role="primary"]:hover {{
    background-color: {colors['accent_hover']};
    color: #ffffff;
}}

QPushButton[role="primary"]:disabled {{
    background-color: {colors['surface_alt']};
    color: {colors['muted']};
    border: 1px solid {colors['border']};
}}

QPushButton[navRole="back"] {{
    background-color: transparent;
    color: {colors['muted']};
}}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
    background-color: {colors['surface_alt']};
    color: {colors['text']};
    border: 1px solid {colors['border']};
    border-radius: 9px;
    padding: 8px 10px;
    selection-background-color: {colors['selection']};
}}

QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QSpinBox:focus {{
    border: 1px solid {colors['accent']};
}}

QPlainTextEdit#urlInput {{
    font-size: 14px;
    padding: 12px 14px;
}}

QLabel[state="muted"] {{ color: {colors['muted']}; }}
QLabel[state="success"] {{ color: {colors['success']}; }}
QLabel[state="warning"] {{ color: {colors['warning']}; }}
QLabel[state="error"] {{ color: {colors['error']}; }}

QLabel#statusLabel[state="success"] {{
    background-color: {colors['success_soft']};
    border: 1px solid {colors['success']};
    border-radius: 8px;
    padding: 9px 12px;
}}
QLabel#statusLabel[state="warning"] {{
    background-color: {colors['warning_soft']};
    border: 1px solid {colors['warning']};
    border-radius: 8px;
    padding: 9px 12px;
}}
QLabel#statusLabel[state="error"] {{
    background-color: {colors['error_soft']};
    border: 1px solid {colors['error']};
    border-radius: 8px;
    padding: 9px 12px;
}}

QTableWidget, QTableView {{
    background-color: {colors['surface']};
    alternate-background-color: {colors['surface_alt']};
    color: {colors['text']};
    border: 1px solid {colors['border']};
    border-radius: 10px;
    gridline-color: {colors['border']};
    selection-background-color: {colors['selection']};
    selection-color: {colors['text']};
}}

QHeaderView::section {{
    background-color: {colors['surface_alt']};
    color: {colors['muted']};
    border: none;
    border-bottom: 1px solid {colors['border']};
    padding: 9px 8px;
    font-weight: 650;
}}

QProgressBar {{
    background-color: {colors['surface_alt']};
    border: 1px solid {colors['border']};
    border-radius: 7px;
    min-height: 14px;
    text-align: center;
}}
QProgressBar::chunk {{
    background-color: {colors['accent']};
    border-radius: 6px;
}}

QGroupBox {{
    border: 1px solid {colors['border']};
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: 650;
}}
QGroupBox::title {{
    color: {colors['muted']};
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 5px;
}}

QToolTip {{
    background-color: {colors['text']};
    color: {colors['surface']};
    border: none;
    padding: 6px;
}}
"""


def apply_app_style(app: QApplication, font_size: int, theme: str = "light") -> int:
    """Apply Material Design theme to the app. Returns normalized font size."""
    normalized = clamp_ui_font_size(font_size)
    material_theme = MATERIAL_THEME_DARK if theme == "dark" else MATERIAL_THEME_LIGHT
    _apply_material_stylesheet(app, material_theme, normalized)
    palette = app.palette()
    link_color = QColor("#ff7377" if theme == "dark" else "#d92f35")
    palette.setColor(QPalette.Link, link_color)
    palette.setColor(QPalette.LinkVisited, link_color)
    app.setPalette(palette)
    app.setStyleSheet(app.styleSheet() + "\n" + build_app_stylesheet(theme))
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
    button.setProperty("role", "secondary")
    button.setAutoDefault(False)
    button.setDefault(False)
    button.style().unpolish(button)
    button.style().polish(button)


def set_label_state(label: QLabel, state: str) -> None:
    """Set a semantic state on a label (success, warning, error, muted)."""
    label.setProperty("state", state)
    label.style().unpolish(label)
    label.style().polish(label)
