#!/usr/bin/env python3
"""Batch download dialogs extracted from music_fetch.dialogs.py."""

from __future__ import annotations

import copy
import functools
from datetime import datetime
from pathlib import Path
from typing import Optional

from music_fetch.app_logging import get_logger
from music_fetch.app_settings import (
    clamp_download_settings,
    DEFAULT_DETECT_TIMEOUT_SEC,
    DEFAULT_DOWNLOAD_CONCURRENCY,
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_DOWNLOAD_RETRY_COUNT,
    DEFAULT_DOWNLOAD_TIMEOUT_SEC,
    DETECT_TIMEOUT_OPTIONS,
    DOWNLOAD_TIMEOUT_OPTIONS,
    MAX_DETECT_TIMEOUT_SEC,
    MAX_DOWNLOAD_CONCURRENCY,
    MAX_DOWNLOAD_RETRY_COUNT,
    MAX_DOWNLOAD_TIMEOUT_SEC,
    MIN_DETECT_TIMEOUT_SEC,
    MIN_DOWNLOAD_CONCURRENCY,
    MIN_DOWNLOAD_RETRY_COUNT,
    MIN_DOWNLOAD_TIMEOUT_SEC,
    clamp,
)
from music_fetch.app_stores import DownloadHistoryStore, DownloadRecord
from music_fetch.download_tasks import (
    TASK_STATE_CANCELED,
    TASK_STATE_FAILED,
    TASK_STATE_SUCCESS,
    build_task_id,
)
from music_fetch.error_texts import UNKNOWN_ERROR, user_error_message
from music_fetch.api import MusicFetchError, SUPPORTED_GUI_AUDIO_FORMATS
from music_fetch.audio import is_ffmpeg_available, resolve_output_path
from music_fetch.batch_results import build_batch_results_csv, retryable_failed_rows, summarize_batch_rows
from music_fetch.gui_styles import set_button_role, set_label_state, set_secondary_button, set_back_button
from music_fetch.batch_models import BatchDetectRow, format_bytes
from music_fetch.dialog_batch_settings import BatchRuntimeSettingsDialog
import music_fetch.combo_utils
import music_fetch.workers
import music_fetch.ui_texts as T

try:
    from PySide6.QtCore import Qt, QTimer
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QComboBox,
        QDialog,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QProgressBar,
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


