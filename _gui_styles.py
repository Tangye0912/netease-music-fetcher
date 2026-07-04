#!/usr/bin/env python3
"""
GUI style helpers: QSS stylesheet builder, button role/label state helpers,
and the app-wide style application function.

Extracted from _dialogs.py to reduce module size and centralize visual
appearance logic.
"""

from __future__ import annotations

from typing import Optional

from app_settings import (
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



__all__ = ['apply_app_style', 'build_app_stylesheet', 'build_dark_stylesheet', 'clamp_ui_font_size', 'set_back_button', 'set_button_role', 'set_label_state', 'set_secondary_button']
def clamp_ui_font_size(value: object) -> int:
    return clamp(value, DEFAULT_UI_FONT_SIZE, MIN_UI_FONT_SIZE, MAX_UI_FONT_SIZE)


def build_app_stylesheet(font_size: int) -> str:
    field_height = max(34, int(font_size * 2.2))
    button_height = max(36, int(font_size * 2.35))
    radius = max(8, int(font_size * 0.55))
    return f"""
    QWidget {{
        font-size: {font_size}px;
    }}
    QPushButton {{
        min-height: {button_height}px;
        padding: 4px 14px;
        border-radius: {radius}px;
        border: 1px solid #d0d7de;
        background: #f6f8fa;
        color: #24292f;
    }}
    QPushButton:hover {{
        background: #eef3f8;
    }}
    QPushButton:focus {{
        border-color: #0969da;
        background: #eef3f8;
    }}
    QPushButton[role="primary"] {{
        background: #0969da;
        border-color: #0969da;
        color: #ffffff;
        font-weight: 600;
    }}
    QPushButton[role="primary"]:hover {{
        background: #0550ae;
        border-color: #0550ae;
    }}
    QPushButton[role="primary"]:focus {{
        background: #0550ae;
        border-color: #0550ae;
    }}
    QPushButton[navRole="back"] {{
        min-width: 96px;
    }}
    QLineEdit, QPlainTextEdit, QComboBox {{
        min-height: {field_height}px;
        border: 1px solid #d0d7de;
        border-radius: {radius}px;
        padding: 0 10px;
        background: #ffffff;
        color: #24292f;
        selection-background-color: #0969da;
        selection-color: #ffffff;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
        border-color: #0969da;
    }}
    QComboBox QAbstractItemView {{
        border: 1px solid #d0d7de;
        background: #ffffff;
        selection-background-color: #0969da;
        selection-color: #ffffff;
        outline: 0;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background: #dbeafe;
        color: #111827;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background: #0969da;
        color: #ffffff;
    }}
    QLabel[state="success"] {{
        color: #1a7f37;
        font-weight: 600;
    }}
    QLabel[state="warning"] {{
        color: #9a6700;
        font-weight: 600;
    }}
    QLabel[state="error"] {{
        color: #cf222e;
        font-weight: 600;
    }}
    QLabel[state="muted"] {{
        color: #656d76;
    }}
    QProgressBar {{
        min-height: {field_height}px;
    }}
    """


def build_dark_stylesheet(font_size: int) -> str:
    field_height = max(34, int(font_size * 2.2))
    button_height = max(36, int(font_size * 2.35))
    radius = max(8, int(font_size * 0.55))
    return f"""
    QWidget {{
        font-size: {font_size}px;
        background: #1e1e2e;
        color: #cdd6f4;
    }}
    QPushButton {{
        min-height: {button_height}px;
        padding: 4px 14px;
        border-radius: {radius}px;
        border: 1px solid #45475a;
        background: #313244;
        color: #cdd6f4;
    }}
    QPushButton:hover {{
        background: #45475a;
    }}
    QPushButton:focus {{
        border-color: #89b4fa;
        background: #45475a;
    }}
    QPushButton[role="primary"] {{
        background: #89b4fa;
        border-color: #89b4fa;
        color: #1e1e2e;
        font-weight: 600;
    }}
    QPushButton[role="primary"]:hover {{
        background: #74c7ec;
        border-color: #74c7ec;
    }}
    QPushButton[role="primary"]:focus {{
        background: #74c7ec;
        border-color: #74c7ec;
    }}
    QPushButton[navRole="back"] {{
        min-width: 96px;
    }}
    QLineEdit, QPlainTextEdit, QComboBox {{
        min-height: {field_height}px;
        border: 1px solid #45475a;
        border-radius: {radius}px;
        padding: 0 10px;
        background: #313244;
        color: #cdd6f4;
        selection-background-color: #89b4fa;
        selection-color: #1e1e2e;
    }}
    QLineEdit:focus, QPlainTextEdit:focus, QComboBox:focus {{
        border-color: #89b4fa;
    }}
    QComboBox QAbstractItemView {{
        border: 1px solid #45475a;
        background: #313244;
        selection-background-color: #89b4fa;
        selection-color: #1e1e2e;
        outline: 0;
    }}
    QComboBox QAbstractItemView::item:hover {{
        background: #45475a;
        color: #cdd6f4;
    }}
    QComboBox QAbstractItemView::item:selected {{
        background: #89b4fa;
        color: #1e1e2e;
    }}
    QLabel[state="success"] {{
        color: #a6e3a1;
        font-weight: 600;
    }}
    QLabel[state="warning"] {{
        color: #f9e2af;
        font-weight: 600;
    }}
    QLabel[state="error"] {{
        color: #f38ba8;
        font-weight: 600;
    }}
    QLabel[state="muted"] {{
        color: #6c7086;
    }}
    QProgressBar {{
        min-height: {field_height}px;
        background: #313244;
        border: 1px solid #45475a;
        border-radius: {radius}px;
    }}
    QProgressBar::chunk {{
        background: #89b4fa;
        border-radius: {radius}px;
    }}
    QTableWidget {{
        background: #313244;
        color: #cdd6f4;
        border: 1px solid #45475a;
        gridline-color: #45475a;
    }}
    QTableWidget::item:selected {{
        background: #89b4fa;
        color: #1e1e2e;
    }}
    QHeaderView::section {{
        background: #313244;
        color: #cdd6f4;
        border: 1px solid #45475a;
        padding: 4px 8px;
    }}
    QGroupBox {{
        background: #1e1e2e;
        color: #cdd6f4;
        border: 1px solid #45475a;
        border-radius: {radius}px;
        margin-top: 8px;
        padding-top: 12px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
    }}
    QMenu {{
        background: #313244;
        color: #cdd6f4;
        border: 1px solid #45475a;
    }}
    QMenu::item:selected {{
        background: #89b4fa;
        color: #1e1e2e;
    }}
    QCheckBox {{
        color: #cdd6f4;
    }}
    QScrollBar:vertical {{
        background: #1e1e2e;
        width: 10px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: #45475a;
        min-height: 20px;
        border-radius: 5px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #585b70;
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: #1e1e2e;
        height: 10px;
        margin: 0;
    }}
    QScrollBar::handle:horizontal {{
        background: #45475a;
        min-width: 20px;
        border-radius: 5px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background: #585b70;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0;
    }}
    QToolTip {{
        background: #313244;
        color: #cdd6f4;
        border: 1px solid #45475a;
        padding: 4px 8px;
        border-radius: 4px;
    }}
    QStatusBar {{
        background: #313244;
        color: #cdd6f4;
        border-top: 1px solid #45475a;
    }}
    """


def apply_app_style(app: QApplication, font_size: int, theme: str = "light") -> int:
    normalized = clamp_ui_font_size(font_size)
    if theme == "dark":
        app.setStyleSheet(build_dark_stylesheet(normalized))
    else:
        app.setStyleSheet(build_app_stylesheet(normalized))
    return normalized


def set_button_role(button: QPushButton, role: Optional[str]) -> None:
    button.setProperty("role", role or "")
    button.style().unpolish(button)
    button.style().polish(button)
    if role == "primary":
        button.setDefault(True)
        button.setAutoDefault(True)


def set_back_button(button: QPushButton) -> None:
    button.setProperty("navRole", "back")
    button.setAutoDefault(False)
    button.setDefault(False)
    button.style().unpolish(button)
    button.style().polish(button)


def set_secondary_button(button: QPushButton) -> None:
    button.setAutoDefault(False)
    button.setDefault(False)
    button.style().unpolish(button)
    button.style().polish(button)


def set_label_state(label: QLabel, state: str) -> None:
    label.setProperty("state", state)
    label.style().unpolish(label)
    label.style().polish(label)