#!/usr/bin/env python3
"""
Download progress dialog — single-song download with progress bar, pause/resume,
and cancel support.

Extracted from music_fetch.dialogs.py to reduce module size.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from music_fetch.app_logging import get_logger
from music_fetch.app_settings import (
    MAX_DOWNLOAD_RETRY_COUNT,
    MAX_DOWNLOAD_TIMEOUT_SEC,
    MIN_DOWNLOAD_RETRY_COUNT,
    MIN_DOWNLOAD_TIMEOUT_SEC,
)
from music_fetch.download_tasks import (
    TASK_STATE_CANCELED,
    TASK_STATE_DOWNLOADING,
    TASK_STATE_FAILED,
    TASK_STATE_PENDING,
    TASK_STATE_SUCCESS,
)
from music_fetch.error_texts import user_error_message
from music_fetch.batch_models import format_bytes
from music_fetch.gui_styles import set_secondary_button
import music_fetch.workers
import music_fetch.ui_texts as T

try:
    from PySide6.QtWidgets import (
        QDialog,
        QHBoxLayout,
        QLabel,
        QMessageBox,
        QProgressBar,
        QPushButton,
        QVBoxLayout,
    )
except ImportError as err:
    raise SystemExit(
        "Missing dependency: PySide6. Install it with `python3 -m pip install PySide6` before running main.py."
    ) from err

logger = get_logger("music_fetch.gui")



__all__ = ['DownloadProgressDialog']
class DownloadProgressDialog(QDialog):
    def __init__(
        self,
        task_id: str,
        song_id: str,
        output_path: Path,
        cookie: str,
        target_format: str,
        timeout: int,
        retry_count: int,
        notify_each_result: bool = True,
    ) -> None:
        super().__init__()
        self.task_id = task_id
        self.setWindowTitle(T.DOWNLOAD_PROGRESS_TITLE)
        self.resize(540, 190)
        self.output_path: Optional[Path] = None
        self.requested_output_path = output_path
        self.timeout = max(MIN_DOWNLOAD_TIMEOUT_SEC, min(MAX_DOWNLOAD_TIMEOUT_SEC, int(timeout)))
        self.retry_count = max(MIN_DOWNLOAD_RETRY_COUNT, min(MAX_DOWNLOAD_RETRY_COUNT, int(retry_count)))
        self.notify_each_result = notify_each_result
        # v0.4.0: expose explicit task state to main workflow for unified status tracking.
        self.result_state = TASK_STATE_PENDING
        self.error_code = ""
        self._pause_button_is_pause = True

        layout = QVBoxLayout(self)
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.status_label = QLabel(T.DOWNLOAD_PROGRESS_INIT)
        self.speed_label = QLabel(T.DOWNLOAD_PROGRESS_SPEED)
        self.path_label = QLabel(str(output_path))
        self.path_label.setWordWrap(True)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.status_label)
        layout.addWidget(self.speed_label)
        layout.addWidget(QLabel(T.DOWNLOAD_PROGRESS_PATH))
        layout.addWidget(self.path_label)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        self.pause_button = QPushButton(T.DOWNLOAD_PROGRESS_PAUSE)
        set_secondary_button(self.pause_button)
        self.pause_button.clicked.connect(self._on_pause_resume)
        button_row.addWidget(self.pause_button)
        self.cancel_button = QPushButton(T.DOWNLOAD_PROGRESS_CANCEL)
        set_secondary_button(self.cancel_button)
        self.cancel_button.clicked.connect(self._on_cancel)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        self.worker = music_fetch.workers.DownloadWorker(
            task_id=task_id,
            song_id=song_id,
            output_path=output_path,
            cookie=cookie,
            target_format=target_format,
            timeout=self.timeout,
            retry_count=self.retry_count,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.failed.connect(self._on_failed)
        self.worker.canceled.connect(self._on_canceled)
        self.worker.succeeded.connect(self._on_succeeded)
        self.worker.paused.connect(self._on_paused)
        self.worker.start()
        self.result_state = TASK_STATE_DOWNLOADING
        logger.info(
            "Download progress dialog opened. task_id=%s song_id=%s timeout=%ss retry_count=%s",
            self.task_id,
            song_id,
            self.timeout,
            self.retry_count,
        )

    def _on_pause_resume(self) -> None:
        if self._pause_button_is_pause:
            self.pause_button.setText(T.DOWNLOAD_PROGRESS_RESUME)
            self.status_label.setText(T.DOWNLOAD_PROGRESS_PAUSED)
            self.worker.request_pause()
            self._pause_button_is_pause = False
            logger.info("Download pause requested. task_id=%s", self.task_id)
        else:
            self.pause_button.setText(T.DOWNLOAD_PROGRESS_PAUSE)
            self.status_label.setText(T.DOWNLOAD_PROGRESS_RESUMING)
            self.worker.request_resume()
            self._pause_button_is_pause = True
            logger.info("Download resume requested. task_id=%s", self.task_id)

    def _on_paused(self) -> None:
        self.result_state = TASK_STATE_CANCELED  # treated as non-success exit
        logger.info("Download progress paused. task_id=%s", self.task_id)

    def _on_cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.pause_button.setEnabled(False)
        self.status_label.setText(T.STATUS_CANCELING)
        self.result_state = TASK_STATE_CANCELED
        self.worker.request_cancel()
        logger.info("Download cancel requested. task_id=%s", self.task_id)

    def _on_progress(self, downloaded: int, total: int, speed: float) -> None:
        if total <= 0:
            self.progress_bar.setRange(0, 0)
            self.status_label.setText(T.DOWNLOAD_PROGRESS_TEXT_SIMPLE.format(downloaded=format_bytes(downloaded)))
        else:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(downloaded, total))
            self.status_label.setText(
                T.DOWNLOAD_PROGRESS_TEXT_FULL.format(downloaded=format_bytes(downloaded), total=format_bytes(total))
            )
        self.speed_label.setText(T.speed_text(format_bytes(int(speed))))

    def _on_failed(self, code: str, message: str) -> None:
        self.result_state = TASK_STATE_FAILED
        self.error_code = code
        logger.warning("Download progress failed. task_id=%s code=%s", self.task_id, code)
        mapped = user_error_message(code, message)
        if self.notify_each_result:
            QMessageBox.critical(self, T.TITLE_DOWNLOAD_FAIL, T.code_message(code, mapped))
        self.reject()

    def _on_canceled(self) -> None:
        self.result_state = TASK_STATE_CANCELED
        logger.info("Download progress canceled. task_id=%s", self.task_id)
        if self.notify_each_result:
            QMessageBox.information(self, T.TITLE_DOWNLOAD_CANCELED, T.MSG_DOWNLOAD_CANCELED)
        self.reject()

    def _on_succeeded(self, output_path: str, file_size: int) -> None:
        self.result_state = TASK_STATE_SUCCESS
        self.output_path = Path(output_path)
        logger.info("Download progress succeeded. task_id=%s output=%s size=%s", self.task_id, self.output_path, file_size)
        fallback_note = ""
        if self.output_path.suffix.lower() != self.requested_output_path.suffix.lower():
            fallback_note = T.DOWNLOAD_PROGRESS_DONE_FALLBACK_NOTE
        if self.notify_each_result:
            QMessageBox.information(
                self,
                T.TITLE_DOWNLOAD_DONE,
                T.DOWNLOAD_PROGRESS_DONE_BODY.format(
                    name=self.output_path.name,
                    size=format_bytes(file_size),
                    path=self.output_path,
                )
                + fallback_note,
            )
        self.accept()


