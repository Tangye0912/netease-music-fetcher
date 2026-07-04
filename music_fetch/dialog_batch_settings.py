#!/usr/bin/env python3
"""
Batch runtime settings dialog — lightweight in-workflow settings for
detect/download timeout, retry count, and concurrency.

Extracted from music_fetch.batch_dialogs.py to reduce module size.
"""

from __future__ import annotations

from music_fetch.app_settings import (
    clamp_download_settings,
    DEFAULT_DETECT_TIMEOUT_SEC,
    DEFAULT_DOWNLOAD_CONCURRENCY,
    DEFAULT_DOWNLOAD_RETRY_COUNT,
    DEFAULT_DOWNLOAD_TIMEOUT_SEC,
    DETECT_TIMEOUT_OPTIONS,
    DOWNLOAD_TIMEOUT_OPTIONS,
    MAX_DOWNLOAD_CONCURRENCY,
    MAX_DOWNLOAD_RETRY_COUNT,
    MAX_DOWNLOAD_TIMEOUT_SEC,
    MIN_DOWNLOAD_CONCURRENCY,
    MIN_DOWNLOAD_RETRY_COUNT,
    MIN_DOWNLOAD_TIMEOUT_SEC,
    clamp,
)
from music_fetch.gui_styles import (
    set_back_button,
    set_button_role,
    set_label_state,
)
import music_fetch.combo_utils
import music_fetch.ui_texts as T

try:
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QDialog,
        QFormLayout,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as err:
    raise SystemExit(
        "Missing dependency: PySide6. Install it with `python3 -m pip install PySide6` before running main.py."
    ) from err



__all__ = ['BatchRuntimeSettingsDialog']
class BatchRuntimeSettingsDialog(QDialog):
    """Lightweight settings dialog used inside batch workflow."""

    def __init__(
        self,
        detect_timeout_sec: int,
        download_timeout_sec: int,
        download_retry_count: int,
        download_concurrency: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.detect_timeout_sec, self.download_timeout_sec, self.download_retry_count, self.download_concurrency = clamp_download_settings(
            detect_timeout_sec, download_timeout_sec, download_retry_count, download_concurrency,
        )
        self.setWindowTitle(T.BATCH_BTN_SETTINGS)
        self.resize(480, 260)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.detect_timeout_input = music_fetch.combo_utils.build_options_combo(DETECT_TIMEOUT_OPTIONS, "s")
        music_fetch.combo_utils.set_combo_value(self.detect_timeout_input, self.detect_timeout_sec)
        form.addRow(T.UI_SETTINGS_DETECT_TIMEOUT, self.detect_timeout_input)

        self.download_timeout_input = music_fetch.combo_utils.build_options_combo(DOWNLOAD_TIMEOUT_OPTIONS, "s")
        music_fetch.combo_utils.set_combo_value(self.download_timeout_input, self.download_timeout_sec)
        form.addRow(T.UI_SETTINGS_DOWNLOAD_TIMEOUT, self.download_timeout_input)

        self.download_retry_input = music_fetch.combo_utils.build_value_combo(MIN_DOWNLOAD_RETRY_COUNT, MAX_DOWNLOAD_RETRY_COUNT, T.COUNT_SUFFIX)
        music_fetch.combo_utils.set_combo_value(self.download_retry_input, self.download_retry_count)
        form.addRow(T.UI_SETTINGS_DOWNLOAD_RETRY, self.download_retry_input)

        self.download_concurrency_input = music_fetch.combo_utils.build_value_combo(
            MIN_DOWNLOAD_CONCURRENCY, MAX_DOWNLOAD_CONCURRENCY, T.CONCURRENCY_SUFFIX
        )
        music_fetch.combo_utils.set_combo_value(self.download_concurrency_input, self.download_concurrency)
        form.addRow(T.UI_SETTINGS_DOWNLOAD_CONCURRENCY, self.download_concurrency_input)
        layout.addLayout(form)

        hint = QLabel(T.UI_SETTINGS_DOWNLOAD_CONCURRENCY_HINT)
        hint.setWordWrap(True)
        set_label_state(hint, "muted")
        layout.addWidget(hint)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton(T.BTN_BACK)
        cancel_button.clicked.connect(self.reject)
        set_back_button(cancel_button)
        save_button = QPushButton(T.UI_SETTINGS_SAVE)
        save_button.clicked.connect(self._on_save)
        set_button_role(save_button, "primary")
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    def _on_save(self) -> None:
        self.detect_timeout_sec, self.download_timeout_sec, self.download_retry_count, self.download_concurrency = clamp_download_settings(
            music_fetch.combo_utils.combo_int_value(self.detect_timeout_input, DEFAULT_DETECT_TIMEOUT_SEC),
            music_fetch.combo_utils.combo_int_value(self.download_timeout_input, DEFAULT_DOWNLOAD_TIMEOUT_SEC),
            music_fetch.combo_utils.combo_int_value(self.download_retry_input, DEFAULT_DOWNLOAD_RETRY_COUNT),
            music_fetch.combo_utils.combo_int_value(self.download_concurrency_input, DEFAULT_DOWNLOAD_CONCURRENCY),
        )
        self.accept()


