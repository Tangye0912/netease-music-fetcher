#!/usr/bin/env python3
"""
Download manager dialog — history browser with status filter, file open/delete,
and failed-task retry.

Extracted from music_fetch.dialogs.py to reduce module size.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from music_fetch.app_logging import get_logger
from music_fetch.app_settings import (
    DEFAULT_DOWNLOAD_DIR,
    DOWNLOAD_HISTORY_PAGE_SIZE,
    MAX_DOWNLOAD_RETRY_COUNT,
    MAX_DOWNLOAD_TIMEOUT_SEC,
    MIN_DOWNLOAD_RETRY_COUNT,
    MIN_DOWNLOAD_TIMEOUT_SEC,
)
from music_fetch.app_stores import DownloadHistoryStore, DownloadRecord
from music_fetch.download_retry import can_retry_status, retry_target_format
from music_fetch.history_results import build_download_history_csv, filter_download_history
from music_fetch.dialog_progress import DownloadProgressDialog
from music_fetch.download_tasks import (
    TASK_STATE_CANCELED,
    TASK_STATE_FAILED,
    TASK_STATE_PENDING,
    TASK_STATE_SUCCESS,
    TASK_STATE_DOWNLOADING,
    build_task_id,
)
from music_fetch.batch_models import format_bytes
from music_fetch.gui_styles import (
    set_back_button,
    set_label_state,
    set_secondary_button,
)
import music_fetch.ui_texts as T

try:
    from PySide6.QtCore import Qt, QUrl
    from PySide6.QtGui import QDesktopServices
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QComboBox,
        QDialog,
        QFileDialog,
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



__all__ = ['DownloadManagerDialog']
class DownloadManagerDialog(QDialog):
    def __init__(
        self,
        history_store: DownloadHistoryStore,
        cookie: str,
        download_timeout_sec: int,
        download_retry_count: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.history_store = history_store
        self.cookie = cookie
        self.download_timeout_sec = max(MIN_DOWNLOAD_TIMEOUT_SEC, min(MAX_DOWNLOAD_TIMEOUT_SEC, int(download_timeout_sec)))
        self.download_retry_count = max(MIN_DOWNLOAD_RETRY_COUNT, min(MAX_DOWNLOAD_RETRY_COUNT, int(download_retry_count)))
        self.records: list[DownloadRecord] = []
        self.filtered_records: list[DownloadRecord] = []
        self.page_records: list[DownloadRecord] = []
        self.current_page = 0
        self.page_size = DOWNLOAD_HISTORY_PAGE_SIZE
        self.setWindowTitle(T.MANAGER_TITLE)
        self.resize(900, 420)

        layout = QVBoxLayout(self)
        # v0.4.0: allow users to inspect history by task state.
        filter_row = QHBoxLayout()
        self.filter_label = QLabel(T.MANAGER_FILTER_LABEL)
        self.filter_combo = QComboBox()
        self.filter_combo.setMinimumWidth(170)
        self.filter_combo.setMinimumContentsLength(12)
        self.filter_combo.view().setMinimumWidth(190)
        self.filter_combo.addItem(T.MANAGER_FILTER_ALL, "all")
        self.filter_combo.addItem(T.MANAGER_FILTER_SUCCESS, TASK_STATE_SUCCESS)
        self.filter_combo.addItem(T.MANAGER_FILTER_FAILED, TASK_STATE_FAILED)
        self.filter_combo.addItem(T.MANAGER_FILTER_CANCELED, TASK_STATE_CANCELED)
        self.filter_combo.addItem(T.MANAGER_FILTER_PENDING, TASK_STATE_PENDING)
        self.filter_combo.addItem(T.MANAGER_FILTER_DOWNLOADING, TASK_STATE_DOWNLOADING)
        self.filter_combo.currentIndexChanged.connect(self._on_filter_changed)
        filter_row.addWidget(self.filter_label)
        filter_row.addWidget(self.filter_combo)
        filter_row.addSpacing(12)
        search_label = QLabel(T.MANAGER_SEARCH_LABEL)
        filter_row.addWidget(search_label)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(T.MANAGER_SEARCH_PLACEHOLDER)
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self._on_search_changed)
        filter_row.addWidget(self.search_input, stretch=1)
        layout.addLayout(filter_row)

        self.empty_label = QLabel(T.MSG_DOWNLOADS_EMPTY)
        set_label_state(self.empty_label, "muted")
        self.empty_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty_label)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                T.MANAGER_COL_SONG,
                T.MANAGER_COL_FILENAME,
                T.MANAGER_COL_SIZE,
                T.MANAGER_COL_TIME,
                T.MANAGER_COL_STATUS,
                T.MANAGER_COL_PATH,
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        layout.addWidget(self.table)

        page_row = QHBoxLayout()
        page_row.addStretch(1)
        self.previous_page_button = QPushButton(T.MANAGER_BTN_PREVIOUS_PAGE)
        set_secondary_button(self.previous_page_button)
        self.previous_page_button.clicked.connect(self._go_previous_page)
        page_row.addWidget(self.previous_page_button)
        self.page_label = QLabel("")
        self.page_label.setAlignment(Qt.AlignCenter)
        page_row.addWidget(self.page_label)
        self.next_page_button = QPushButton(T.MANAGER_BTN_NEXT_PAGE)
        set_secondary_button(self.next_page_button)
        self.next_page_button.clicked.connect(self._go_next_page)
        page_row.addWidget(self.next_page_button)
        page_row.addStretch(1)
        layout.addLayout(page_row)

        button_row = QHBoxLayout()
        self.open_folder_button = QPushButton(T.MANAGER_BTN_OPEN_FOLDER)
        self.open_folder_button.clicked.connect(self._open_selected_folder)
        self.delete_button = QPushButton(T.MANAGER_BTN_DELETE_FILE)
        self.delete_button.clicked.connect(self._delete_selected_file)
        self.retry_failed_button = QPushButton(T.MANAGER_BTN_RETRY_FAILED)
        self.retry_failed_button.clicked.connect(self._retry_selected_failed)
        self.export_csv_button = QPushButton(T.MANAGER_BTN_EXPORT_CSV)
        set_secondary_button(self.export_csv_button)
        self.export_csv_button.clicked.connect(self._export_filtered_csv)
        refresh_button = QPushButton(T.MANAGER_BTN_REFRESH)
        refresh_button.clicked.connect(self.refresh)
        close_button = QPushButton(T.BTN_BACK)
        close_button.clicked.connect(self.accept)
        set_back_button(close_button)
        button_row.addWidget(self.open_folder_button)
        button_row.addWidget(self.delete_button)
        button_row.addWidget(self.retry_failed_button)
        button_row.addWidget(self.export_csv_button)
        button_row.addStretch(1)
        button_row.addWidget(refresh_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.table.itemSelectionChanged.connect(self._sync_action_buttons)
        self.refresh()

    def refresh(self, *_args: object) -> None:
        self.records = self.history_store.load()
        status_filter = str(self.filter_combo.currentData())
        self.filtered_records = filter_download_history(
            self.records,
            status_filter=status_filter,
            query=self.search_input.text(),
        )
        self._render_current_page()

    def _render_current_page(self) -> None:
        status_filter = str(self.filter_combo.currentData())
        total_records = len(self.filtered_records)
        total_pages = (total_records + self.page_size - 1) // self.page_size
        if total_pages:
            self.current_page = min(max(self.current_page, 0), total_pages - 1)
        else:
            self.current_page = 0
        page_start = self.current_page * self.page_size
        self.page_records = self.filtered_records[page_start:page_start + self.page_size]

        if not self.records:
            self.empty_label.setText(T.MSG_DOWNLOADS_EMPTY)
        elif not self.filtered_records:
            self.empty_label.setText(T.MSG_DOWNLOADS_FILTER_EMPTY)
        else:
            self.empty_label.setText("")
        self.empty_label.setVisible(len(self.filtered_records) == 0)
        self.table.setVisible(len(self.filtered_records) > 0)
        self.table.clearSelection()
        self.table.setCurrentCell(-1, -1)
        self.table.setRowCount(len(self.page_records))
        for row, record in enumerate(self.page_records):
            file_name = Path(record.output_path).name
            self.table.setItem(row, 0, QTableWidgetItem(record.song_name))
            self.table.setItem(row, 1, QTableWidgetItem(file_name))
            self.table.setItem(row, 2, QTableWidgetItem(format_bytes(record.size_bytes)))
            self.table.setItem(row, 3, QTableWidgetItem(record.downloaded_at))
            self.table.setItem(row, 4, QTableWidgetItem(T.manager_status_text(record.status)))
            self.table.setItem(row, 5, QTableWidgetItem(record.output_path))
        displayed_page = self.current_page + 1 if total_pages else 0
        self.page_label.setText(
            T.MANAGER_PAGE_SUMMARY.format(
                current=displayed_page,
                total=total_pages,
                count=total_records,
            )
        )
        self.previous_page_button.setEnabled(self.current_page > 0)
        self.next_page_button.setEnabled(self.current_page + 1 < total_pages)
        self.export_csv_button.setEnabled(bool(self.filtered_records))
        logger.info(
            "Download manager refreshed. total=%s filtered=%s page=%s/%s filter=%s",
            len(self.records),
            len(self.filtered_records),
            displayed_page,
            total_pages,
            status_filter,
        )
        self._sync_action_buttons()

    def _on_filter_changed(self, *_args: object) -> None:
        self.current_page = 0
        self.refresh()

    def _on_search_changed(self, *_args: object) -> None:
        self.current_page = 0
        self.refresh()

    def _go_previous_page(self, *_args: object) -> None:
        if self.current_page > 0:
            self.current_page -= 1
            self._render_current_page()

    def _go_next_page(self, *_args: object) -> None:
        if (self.current_page + 1) * self.page_size < len(self.filtered_records):
            self.current_page += 1
            self._render_current_page()

    def _selected_record(self) -> Optional[DownloadRecord]:
        current = self.table.currentRow()
        if current < 0 or current >= len(self.page_records):
            return None
        return self.page_records[current]

    def _sync_action_buttons(self) -> None:
        record = self._selected_record()
        has_selection = record is not None
        self.open_folder_button.setEnabled(has_selection)
        self.delete_button.setEnabled(has_selection)
        self.retry_failed_button.setEnabled(bool(record and can_retry_status(record.status)))

    def _open_selected_folder(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_NOT_SELECTED_RECORD)
            return
        folder = Path(record.output_path).expanduser().parent
        if not folder.exists():
            QMessageBox.warning(self, T.TITLE_PATH_MISSING, T.MANAGER_MISSING_FOLDER.format(folder=folder))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        logger.info("Download manager opened folder. folder=%s", folder)

    def _export_filtered_csv(self, *_args: object) -> None:
        if not self.filtered_records:
            QMessageBox.information(self, T.TITLE_WARNING, T.MANAGER_EXPORT_EMPTY)
            return
        default_name = f"download-history-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
        default_path = str(Path(DEFAULT_DOWNLOAD_DIR).expanduser() / default_name)
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            T.MANAGER_EXPORT_TITLE,
            default_path,
            T.MANAGER_EXPORT_FILTER,
        )
        if not selected:
            return
        output_path = Path(selected).expanduser()
        if not output_path.suffix:
            output_path = output_path.with_suffix(".csv")
        try:
            output_path.write_text(
                build_download_history_csv(self.filtered_records),
                encoding="utf-8-sig",
            )
        except OSError as err:
            QMessageBox.critical(
                self,
                T.TITLE_DOWNLOAD_FAIL,
                T.MANAGER_EXPORT_FAILED.format(message=str(err)),
            )
            return
        QMessageBox.information(
            self,
            T.TITLE_DOWNLOAD_DONE,
            T.MANAGER_EXPORT_DONE.format(path=output_path),
        )
        logger.info(
            "Download history exported. path=%s records=%s filter=%s query=%s",
            output_path,
            len(self.filtered_records),
            self.filter_combo.currentData(),
            bool(self.search_input.text().strip()),
        )

    def _delete_selected_file(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_NOT_SELECTED_RECORD)
            return
        path = Path(record.output_path).expanduser()
        answer = QMessageBox.question(
            self,
            T.TITLE_DELETE_CONFIRM,
            T.MANAGER_DELETE_CONFIRM.format(path=path),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        if path.exists():
            try:
                path.unlink()
                logger.info("Deleted downloaded file from manager. path=%s", path)
            except OSError as err:
                QMessageBox.warning(self, T.TITLE_DELETE_FAIL, str(err))
                logger.warning("Failed to delete file from manager. path=%s error=%s", path, err)
                return
        self.history_store.remove_by_path(str(path))
        self.refresh()

    def _retry_selected_failed(self) -> None:
        record = self._selected_record()
        if not record:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_NOT_SELECTED_RECORD)
            return
        if not can_retry_status(record.status):
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_RETRY_ONLY_FAILED)
            return
        if not self.cookie:
            QMessageBox.warning(self, T.TITLE_NOT_LOGIN, T.MSG_NEED_LOGIN_ANY)
            return

        output_path = Path(record.output_path).expanduser()
        task_id = build_task_id(record.song_id)
        target_format = retry_target_format(output_path)
        logger.info(
            "Retry failed task requested. task_id=%s song_id=%s output=%s",
            task_id,
            record.song_id,
            output_path,
        )
        progress = DownloadProgressDialog(
            task_id=task_id,
            song_id=record.song_id,
            output_path=output_path,
            cookie=self.cookie,
            target_format=target_format,
            timeout=self.download_timeout_sec,
            retry_count=self.download_retry_count,
        )
        if progress.exec() == QDialog.Accepted and progress.output_path:
            size_bytes = progress.output_path.stat().st_size if progress.output_path.exists() else 0
            self.history_store.remove_by_path(str(output_path))
            self.history_store.add(
                DownloadRecord(
                    song_id=record.song_id,
                    song_name=record.song_name,
                    output_path=str(progress.output_path),
                    size_bytes=size_bytes,
                    downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    status=TASK_STATE_SUCCESS,
                )
            )
            logger.info("Retry task finished with success. task_id=%s", task_id)
        elif progress.result_state == TASK_STATE_FAILED:
            self.history_store.remove_by_path(str(output_path))
            self.history_store.add(
                DownloadRecord(
                    song_id=record.song_id,
                    song_name=record.song_name,
                    output_path=str(output_path),
                    size_bytes=0,
                    downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    status=TASK_STATE_FAILED,
                    error_code=progress.error_code,
                )
            )
            logger.warning("Retry task finished with failure. task_id=%s code=%s", task_id, progress.error_code)
        else:
            self.history_store.remove_by_path(str(output_path))
            self.history_store.add(
                DownloadRecord(
                    song_id=record.song_id,
                    song_name=record.song_name,
                    output_path=str(output_path),
                    size_bytes=0,
                    downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    status=TASK_STATE_CANCELED,
                )
            )
            logger.info("Retry task finished with canceled. task_id=%s", task_id)
        self.refresh()
