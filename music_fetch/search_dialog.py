#!/usr/bin/env python3
"""
Search dialog — search songs by keyword and download directly.

Extracted as a separate module to keep main.py manageable.
"""

from __future__ import annotations

from typing import Optional

from music_fetch.app_logging import get_logger
from music_fetch.api import SearchResult, search_songs
from music_fetch.batch_models import format_duration
from music_fetch.gui_styles import set_back_button, set_button_role, set_label_state, set_secondary_button
import music_fetch.ui_texts as T

try:
    from PySide6.QtCore import QThread, Signal
    from PySide6.QtWidgets import (
        QDialog,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPushButton,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as err:
    raise SystemExit(
        "Missing dependency: PySide6. Install it with `python3 -m pip install PySide6` before running main.py."
    ) from err

logger = get_logger("music_fetch.gui")

__all__ = ["SearchDialog", "SearchWorker"]


class SearchWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, keyword: str, cookie: str, timeout: int = 10) -> None:
        super().__init__()
        self.keyword = keyword
        self.cookie = cookie
        self.timeout = timeout

    def run(self) -> None:
        try:
            results = search_songs(self.keyword, self.cookie, timeout=self.timeout)
            self.succeeded.emit(results)
        except (OSError, ValueError, TypeError) as err:
            logger.exception("SearchWorker unexpected error.")
            self.failed.emit("UNKNOWN_ERROR", str(err))


class SearchDialog(QDialog):
    def __init__(self, cookie: str, timeout: int = 10, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.cookie = cookie
        self.timeout = timeout
        self.search_worker: Optional[SearchWorker] = None
        self.results: list[SearchResult] = []
        self.selected_result: Optional[SearchResult] = None
        self.setWindowTitle(T.SEARCH_TITLE)
        self.resize(700, 450)

        layout = QVBoxLayout(self)

        # Search bar
        search_row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText(T.SEARCH_PLACEHOLDER)
        self.input.returnPressed.connect(self._on_search)
        search_row.addWidget(self.input, stretch=1)
        self.search_button = QPushButton(T.SEARCH_BTN)
        set_button_role(self.search_button, "primary")
        self.search_button.clicked.connect(self._on_search)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)

        self.hint_label = QLabel(T.SEARCH_HINT)
        set_label_state(self.hint_label, "muted")
        layout.addWidget(self.hint_label)

        # Results table
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            T.SEARCH_COL_SONG, T.SEARCH_COL_ARTIST, T.SEARCH_COL_ALBUM,
            T.SEARCH_COL_DURATION, T.SEARCH_COL_ACTION,
        ])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, stretch=1)

        # Back button
        button_row = QHBoxLayout()
        button_row.addStretch(1)
        back_button = QPushButton(T.BTN_BACK)
        back_button.clicked.connect(self.reject)
        set_back_button(back_button)
        button_row.addWidget(back_button)
        layout.addLayout(button_row)

        self.input.setFocus()

    def _on_search(self) -> None:
        keyword = self.input.text().strip()
        if not keyword:
            return
        if self.search_worker and self.search_worker.isRunning():
            return
        self.search_button.setEnabled(False)
        self.search_button.setText(T.SEARCH_BTN_SEARCHING)
        self.hint_label.setText(T.SEARCH_BTN_SEARCHING)
        set_label_state(self.hint_label, "muted")
        self.search_worker = SearchWorker(keyword, self.cookie, timeout=self.timeout)
        self.search_worker.succeeded.connect(self._on_search_succeeded)
        self.search_worker.failed.connect(self._on_search_failed)
        self.search_worker.start()

    def _on_search_succeeded(self, results: list[SearchResult]) -> None:
        self.search_button.setEnabled(True)
        self.search_button.setText(T.SEARCH_BTN)
        self.results = results
        self.table.setRowCount(len(results))
        for row, result in enumerate(results):
            self.table.setItem(row, 0, QTableWidgetItem(result.song_name))
            self.table.setItem(row, 1, QTableWidgetItem(result.artist))
            self.table.setItem(row, 2, QTableWidgetItem(result.album))
            self.table.setItem(row, 3, QTableWidgetItem(format_duration(result.duration_ms) if result.duration_ms else ""))
            download_btn = QPushButton(T.SEARCH_DOWNLOAD_BTN)
            set_secondary_button(download_btn)
            download_btn.clicked.connect(lambda _, r=row: self._on_download_clicked(r))
            self.table.setCellWidget(row, 4, download_btn)
        if not results:
            self.hint_label.setText(T.SEARCH_EMPTY)
            set_label_state(self.hint_label, "muted")
        else:
            self.hint_label.setText("")
        logger.info("Search dialog results displayed. count=%s", len(results))

    def _on_search_failed(self, code: str, message: str) -> None:
        self.search_button.setEnabled(True)
        self.search_button.setText(T.SEARCH_BTN)
        self.hint_label.setText(f"{code}: {message}")
        set_label_state(self.hint_label, "error")

    def _on_download_clicked(self, row: int) -> None:
        if row < 0 or row >= len(self.results):
            return
        self.selected_result = self.results[row]
        self.accept()