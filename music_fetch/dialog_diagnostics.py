#!/usr/bin/env python3
"""GUI diagnostics center with safe log export and asynchronous probes."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional, Sequence

from music_fetch.app_logging import get_logger
from music_fetch.app_settings import APP_VERSION
from music_fetch.diagnostics import (
    DEFAULT_PROBE_TARGETS,
    DiagnosticContext,
    EndpointProbe,
    build_diagnostic_report,
    read_log_tail,
    redact_diagnostic_text,
    run_network_diagnostics,
)
from music_fetch.download_tasks import DownloadTaskSnapshot
from music_fetch.gui_styles import set_back_button, set_label_state, set_secondary_button
import music_fetch.ui_texts as T

try:
    from PySide6.QtCore import QThread, Qt, QUrl, Signal
    from PySide6.QtGui import QCloseEvent, QDesktopServices
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QDialog,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QMessageBox,
        QPlainTextEdit,
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


class DiagnosticsWorker(QThread):
    completed = Signal(object)

    def __init__(self, timeout: int = 5, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.timeout = timeout

    def run(self) -> None:
        self.completed.emit(run_network_diagnostics(timeout=self.timeout))


class DiagnosticsDialog(QDialog):
    def __init__(
        self,
        *,
        log_path: Path,
        cookie: str,
        proxy_type: str,
        proxy_host: str,
        proxy_port: int,
        proxy_username: str,
        proxy_password: str,
        ffmpeg_available: bool,
        latest_task: Optional[DownloadTaskSnapshot] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.log_path = log_path.expanduser()
        self._sensitive_values = tuple(
            value for value in (cookie, proxy_password) if value
        )
        self.context = DiagnosticContext(
            app_version=APP_VERSION,
            log_path=self.log_path,
            login_configured="MUSIC_U=" in cookie,
            proxy_type=(proxy_type or "").strip().lower(),
            proxy_host=(proxy_host or "").strip(),
            proxy_port=int(proxy_port or 0),
            proxy_authenticated=bool((proxy_username or "").strip()),
            ffmpeg_available=bool(ffmpeg_available),
            latest_task_state=latest_task.state if latest_task else "",
            latest_error_code=latest_task.error_code if latest_task else "",
            latest_song_id=latest_task.song_id if latest_task else "",
        )
        self.probes: tuple[EndpointProbe, ...] = ()
        self._network_worker: Optional[DiagnosticsWorker] = None
        self._log_tail = ""
        self.setWindowTitle(T.DIAGNOSTICS_TITLE)
        self.resize(820, 700)

        layout = QVBoxLayout(self)
        description = QLabel(T.DIAGNOSTICS_DESC)
        description.setWordWrap(True)
        set_label_state(description, "muted")
        layout.addWidget(description)

        overview_title = QLabel(T.DIAGNOSTICS_OVERVIEW_GROUP)
        set_label_state(overview_title, "muted")
        layout.addWidget(overview_title)
        overview = QFormLayout()
        overview.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        overview.addRow(T.DIAGNOSTICS_VERSION, QLabel(self.context.app_version))
        login_text = T.DIAGNOSTICS_LOGIN_READY if self.context.login_configured else T.DIAGNOSTICS_LOGIN_MISSING
        overview.addRow(T.DIAGNOSTICS_LOGIN, QLabel(login_text))
        overview.addRow(
            T.DIAGNOSTICS_PROXY,
            QLabel(
                T.proxy_settings_summary(
                    self.context.proxy_type,
                    self.context.proxy_host,
                    self.context.proxy_port,
                    self.context.proxy_authenticated,
                ).removeprefix("网络：")
            ),
        )
        overview.addRow(
            T.DIAGNOSTICS_FFMPEG,
            QLabel(T.DIAGNOSTICS_AVAILABLE if self.context.ffmpeg_available else T.DIAGNOSTICS_UNAVAILABLE),
        )
        task_text = T.DIAGNOSTICS_NO_TASK
        if latest_task:
            task_text = f"{T.manager_status_text(latest_task.state)} · {latest_task.error_code or latest_task.song_id}"
        overview.addRow(T.DIAGNOSTICS_LATEST_TASK, QLabel(task_text))
        layout.addLayout(overview)

        network_row = QHBoxLayout()
        network_title = QLabel(T.DIAGNOSTICS_NETWORK_GROUP)
        set_label_state(network_title, "muted")
        network_row.addWidget(network_title)
        network_row.addStretch(1)
        self.run_network_button = QPushButton(T.DIAGNOSTICS_BTN_RUN)
        set_secondary_button(self.run_network_button)
        self.run_network_button.clicked.connect(self._run_network_check)
        network_row.addWidget(self.run_network_button)
        layout.addLayout(network_row)

        self.network_table = QTableWidget(len(DEFAULT_PROBE_TARGETS), 3)
        self.network_table.setHorizontalHeaderLabels(
            [
                T.DIAGNOSTICS_NETWORK_TARGET,
                T.DIAGNOSTICS_NETWORK_STATUS,
                T.DIAGNOSTICS_NETWORK_DETAIL,
            ]
        )
        self.network_table.verticalHeader().setVisible(False)
        self.network_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        network_header = self.network_table.horizontalHeader()
        network_header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        network_header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        network_header.setSectionResizeMode(2, QHeaderView.Stretch)
        for row, (name, _url) in enumerate(DEFAULT_PROBE_TARGETS):
            self.network_table.setItem(row, 0, QTableWidgetItem(name))
            self.network_table.setItem(row, 1, QTableWidgetItem(T.DIAGNOSTICS_NOT_CHECKED))
            self.network_table.setItem(row, 2, QTableWidgetItem("-"))
        self.network_table.setMaximumHeight(130)
        layout.addWidget(self.network_table)

        log_title = QLabel(T.DIAGNOSTICS_LOG_GROUP)
        set_label_state(log_title, "muted")
        layout.addWidget(log_title)
        self.log_preview = QPlainTextEdit()
        self.log_preview.setReadOnly(True)
        self.log_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.log_preview, stretch=1)

        button_row = QHBoxLayout()
        refresh_button = QPushButton(T.DIAGNOSTICS_BTN_REFRESH_LOG)
        set_secondary_button(refresh_button)
        refresh_button.clicked.connect(self._refresh_log)
        button_row.addWidget(refresh_button)
        open_folder_button = QPushButton(T.DIAGNOSTICS_BTN_OPEN_LOG_DIR)
        set_secondary_button(open_folder_button)
        open_folder_button.clicked.connect(self._open_log_folder)
        button_row.addWidget(open_folder_button)
        export_button = QPushButton(T.DIAGNOSTICS_BTN_EXPORT)
        export_button.clicked.connect(self._export_report)
        button_row.addWidget(export_button)
        button_row.addStretch(1)
        close_button = QPushButton(T.BTN_BACK)
        set_back_button(close_button)
        close_button.clicked.connect(self.reject)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self._refresh_log()

    def _refresh_log(self, *_args: object) -> None:
        raw_tail = read_log_tail(self.log_path)
        self._log_tail = redact_diagnostic_text(raw_tail, self._sensitive_values)
        warning_lines = [
            line
            for line in self._log_tail.splitlines()
            if any(level in line for level in (" WARNING ", " ERROR ", " CRITICAL "))
        ]
        self.log_preview.setPlainText("\n".join(warning_lines) or T.DIAGNOSTICS_LOG_EMPTY)

    def _run_network_check(self, *_args: object) -> None:
        if self._network_worker is not None and self._network_worker.isRunning():
            return
        self.run_network_button.setEnabled(False)
        self.run_network_button.setText(T.DIAGNOSTICS_BTN_RUNNING)
        for row in range(self.network_table.rowCount()):
            self.network_table.setItem(row, 1, QTableWidgetItem(T.DIAGNOSTICS_CHECKING))
            self.network_table.setItem(row, 2, QTableWidgetItem("-"))
        worker = DiagnosticsWorker(parent=self)
        worker.completed.connect(self._apply_probe_results)
        worker.finished.connect(self._on_network_worker_finished)
        worker.finished.connect(worker.deleteLater)
        self._network_worker = worker
        worker.start()

    def _apply_probe_results(self, results: object) -> None:
        probes = tuple(
            result for result in results if isinstance(result, EndpointProbe)
        ) if isinstance(results, Sequence) else ()
        self.probes = probes
        for row, probe in enumerate(probes[:self.network_table.rowCount()]):
            status_text = T.DIAGNOSTICS_REACHABLE if probe.reachable else T.DIAGNOSTICS_UNREACHABLE
            self.network_table.setItem(row, 0, QTableWidgetItem(probe.name))
            self.network_table.setItem(row, 1, QTableWidgetItem(status_text))
            self.network_table.setItem(row, 2, QTableWidgetItem(probe.detail or "-"))
        self.run_network_button.setEnabled(True)
        self.run_network_button.setText(T.DIAGNOSTICS_BTN_RUN)

    def _on_network_worker_finished(self) -> None:
        self._network_worker = None

    def _current_report(self) -> str:
        return build_diagnostic_report(
            self.context,
            probes=self.probes,
            log_tail=self._log_tail,
            sensitive_values=self._sensitive_values,
        )

    def _export_report(self, *_args: object) -> None:
        default_name = f"music-fetch-diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            T.DIAGNOSTICS_EXPORT_TITLE,
            str(Path.home() / default_name),
            T.DIAGNOSTICS_EXPORT_FILTER,
        )
        if not selected:
            return
        try:
            Path(selected).expanduser().write_text(self._current_report(), encoding="utf-8")
        except OSError as err:
            QMessageBox.critical(self, T.TITLE_DOWNLOAD_FAIL, T.DIAGNOSTICS_EXPORT_FAILED.format(message=str(err)))
            return
        QMessageBox.information(self, T.DIAGNOSTICS_TITLE, T.DIAGNOSTICS_EXPORT_DONE.format(path=selected))
        logger.info("Diagnostic report exported. path=%s", selected)

    def _open_log_folder(self, *_args: object) -> None:
        folder = self.log_path.parent
        if not folder.exists():
            QMessageBox.warning(self, T.TITLE_PATH_MISSING, T.DIAGNOSTICS_LOG_DIR_MISSING.format(path=folder))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _network_check_running(self) -> bool:
        return self._network_worker is not None and self._network_worker.isRunning()

    def reject(self) -> None:
        if self._network_check_running():
            QMessageBox.information(self, T.DIAGNOSTICS_TITLE, T.DIAGNOSTICS_WAIT_FOR_CHECK)
            return
        super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._network_check_running():
            event.ignore()
            QMessageBox.information(self, T.DIAGNOSTICS_TITLE, T.DIAGNOSTICS_WAIT_FOR_CHECK)
            return
        event.accept()


__all__ = ["DiagnosticsDialog", "DiagnosticsWorker"]
