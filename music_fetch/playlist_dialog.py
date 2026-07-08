#!/usr/bin/env python3
"""
User playlist dialog — browse logged-in user's playlists and open for batch download.
"""

from __future__ import annotations

from typing import Optional

from music_fetch.app_logging import get_logger
from music_fetch.api import MusicFetchError, UserPlaylist, fetch_user_playlists
from music_fetch.gui_styles import set_back_button, set_label_state, set_secondary_button
import music_fetch.ui_texts as T

try:
    from PySide6.QtCore import QThread, Signal
    from PySide6.QtWidgets import (
        QDialog,
        QHBoxLayout,
        QHeaderView,
        QLabel,
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

__all__ = ["PlaylistDialog", "PlaylistFetchWorker"]


class PlaylistFetchWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, cookie: str, timeout: int = 10) -> None:
        super().__init__()
        self.cookie = cookie
        self.timeout = timeout

    def run(self) -> None:
        try:
            playlists = fetch_user_playlists(self.cookie, timeout=self.timeout)
            self.succeeded.emit(playlists)
        except MusicFetchError as err:
            logger.warning("PlaylistFetchWorker failed. code=%s message=%s", err.code, err.message)
            self.failed.emit(err.code, err.message)
        except (OSError, ValueError, TypeError) as err:
            logger.exception("PlaylistFetchWorker unexpected error.")
            self.failed.emit("UNKNOWN_ERROR", str(err))


class PlaylistDialog(QDialog):
    def __init__(self, cookie: str, timeout: int = 10, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.cookie = cookie
        self.timeout = timeout
        self.fetch_worker: Optional[PlaylistFetchWorker] = None
        self.playlists: list[UserPlaylist] = []
        self.selected_playlist: Optional[UserPlaylist] = None
        self.setWindowTitle(T.PLAYLIST_TITLE)
        self.resize(600, 400)

        layout = QVBoxLayout(self)

        self.hint_label = QLabel(T.PLAYLIST_EMPTY)
        set_label_state(self.hint_label, "muted")
        layout.addWidget(self.hint_label)

        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([
            T.PLAYLIST_COL_NAME, T.PLAYLIST_COL_COUNT, T.PLAYLIST_COL_CREATOR,
        ])
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        layout.addWidget(self.table, stretch=1)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        back_button = QPushButton(T.BTN_BACK)
        back_button.clicked.connect(self.reject)
        set_back_button(back_button)
        button_row.addWidget(back_button)
        layout.addLayout(button_row)

        self._start_fetch()

    def _start_fetch(self) -> None:
        self.hint_label.setText(T.SEARCH_BTN_SEARCHING)
        set_label_state(self.hint_label, "muted")
        self.fetch_worker = PlaylistFetchWorker(self.cookie, timeout=self.timeout)
        self.fetch_worker.succeeded.connect(self._on_fetch_succeeded)
        self.fetch_worker.failed.connect(self._on_fetch_failed)
        self.fetch_worker.finished.connect(self.fetch_worker.deleteLater)
        self.fetch_worker.start()

    def _on_fetch_succeeded(self, playlists: list[UserPlaylist]) -> None:
        self.playlists = playlists
        self.table.setRowCount(len(playlists))
        for row, pl in enumerate(playlists):
            self.table.setItem(row, 0, QTableWidgetItem(pl.name))
            self.table.setItem(row, 1, QTableWidgetItem(str(pl.song_count)))
            self.table.setItem(row, 2, QTableWidgetItem(pl.creator))
        # Add button column
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderItem(3, QTableWidgetItem(""))
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        for row, pl in enumerate(playlists):
            open_btn = QPushButton(T.PLAYLIST_BTN_OPEN)
            set_secondary_button(open_btn)
            open_btn.clicked.connect(lambda _, r=row: self._on_open_clicked(r))
            self.table.setCellWidget(row, 3, open_btn)
        if not playlists:
            self.hint_label.setText(T.PLAYLIST_EMPTY)
            set_label_state(self.hint_label, "muted")
        else:
            self.hint_label.setText("")
        logger.info("Playlist dialog results displayed. count=%s", len(playlists))

    def _on_fetch_failed(self, code: str, message: str) -> None:
        self.hint_label.setText(f"{code}: {message}")
        set_label_state(self.hint_label, "error")

    def _on_open_clicked(self, row: int) -> None:
        if row < 0 or row >= len(self.playlists):
            return
        self.selected_playlist = self.playlists[row]
        self.accept()