__all__ = ['BatchDownloadDialog']
class BatchDownloadDialog(QDialog):
    # v0.5.0: batch detect + batch download workflow entry.
    def __init__(
        self,
        cookie: str,
        history_store: DownloadHistoryStore,
        last_download_dir: str,
        detect_timeout_sec: int,
        download_timeout_sec: int,
        download_retry_count: int,
        download_concurrency: int,
        initial_input_text: str = "",
        auto_detect_on_open: bool = False,
        preloaded_rows: Optional[list[BatchDetectRow]] = None,
        preloaded_signature: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.cookie = cookie
        self.history_store = history_store
        self.detect_timeout_sec = clamp(detect_timeout_sec, DEFAULT_DETECT_TIMEOUT_SEC, MIN_DETECT_TIMEOUT_SEC, MAX_DETECT_TIMEOUT_SEC)
        self.download_timeout_sec = clamp(download_timeout_sec, DEFAULT_DOWNLOAD_TIMEOUT_SEC, MIN_DOWNLOAD_TIMEOUT_SEC, MAX_DOWNLOAD_TIMEOUT_SEC)
        self.download_retry_count = clamp(download_retry_count, DEFAULT_DOWNLOAD_RETRY_COUNT, MIN_DOWNLOAD_RETRY_COUNT, MAX_DOWNLOAD_RETRY_COUNT)
        self.download_concurrency = clamp(download_concurrency, DEFAULT_DOWNLOAD_CONCURRENCY, MIN_DOWNLOAD_CONCURRENCY, MAX_DOWNLOAD_CONCURRENCY)
        self.ffmpeg_available = is_ffmpeg_available()
        self.rows: list[BatchDetectRow] = []
        self.inspect_worker: Optional[music_fetch.workers.BatchInspectWorker] = None
        self.auto_detect_on_open = auto_detect_on_open
        self._last_detect_signature = ""
        self._restored_from_cache = False
        self._table_syncing = False
        self._downloading = False
        self._download_cancel_requested = False
        self._download_paused = False
        self._initialized = False
        self._download_queue: list[BatchDetectRow] = []
        self._download_total = 0
        self._download_next_index = 0
        self._download_cursor = 0
        self._download_success = 0
        self._download_failed = 0
        self._download_canceled = 0
        self._download_workers: dict[int, music_fetch.workers.DownloadWorker] = {}
        self._worker_rows: dict[int, BatchDetectRow] = {}
        self._worker_output_paths: dict[int, Path] = {}

        self.setWindowTitle(T.BATCH_DIALOG_TITLE)
        self.resize(1020, 620)

        root = QVBoxLayout(self)
        desc = QLabel(T.BATCH_DIALOG_DESC)
        desc.setWordWrap(True)
        root.addWidget(desc)

        root.addWidget(QLabel(T.BATCH_INPUT_LABEL))
        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText(T.BATCH_INPUT_PLACEHOLDER)
        self.input_edit.setMinimumHeight(72)
        self.input_edit.setMaximumHeight(160)
        self.input_edit.textChanged.connect(self._on_input_changed)
        if initial_input_text.strip():
            self.input_edit.setPlainText(initial_input_text.strip())
        self._sync_input_edit_height()
        root.addWidget(self.input_edit)

        form = QFormLayout()
        out_row = QHBoxLayout()
        self.out_dir_input = QLineEdit(last_download_dir or DEFAULT_DOWNLOAD_DIR)
        self.out_dir_input.setMinimumWidth(400)
        self.out_dir_input.setToolTip(self.out_dir_input.text())
        self.out_dir_input.textChanged.connect(self.out_dir_input.setToolTip)
        out_row.addWidget(self.out_dir_input, stretch=1)
        pick_button = QPushButton(T.BATCH_OUTPUT_PICKER_BTN)
        pick_button.setMinimumWidth(100)
        set_secondary_button(pick_button)
        pick_button.clicked.connect(self._pick_output_dir)
        out_row.addWidget(pick_button)
        form.addRow(T.BATCH_OUTPUT_DIR, out_row)

        self.format_combo = QComboBox()
        self.format_combo.addItems([fmt.upper() for fmt in SUPPORTED_GUI_AUDIO_FORMATS])
        self.format_combo.setMinimumWidth(220)
        self.format_combo.setMinimumContentsLength(12)
        self.format_combo.view().setMinimumWidth(240)
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        if not self.ffmpeg_available:
            self._set_format_safely("MP3")
        form.addRow(T.BATCH_TARGET_FORMAT, self.format_combo)
        root.addLayout(form)

        self.status_label = QLabel(T.BATCH_STATUS_IDLE)
        set_label_state(self.status_label, "muted")
        root.addWidget(self.status_label)

        self.batch_progress = QProgressBar()
        self.batch_progress.setRange(0, 1)
        self.batch_progress.setValue(0)
        root.addWidget(self.batch_progress)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            [
                T.BATCH_COL_SELECT,
                T.BATCH_COL_SOURCE,
                T.BATCH_COL_SONG_ID,
                T.BATCH_COL_SONG_NAME,
                T.BATCH_COL_SIZE,
                T.BATCH_COL_STATUS,
            ]
        )
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Fixed)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        header.setSectionResizeMode(3, QHeaderView.Fixed)
        header.setSectionResizeMode(4, QHeaderView.Fixed)
        header.setSectionResizeMode(5, QHeaderView.Stretch)
        self.table.itemChanged.connect(self._on_table_item_changed)
        root.addWidget(self.table, stretch=1)

        button_row = QHBoxLayout()
        self.detect_button = QPushButton(T.BATCH_BTN_DETECT)
        set_button_role(self.detect_button, "primary")
        self.detect_button.clicked.connect(self._on_detect_clicked)
        self.batch_settings_button = QPushButton(T.BATCH_BTN_SETTINGS)
        set_secondary_button(self.batch_settings_button)
        self.batch_settings_button.clicked.connect(self._on_open_batch_settings)
        self.select_all_button = QPushButton(T.BATCH_BTN_SELECT_ALL)
        set_secondary_button(self.select_all_button)
        self.select_all_button.clicked.connect(self._on_select_all_ready)
        self.select_all_button.setEnabled(False)
        self.invert_select_button = QPushButton(T.BATCH_BTN_INVERT)
        set_secondary_button(self.invert_select_button)
        self.invert_select_button.clicked.connect(self._on_invert_ready_selection)
        self.invert_select_button.setToolTip(T.BATCH_BTN_INVERT_TIP)
        self.invert_select_button.setEnabled(False)
        self.selection_summary_label = QLabel(T.BATCH_SELECTION_SUMMARY.format(selected=0, ready=0))
        set_label_state(self.selection_summary_label, "muted")
        self.download_button = QPushButton(T.BATCH_BTN_DOWNLOAD)
        self.download_button.setEnabled(False)
        self.download_button.clicked.connect(self._on_download_clicked)
        self.retry_failed_button = QPushButton(T.BATCH_BTN_RETRY_FAILED)
        set_secondary_button(self.retry_failed_button)
        self.retry_failed_button.setEnabled(False)
        self.retry_failed_button.clicked.connect(self._on_retry_failed_clicked)
        self.export_csv_button = QPushButton(T.BATCH_BTN_EXPORT_CSV)
        set_secondary_button(self.export_csv_button)
        self.export_csv_button.setEnabled(False)
        self.export_csv_button.clicked.connect(self._on_export_csv_clicked)
        self.cancel_download_button = QPushButton(T.BATCH_BTN_CANCEL)
        self.cancel_download_button.setEnabled(False)
        self.cancel_download_button.setVisible(False)
        self.cancel_download_button.clicked.connect(self._on_cancel_download_clicked)
        self.pause_download_button = QPushButton(T.BATCH_BTN_PAUSE)
        self.pause_download_button.setEnabled(False)
        self.pause_download_button.setVisible(False)
        self.pause_download_button.clicked.connect(self._on_pause_download_clicked)
        back_button = QPushButton(T.BTN_BACK)
        set_back_button(back_button)
        back_button.clicked.connect(self.reject)
        button_row.addWidget(self.detect_button)
        button_row.addWidget(self.batch_settings_button)
        button_row.addWidget(self.select_all_button)
        button_row.addWidget(self.invert_select_button)
        button_row.addWidget(self.selection_summary_label)
        button_row.addWidget(self.download_button)
        button_row.addWidget(self.retry_failed_button)
        button_row.addWidget(self.export_csv_button)
        button_row.addWidget(self.cancel_download_button)
        button_row.addStretch(1)
        button_row.addWidget(back_button)
        root.addLayout(button_row)

        current_signature = self._current_input_signature()
        if preloaded_rows and preloaded_signature and current_signature == preloaded_signature:
            self.rows = copy.deepcopy(preloaded_rows)
            self._last_detect_signature = preloaded_signature
            self._restored_from_cache = True
            self._render_rows()
            self.batch_progress.setRange(0, max(len(self.rows), 1))
            self.batch_progress.setValue(len(self.rows))
            self._set_detect_summary_status()

        self._update_detect_button_state()
        self._update_download_button_state()
        if self.auto_detect_on_open and not self._restored_from_cache and self.input_edit.toPlainText().strip():
            QTimer.singleShot(0, self._on_detect_clicked)
        QTimer.singleShot(0, self._adjust_table_columns)
        self.setTabOrder(self.input_edit, self.detect_button)
        self.setTabOrder(self.detect_button, self.out_dir_input)
        self._initialized = True

    def _current_input_signature(self) -> str:
        return self.input_edit.toPlainText().strip()

    def _input_changed_since_detect(self) -> bool:
        return bool(self._last_detect_signature) and self._current_input_signature() != self._last_detect_signature

    def _pick_output_dir(self) -> None:
        current = self.out_dir_input.text().strip() or DEFAULT_DOWNLOAD_DIR
        selected = QFileDialog.getExistingDirectory(self, T.BATCH_OUTPUT_PICKER_TITLE, current)
        if selected:
            self.out_dir_input.setText(selected)

    def _set_format_safely(self, value: str) -> None:
        normalized = value.upper().strip()
        idx = self.format_combo.findText(normalized)
        if idx >= 0:
            self.format_combo.blockSignals(True)
            try:
                self.format_combo.setCurrentIndex(idx)
            finally:
                self.format_combo.blockSignals(False)

    def _on_format_changed(self, value: str) -> None:
        if self.ffmpeg_available:
            return
        if value.lower().strip() == "mp3":
            return
        QMessageBox.information(self, T.TITLE_DEP_MISSING, T.MSG_FFMPEG_NEED_INSTALL)
        self._set_format_safely("MP3")

    def _sync_input_edit_height(self) -> None:
        text = self._current_input_signature()
        line_count = max(1, len(text.splitlines())) if text else 1
        char_count = len(text)
        target_height = 76
        if line_count >= 3 or char_count > 220:
            target_height = 108
        elif line_count == 2 or char_count > 120:
            target_height = 92
        self.input_edit.setFixedHeight(target_height)

    def _on_input_changed(self) -> None:
        self._sync_input_edit_height()
        self._update_detect_button_state()
        self._update_download_button_state()

    def _update_detect_button_state(self) -> None:
        if not self._initialized:
            return
        signature = self._current_input_signature()
        has_input = bool(signature)
        running_detect = bool(self.inspect_worker and self.inspect_worker.isRunning())
        unchanged = bool(self.rows) and signature == self._last_detect_signature
        can_detect = has_input and not self._downloading and not running_detect and not unchanged
        self.detect_button.setVisible(has_input and not self._downloading and not running_detect and not unchanged)
        self.detect_button.setEnabled(can_detect)
        if unchanged:
            self.detect_button.setToolTip(T.MSG_BATCH_INPUT_UNCHANGED)
        else:
            self.detect_button.setToolTip("")

    def _update_download_button_state(self) -> None:
        if not self._initialized:
            return
        running_detect = bool(self.inspect_worker and self.inspect_worker.isRunning())
        selected_ready = self._selected_ready_rows()
        selected_count = len(selected_ready)
        can_download = (
            not self._downloading
            and not running_detect
            and not self._input_changed_since_detect()
            and bool(selected_ready)
        )
        self.download_button.setEnabled(can_download)
        can_retry_failed = (
            not self._downloading
            and not running_detect
            and not self._input_changed_since_detect()
            and bool(retryable_failed_rows(self.rows))
        )
        self.retry_failed_button.setEnabled(can_retry_failed)
        self.export_csv_button.setEnabled(bool(self.rows) and not self._downloading and not running_detect)
        ready_count = len([row for row in self.rows if row.status == "ready"])
        can_toggle_select = (
            ready_count > 0
            and not self._downloading
            and not running_detect
            and not self._input_changed_since_detect()
        )
        all_ready_selected = ready_count > 0 and selected_count == ready_count
        self.select_all_button.setText(T.BATCH_BTN_CLEAR_ALL if all_ready_selected else T.BATCH_BTN_SELECT_ALL)
        self.select_all_button.setEnabled(can_toggle_select)
        self.invert_select_button.setEnabled(can_toggle_select)
        self.selection_summary_label.setText(
            T.BATCH_SELECTION_SUMMARY.format(selected=selected_count, ready=ready_count)
        )

    def _selected_ready_rows(self) -> list[BatchDetectRow]:
        return [row for row in self.rows if row.status == "ready" and row.selected]

    def _on_select_all_ready(self) -> None:
        ready_rows = [row for row in self.rows if row.status == "ready"]
        if not ready_rows:
            return
        clear_all = all(row.selected for row in ready_rows)
        for row in self.rows:
            if row.status == "ready":
                row.selected = not clear_all
        self._render_rows()
        self._update_download_button_state()

    def _on_invert_ready_selection(self) -> None:
        for row in self.rows:
            if row.status == "ready":
                row.selected = not row.selected
        self._render_rows()
        self._update_download_button_state()

    def _on_open_batch_settings(self) -> None:
        dialog = BatchRuntimeSettingsDialog(
            detect_timeout_sec=self.detect_timeout_sec,
            download_timeout_sec=self.download_timeout_sec,
            download_retry_count=self.download_retry_count,
            download_concurrency=self.download_concurrency,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        self.detect_timeout_sec = dialog.detect_timeout_sec
        self.download_timeout_sec = dialog.download_timeout_sec
        self.download_retry_count = dialog.download_retry_count
        self.download_concurrency = dialog.download_concurrency
        if self._downloading and not self._download_cancel_requested:
            self._dispatch_download_workers()
        self.status_label.setText(
            T.batch_runtime_settings_updated(
                self.detect_timeout_sec, self.download_timeout_sec,
                self.download_retry_count, self.download_concurrency,
            )
        )
        set_label_state(self.status_label, "success")

    def _on_detect_clicked(self) -> None:
        if self.inspect_worker and self.inspect_worker.isRunning():
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_DETECT_RUNNING)
            return
        if self._downloading:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_DOWNLOAD_RUNNING)
            return
        if not self.cookie:
            QMessageBox.warning(self, T.TITLE_NOT_LOGIN, T.MSG_NEED_LOGIN_ANY)
            return

        raw_text = self._current_input_signature()
        if not raw_text:
            QMessageBox.warning(self, T.TITLE_PARAM_ERROR, T.MSG_BATCH_NEED_INPUT)
            return
        if self.rows and raw_text == self._last_detect_signature:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_INPUT_UNCHANGED)
            return

        self.rows = []
        self._last_detect_signature = ""
        self._render_rows()
        self.batch_progress.setRange(0, 1)
        self.batch_progress.setValue(0)
        self._update_download_button_state()
        self._update_detect_button_state()
        self.status_label.setText(T.BATCH_STATUS_DETECTING)
        set_label_state(self.status_label, "warning")
        self.inspect_worker = music_fetch.workers.BatchInspectWorker(raw_text, self.cookie, timeout=self.detect_timeout_sec, detect_concurrency=self.download_concurrency)
        self.inspect_worker.progress.connect(self._on_detect_progress)
        self.inspect_worker.completed.connect(self._on_detect_completed)
        self.inspect_worker.failed.connect(self._on_detect_failed)
        self.inspect_worker.finished.connect(self._update_detect_button_state)
        self.inspect_worker.finished.connect(self._update_download_button_state)
        self.inspect_worker.start()
        self._update_detect_button_state()
        self._update_download_button_state()

    def _on_detect_progress(self, current: int, total: int, current_input: str) -> None:
        self.batch_progress.setRange(0, max(total, 1))
        self.batch_progress.setValue(min(current, total))
        self.status_label.setText(f"{T.BATCH_STATUS_DETECTING} {current}/{total} - {current_input[:80]}")
        set_label_state(self.status_label, "warning")

    def _on_detect_failed(self, code: str, message: str) -> None:
        mapped = user_error_message(code, message)
        self.status_label.setText(T.MSG_BATCH_DETECT_FAIL.format(message=T.code_message(code, mapped)))
        set_label_state(self.status_label, "error")
        self.batch_progress.setRange(0, 1)
        self.batch_progress.setValue(0)
        self._update_detect_button_state()
        self._update_download_button_state()

    def _on_detect_completed(self, rows: list[BatchDetectRow]) -> None:
        self._last_detect_signature = self._current_input_signature()
        self.rows = rows
        self._render_rows()
        self.batch_progress.setRange(0, max(len(rows), 1))
        self.batch_progress.setValue(len(rows))
        self._set_detect_summary_status()
        self._update_detect_button_state()
        self._update_download_button_state()
        QTimer.singleShot(0, self._adjust_table_columns)
        if not rows:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_DETECT_EMPTY)

    def _render_rows(self) -> None:
        self._table_syncing = True
        self.table.setRowCount(len(self.rows))
        for row_index, row in enumerate(self.rows):
            check_item = QTableWidgetItem("")
            if row.status == "ready":
                check_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                check_item.setCheckState(Qt.Checked if row.selected else Qt.Unchecked)
            else:
                check_item.setFlags(Qt.ItemIsEnabled)
                check_item.setCheckState(Qt.Unchecked)
            self.table.setItem(row_index, 0, check_item)
            source_value = row.source_label.strip() or T.batch_source_text(row.source_type)
            source_item = QTableWidgetItem(source_value)
            if row.raw_input:
                source_item.setToolTip(row.raw_input)
            self.table.setItem(row_index, 1, source_item)
            self.table.setItem(row_index, 2, QTableWidgetItem(row.song_id))
            self.table.setItem(row_index, 3, QTableWidgetItem(row.song_name))
            size_text = format_bytes(row.media_size_bytes) if row.media_size_bytes > 0 else T.MSG_UNKNOWN
            self.table.setItem(row_index, 4, QTableWidgetItem(size_text))
            status_item = QTableWidgetItem(T.batch_detect_status_text(row.status))
            if row.message:
                status_item.setToolTip(row.message)
            self.table.setItem(row_index, 5, status_item)
        self._table_syncing = False

    def _adjust_table_columns(self) -> None:
        viewport_width = self.table.viewport().width()
        if viewport_width <= 0:
            return
        col_select = 66
        col_song_id = 120
        col_size = 110
        col_status = 130
        fixed_total = col_select + col_song_id + col_size + col_status
        available = viewport_width - fixed_total - 2
        if available < 460:
            col_source = 180
            col_song_name = 280
        else:
            col_source = min(max(int(available * 0.34), 180), 360)
            col_song_name = max(280, available - col_source)
            if col_source + col_song_name < available:
                col_song_name = available - col_source
        self.table.setColumnWidth(0, col_select)
        self.table.setColumnWidth(1, col_source)
        self.table.setColumnWidth(2, col_song_id)
        self.table.setColumnWidth(3, col_song_name)
        self.table.setColumnWidth(4, col_size)
        self.table.setColumnWidth(5, col_status)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        super().resizeEvent(event)
        self._adjust_table_columns()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        QTimer.singleShot(0, self._adjust_table_columns)

    def _on_table_item_changed(self, item: QTableWidgetItem) -> None:
        if self._table_syncing:
            return
        if item.column() != 0:
            return
        row_index = item.row()
        if row_index < 0 or row_index >= len(self.rows):
            return
        row = self.rows[row_index]
        if row.status != "ready":
            return
        row.selected = item.checkState() == Qt.Checked
        self._update_download_button_state()

    def _on_download_clicked(self) -> None:
        if self.inspect_worker and self.inspect_worker.isRunning():
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_DETECT_RUNNING)
            return
        if self._downloading:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_DOWNLOAD_RUNNING)
            return
        if self._input_changed_since_detect():
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_INPUT_CHANGED)
            return

        ready_rows = self._selected_ready_rows()
        if not ready_rows:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_NEED_READY)
            return

        self._start_download_rows(ready_rows)

    def _on_retry_failed_clicked(self) -> None:
        if self.inspect_worker and self.inspect_worker.isRunning():
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_DETECT_RUNNING)
            return
        if self._downloading:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_DOWNLOAD_RUNNING)
            return
        if self._input_changed_since_detect():
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_INPUT_CHANGED)
            return
        failed_rows = retryable_failed_rows(self.rows)
        if not failed_rows:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_NEED_FAILED_RETRY)
            return
        self._start_download_rows(failed_rows)

    def _on_export_csv_clicked(self) -> None:
        if not self.rows:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_BATCH_EXPORT_EMPTY)
            return
        default_name = f"batch_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        default_path = str(Path(self.out_dir_input.text().strip() or DEFAULT_DOWNLOAD_DIR).expanduser() / default_name)
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            T.BATCH_EXPORT_CSV_TITLE,
            default_path,
            T.BATCH_EXPORT_CSV_FILTER,
        )
        if not selected:
            return
        try:
            Path(selected).expanduser().write_text(build_batch_results_csv(self.rows), encoding="utf-8-sig")
        except OSError as err:
            QMessageBox.critical(self, T.TITLE_DOWNLOAD_FAIL, T.MSG_BATCH_EXPORT_FAILED.format(message=str(err)))
            return
        QMessageBox.information(self, T.TITLE_DOWNLOAD_DONE, T.MSG_BATCH_EXPORT_DONE.format(path=selected))
        logger.info("Batch results exported. path=%s rows=%s", selected, len(self.rows))

    def _start_download_rows(self, rows: list[BatchDetectRow]) -> None:
        out_dir_raw = self.out_dir_input.text().strip()
        if not out_dir_raw:
            QMessageBox.warning(self, T.TITLE_PARAM_ERROR, T.MSG_BATCH_DOWNLOAD_NO_OUTPUT)
            return
        out_dir = Path(out_dir_raw).expanduser()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except PermissionError as err:
            QMessageBox.warning(self, T.TITLE_PARAM_ERROR, f"Cannot write to output directory: {out_dir}")
            logger.warning("Batch download output directory not writable. dir=%s", out_dir)
            return
        self._downloading = True
        self._download_cancel_requested = False
        self._download_paused = False
        self._download_queue = list(rows)
        self._download_total = len(self._download_queue)
        self._download_cursor = 0
        self._download_success = 0
        self._download_failed = 0
        self._download_canceled = 0
        self._download_next_index = 0
        self._download_workers = {}
        self._worker_rows = {}
        self._worker_output_paths = {}
        self.batch_progress.setRange(0, max(self._download_total, 1))
        self.batch_progress.setValue(0)
        self.status_label.setText(f"{T.BATCH_STATUS_DOWNLOADING}{T.batch_download_concurrency_label(self.download_concurrency)}")
        set_label_state(self.status_label, "warning")
        self.input_edit.setEnabled(False)
        self.cancel_download_button.setVisible(True)
        self.cancel_download_button.setEnabled(True)
        self.pause_download_button.setVisible(True)
        self.pause_download_button.setEnabled(True)
        self.pause_download_button.setText(T.BATCH_BTN_PAUSE)
        self._update_detect_button_state()
        self._update_download_button_state()
        self._dispatch_download_workers()

    def _dispatch_download_workers(self) -> None:
        if not self._downloading:
            return
        if self._download_cancel_requested and not self._download_workers:
            self._stop_download_flow(stopped=True)
            return

        selected_format = self.format_combo.currentText().lower().strip()
        out_dir = Path(self.out_dir_input.text().strip()).expanduser()
        started = False
        changed_rows = False
        while (
            len(self._download_workers) < self.download_concurrency
            and self._download_next_index < self._download_total
            and not self._download_cancel_requested
            and not self._download_paused
        ):
            row = self._download_queue[self._download_next_index]
            self._download_next_index += 1
            try:
                output_path = resolve_output_path(
                    out_dir=out_dir,
                    song_id=row.song_id,
                    song_name=row.song_name or None,
                    rename=None,
                    out_format=selected_format,
                )
            except MusicFetchError as err:
                row.status = "download_failed"
                row.message = T.code_message(err.code, user_error_message(err.code, err.message))
                row.selected = False
                self.history_store.add(
                    DownloadRecord(
                        song_id=row.song_id,
                        song_name=row.song_name or f"song-{row.song_id}",
                        output_path=str(out_dir / f"song-{row.song_id}.{selected_format}"),
                        size_bytes=0,
                        downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        status=TASK_STATE_FAILED,
                        error_code=err.code,
                    )
                )
                self._download_failed += 1
                self._download_cursor += 1
                self.batch_progress.setValue(self._download_cursor)
                changed_rows = True
                continue

            row.status = "downloading"
            row.message = ""
            task_id = build_task_id(row.song_id)
            worker = music_fetch.workers.DownloadWorker(
                task_id=task_id,
                song_id=row.song_id,
                output_path=output_path,
                cookie=self.cookie,
                target_format=selected_format,
                timeout=self.download_timeout_sec,
                retry_count=self.download_retry_count,
                tags={"title": row.song_name or "", "artist": None, "album": None, "cover_url": None},
            )
            key = id(worker)
            self._download_workers[key] = worker
            self._worker_rows[key] = row
            self._worker_output_paths[key] = output_path
            worker.progress.connect(functools.partial(self._on_download_progress, worker))
            worker.succeeded.connect(functools.partial(self._on_download_succeeded, worker))
            worker.failed.connect(functools.partial(self._on_download_failed, worker))
            worker.canceled.connect(functools.partial(self._on_download_canceled, worker))
            worker.finished.connect(functools.partial(self._on_download_worker_finished, worker))
            worker.start()
            started = True
            changed_rows = True

        if changed_rows:
            self._render_rows()
        self._refresh_download_status()
        if self._download_cursor >= self._download_total and not self._download_workers:
            self._stop_download_flow(stopped=self._download_cancel_requested)

    def _on_download_progress(self, worker: music_fetch.workers.DownloadWorker, downloaded: int, total: int, speed: float) -> None:
        row = self._worker_rows.get(id(worker))
        if not row:
            return
        active_count = len(self._download_workers)
        finished = self._download_cursor
        if total > 0:
            self.status_label.setText(
                T.batch_download_progress_with_song(
                    finished, self._download_total, active_count,
                    row.song_name or row.song_id,
                    f"{format_bytes(downloaded)}/{format_bytes(total)}",
                    T.speed_text(format_bytes(int(speed))),
                )
            )
        else:
            self.status_label.setText(
                T.batch_download_progress_with_song(
                    finished, self._download_total, active_count,
                    row.song_name or row.song_id,
                    format_bytes(downloaded),
                    T.speed_text(format_bytes(int(speed))),
                )
            )
        set_label_state(self.status_label, "warning")

    def _on_download_succeeded(self, worker: music_fetch.workers.DownloadWorker, output_path: str, file_size: int) -> None:
        row = self._worker_rows.get(id(worker))
        if not row:
            return
        row.status = "download_success"
        row.selected = False
        row.media_size_bytes = file_size if file_size > 0 else row.media_size_bytes
        row.message = Path(output_path).name
        self.history_store.add(
            DownloadRecord(
                song_id=row.song_id,
                song_name=row.song_name or f"song-{row.song_id}",
                output_path=output_path,
                size_bytes=file_size,
                downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=TASK_STATE_SUCCESS,
            )
        )
        self._download_success += 1
        self._finalize_download_worker(worker)

    def _on_download_failed(self, worker: music_fetch.workers.DownloadWorker, code: str, message: str) -> None:
        key = id(worker)
        row = self._worker_rows.get(key)
        output_path = self._worker_output_paths.get(key)
        if not row:
            return
        mapped = user_error_message(code, message)
        row.status = "download_failed"
        row.selected = False
        row.message = T.code_message(code, mapped)
        self.history_store.add(
            DownloadRecord(
                song_id=row.song_id,
                song_name=row.song_name or f"song-{row.song_id}",
                output_path=str(output_path) if output_path else "",
                size_bytes=0,
                downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=TASK_STATE_FAILED,
                error_code=code,
            )
        )
        self._download_failed += 1
        self._finalize_download_worker(worker)

    def _on_download_canceled(self, worker: music_fetch.workers.DownloadWorker) -> None:
        key = id(worker)
        row = self._worker_rows.get(key)
        output_path = self._worker_output_paths.get(key)
        if not row:
            return
        row.status = "download_canceled"
        row.selected = False
        row.message = T.MSG_DOWNLOAD_CANCELED
        self.history_store.add(
            DownloadRecord(
                song_id=row.song_id,
                song_name=row.song_name or f"song-{row.song_id}",
                output_path=str(output_path) if output_path else "",
                size_bytes=0,
                downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=TASK_STATE_CANCELED,
            )
        )
        self._download_canceled += 1
        self._finalize_download_worker(worker)

    def _on_download_worker_finished(self, worker: music_fetch.workers.DownloadWorker) -> None:
        # Defensive cleanup: worker may finish unexpectedly without status callbacks.
        if id(worker) not in self._download_workers:
            return
        row = self._worker_rows.get(id(worker))
        output_path = self._worker_output_paths.get(id(worker))
        if row and row.status == "downloading":
            row.status = "download_failed"
            row.selected = False
            row.message = T.MSG_BATCH_WORKER_UNEXPECTED
            self._download_failed += 1
            self.history_store.add(
                DownloadRecord(
                    song_id=row.song_id,
                    song_name=row.song_name or f"song-{row.song_id}",
                    output_path=str(output_path) if output_path else "",
                    size_bytes=0,
                    downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    status=TASK_STATE_FAILED,
                    error_code=UNKNOWN_ERROR,
                )
            )
        self._finalize_download_worker(worker)

    def _finalize_download_worker(self, worker: music_fetch.workers.DownloadWorker) -> None:
        key = id(worker)
        if key not in self._download_workers:
            return
        self._download_workers.pop(key, None)
        self._worker_rows.pop(key, None)
        self._worker_output_paths.pop(key, None)
        self._download_cursor += 1
        self.batch_progress.setValue(self._download_cursor)
        self._render_rows()
        self._refresh_download_status()
        if self._download_cancel_requested:
            if not self._download_workers:
                self._stop_download_flow(stopped=True)
            return
        self._dispatch_download_workers()

    def _refresh_download_status(self) -> None:
        if not self._downloading:
            return
        active_count = len(self._download_workers)
        self.status_label.setText(
            f"{T.BATCH_STATUS_DOWNLOADING} {T.batch_download_active_status(self._download_cursor, self._download_total, active_count)}"
        )
        set_label_state(self.status_label, "warning")

    def _on_pause_download_clicked(self) -> None:
        if self._download_paused:
            # Resume all
            self._download_paused = False
            self.pause_download_button.setText(T.BATCH_BTN_PAUSE)
            self.status_label.setText(f"{T.BATCH_STATUS_DOWNLOADING}{T.batch_download_concurrency_label(self.download_concurrency)}")
            set_label_state(self.status_label, "warning")
            for worker in list(self._download_workers.values()):
                worker.request_resume()
            self._dispatch_download_workers()
            logger.info("Batch download resumed. remaining=%s", self._download_total - self._download_cursor)
        else:
            # Pause all
            self._download_paused = True
            self.pause_download_button.setText(T.BATCH_BTN_RESUME)
            self.status_label.setText(T.BATCH_STATUS_DOWNLOAD_PAUSED)
            set_label_state(self.status_label, "muted")
            for worker in list(self._download_workers.values()):
                worker.request_pause()
            logger.info("Batch download paused. cursor=%s/%s", self._download_cursor, self._download_total)

    def _on_cancel_download_clicked(self) -> None:
        if not self._downloading:
            return
        self._download_cancel_requested = True
        self.cancel_download_button.setEnabled(False)
        self.status_label.setText(T.BATCH_STATUS_CANCELING)
        set_label_state(self.status_label, "warning")
        if self._download_workers:
            for worker in list(self._download_workers.values()):
                worker.request_cancel()
        else:
            self._stop_download_flow(stopped=True)

    def _stop_download_flow(self, stopped: bool) -> None:
        processed = self._download_cursor
        total = self._download_total
        pending = max(total - processed, 0)
        # Clean up .part files from paused or canceled workers
        for output_path in self._worker_output_paths.values():
            part_path = output_path.with_name(f"{output_path.name}.part")
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            source_path = output_path.with_name(f"{output_path.name}.source")
            if source_path.exists():
                source_path.unlink(missing_ok=True)
        self._downloading = False
        self._download_cancel_requested = False
        self._download_paused = False
        self._download_workers = {}
        self._worker_rows = {}
        self._worker_output_paths = {}
        self._download_queue = []
        self._download_next_index = 0
        self.input_edit.setEnabled(True)
        self.cancel_download_button.setVisible(False)
        self.pause_download_button.setVisible(False)
        self.cancel_download_button.setEnabled(False)
        if stopped:
            stopped_text = T.BATCH_DOWNLOAD_STOPPED.format(
                processed=processed,
                total=total,
                success=self._download_success,
                failed=self._download_failed,
                canceled=self._download_canceled,
                pending=pending,
            )
            reasons = self._failure_reason_summary()
            if reasons:
                stopped_text = f"{stopped_text} {T.BATCH_FAILURE_REASON_SUMMARY.format(reasons=reasons)}"
            self.status_label.setText(stopped_text)
            set_label_state(self.status_label, "warning")
        else:
            self.status_label.setText(self._download_summary_text())
            set_label_state(self.status_label, "success" if self._download_failed == 0 else "warning")
        self._update_detect_button_state()
        self._update_download_button_state()

    def _set_detect_summary_status(self) -> None:
        summary = summarize_batch_rows(self.rows)
        self.status_label.setText(
            T.BATCH_STATUS_SUMMARY.format(
                total=summary.total,
                ready=summary.ready,
                duplicate=summary.duplicate,
                bad=summary.bad,
            )
        )
        set_label_state(self.status_label, "success" if summary.ready else "warning")

    def _download_summary_text(self) -> str:
        summary = T.BATCH_DOWNLOAD_SUMMARY.format(
            success=self._download_success,
            failed=self._download_failed,
            canceled=self._download_canceled,
        )
        reasons = self._failure_reason_summary()
        if reasons:
            return f"{summary} {T.BATCH_FAILURE_REASON_SUMMARY.format(reasons=reasons)}"
        return summary

    def _failure_reason_summary(self) -> str:
        failure_reasons = summarize_batch_rows(self.rows).failure_reasons
        if not failure_reasons:
            return ""
        parts = [f"{reason} x{count}" for reason, count in sorted(failure_reasons.items())]
        return "；".join(parts)
