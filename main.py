#!/usr/bin/env python3
"""PySide6 GUI app for NetEase Cloud Music single-track download workflow."""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib import error, request

from app_logging import default_log_path, get_logger, setup_logging
from error_texts import user_error_message
from app_settings import (
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_GUI_TARGET_FORMAT,
    DOWNLOAD_HISTORY_FILE,
    SESSION_FILE,
    URL_EXAMPLE_LONG,
)
from app_stores import AppSession, DownloadHistoryStore, DownloadRecord, SessionStore
from music_fetch import (
    AccountProfile,
    MusicFetchError,
    SongDetectionResult,
    SUPPORTED_GUI_AUDIO_FORMATS,
    build_cookie_string,
    check_login_status,
    convert_audio_file,
    detect_song,
    download_song_with_fallback,
    fetch_account_profile,
    infer_audio_format_from_url,
    resolve_output_path,
    sanitize_filename,
)
import ui_texts as T

try:
    from PySide6.QtCore import QSize, QThread, Qt, QUrl, Signal
    from PySide6.QtGui import QAction, QDesktopServices, QIcon, QPixmap
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QHeaderView,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMenu,
        QMessageBox,
        QPushButton,
        QProgressBar,
        QTableWidget,
        QTableWidgetItem,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as err:
    raise SystemExit(
        "Missing dependency: PySide6. Install it with `pip install PySide6` before running main.py."
    ) from err

try:
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView

    WEB_ENGINE_AVAILABLE = True
except ImportError:
    WEB_ENGINE_AVAILABLE = False

logger = get_logger("music_fetch.gui")


def format_duration(duration_ms: Optional[int]) -> str:
    if duration_ms is None:
        return T.MSG_UNKNOWN
    seconds = max(int(duration_ms / 1000), 0)
    mins, secs = divmod(seconds, 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


def format_bytes(value: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    size = float(max(value, 0))
    for unit in units:
        if size < 1024 or unit == units[-1]:
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{value}B"


def load_avatar_icon(url: str) -> Optional[QIcon]:
    if not url:
        return None
    req = request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
    try:
        with request.urlopen(req, timeout=10) as resp:
            image_bytes = resp.read()
    except (error.URLError, error.HTTPError):
        logger.warning("Failed to load avatar image. url=%s", url)
        return None

    pixmap = QPixmap()
    if not pixmap.loadFromData(image_bytes):
        return None
    return QIcon(pixmap)


class InspectWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, song_url: str, cookie: str, timeout: int = 20) -> None:
        super().__init__()
        self.song_url = song_url
        self.cookie = cookie
        self.timeout = timeout

    def run(self) -> None:
        try:
            logger.info("InspectWorker started.")
            result = detect_song(self.song_url, self.cookie, timeout=self.timeout)
            self.succeeded.emit(result)
            logger.info("InspectWorker succeeded. song_id=%s can_download=%s", result.song_id, result.can_download)
        except MusicFetchError as err:
            logger.warning("InspectWorker failed. code=%s message=%s", err.code, err.message)
            self.failed.emit(err.code, err.message)
        except Exception as err:  # pragma: no cover
            logger.exception("InspectWorker unexpected error.")
            self.failed.emit("UNKNOWN_ERROR", str(err))


class DownloadWorker(QThread):
    progress = Signal(int, int, float)
    succeeded = Signal(str, int)
    failed = Signal(str, str)
    canceled = Signal()

    def __init__(
        self,
        song_id: str,
        output_path: Path,
        cookie: str,
        target_format: str = DEFAULT_GUI_TARGET_FORMAT,
        timeout: int = 30,
    ) -> None:
        super().__init__()
        self.song_id = song_id
        self.output_path = output_path
        self.cookie = cookie
        self.target_format = target_format.lower().strip()
        self.timeout = timeout
        self._cancel_requested = False

    def request_cancel(self) -> None:
        self._cancel_requested = True

    def run(self) -> None:
        started_at = time.time()
        logger.info("DownloadWorker started. output=%s", self.output_path)

        def on_progress(downloaded: int, total: Optional[int]) -> None:
            elapsed = max(time.time() - started_at, 0.001)
            speed = downloaded / elapsed
            self.progress.emit(downloaded, total if total is not None else -1, speed)

        def should_cancel() -> bool:
            return self._cancel_requested

        try:
            temp_source_path = self.output_path.with_name(f"{self.output_path.name}.source")
            if temp_source_path.exists():
                temp_source_path.unlink(missing_ok=True)

            selected = download_song_with_fallback(
                song_id=self.song_id,
                cookie=self.cookie,
                output_path=temp_source_path,
                timeout=self.timeout,
                progress_callback=on_progress,
                cancel_checker=should_cancel,
            )
            source_format = infer_audio_format_from_url(selected.media_url) or "unknown"
            logger.info(
                "Download source completed. source_format=%s target_format=%s",
                source_format,
                self.target_format,
            )
            if source_format == self.target_format:
                temp_source_path.replace(self.output_path)
            else:
                convert_audio_file(
                    temp_source_path,
                    self.output_path,
                    self.target_format,
                    timeout=max(240, self.timeout * 8),
                )
                temp_source_path.unlink(missing_ok=True)

            if self._cancel_requested:
                self.canceled.emit()
                return
            file_size = self.output_path.stat().st_size if self.output_path.exists() else 0
            self.succeeded.emit(str(self.output_path.resolve()), file_size)
            logger.info("DownloadWorker succeeded. output=%s size=%s", self.output_path, file_size)
        except MusicFetchError as err:
            if err.code == "DOWNLOAD_CANCELED":
                logger.info("DownloadWorker canceled by user. output=%s", self.output_path)
                self.canceled.emit()
                return
            logger.warning("DownloadWorker failed. code=%s message=%s", err.code, err.message)
            self.failed.emit(err.code, err.message)
        except Exception as err:  # pragma: no cover
            logger.exception("DownloadWorker unexpected error.")
            self.failed.emit("UNKNOWN_ERROR", str(err))
        finally:
            stale_source = self.output_path.with_name(f"{self.output_path.name}.source")
            if stale_source.exists():
                stale_source.unlink(missing_ok=True)


class LoginDialog(QDialog):
    login_success = Signal(str, bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(T.LOGIN_DIALOG_TITLE)
        self.resize(900, 700)
        self.cookie_fields: dict[str, str] = {}

        root_layout = QVBoxLayout(self)
        info = QLabel(T.LOGIN_INFO)
        info.setWordWrap(True)
        root_layout.addWidget(info)

        self.remember_checkbox = QCheckBox(T.LOGIN_REMEMBER)
        self.remember_checkbox.setChecked(True)
        root_layout.addWidget(self.remember_checkbox)

        if WEB_ENGINE_AVAILABLE:
            self.web_group = self._build_web_login_group()
            root_layout.addWidget(self.web_group, stretch=1)
        else:
            fallback_hint = QLabel(T.LOGIN_FALLBACK_HINT)
            fallback_hint.setWordWrap(True)
            root_layout.addWidget(fallback_hint)

        self.manual_group = self._build_manual_group()
        root_layout.addWidget(self.manual_group)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.confirm_button = QPushButton(T.LOGIN_BTN_CONFIRM)
        self.confirm_button.clicked.connect(self._on_confirm)
        cancel_button = QPushButton(T.BTN_CANCEL)
        cancel_button.clicked.connect(self.reject)
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.confirm_button)
        root_layout.addLayout(buttons)

    def _build_web_login_group(self) -> QGroupBox:
        group = QGroupBox(T.LOGIN_WEB_GROUP)
        layout = QVBoxLayout(group)

        self.web_profile = QWebEngineProfile("music-fetch-login", group)
        self.web_page = QWebEnginePage(self.web_profile, group)
        self.web_view = QWebEngineView(group)
        self.web_view.setPage(self.web_page)
        self.web_view.setUrl(QUrl("https://music.163.com/#/login"))
        self.web_profile.cookieStore().cookieAdded.connect(self._on_cookie_added)

        tip = QLabel(T.LOGIN_WEB_HINT)
        tip.setWordWrap(True)
        layout.addWidget(tip)
        layout.addWidget(self.web_view, stretch=1)
        return group

    def _build_manual_group(self) -> QGroupBox:
        group = QGroupBox(T.LOGIN_MANUAL_GROUP)
        form = QFormLayout(group)
        self.music_u_input = QLineEdit()
        self.music_u_input.setEchoMode(QLineEdit.Password)
        self.csrf_input = QLineEdit()
        self.csrf_input.setEchoMode(QLineEdit.Password)
        self.csrf_input.setPlaceholderText(T.MSG_OPTIONAL_RECOMMENDED)
        form.addRow("MUSIC_U", self.music_u_input)
        form.addRow("__csrf", self.csrf_input)
        return group

    def _on_cookie_added(self, cookie) -> None:
        try:
            name = bytes(cookie.name()).decode("utf-8", errors="ignore")
            value = bytes(cookie.value()).decode("utf-8", errors="ignore")
        except Exception:
            return
        if name in {"MUSIC_U", "__csrf"} and value:
            self.cookie_fields[name] = value

    def _on_confirm(self) -> None:
        if self.cookie_fields.get("MUSIC_U"):
            cookie = build_cookie_string(
                self.cookie_fields.get("MUSIC_U", ""),
                self.cookie_fields.get("__csrf", ""),
            )
        else:
            cookie = build_cookie_string(self.music_u_input.text(), self.csrf_input.text())

        if not cookie or "MUSIC_U=" not in cookie:
            QMessageBox.warning(self, T.TITLE_LOGIN_FAIL, T.MSG_LOGIN_COOKIE_MISSING)
            return

        try:
            is_valid = check_login_status(cookie, timeout=10)
        except MusicFetchError as err:
            logger.warning("Login status online check failed. code=%s message=%s", err.code, err.message)
            mapped = user_error_message(err.code, err.message)
            answer = QMessageBox.question(
                self,
                T.TITLE_NETWORK_CHECK_FAIL,
                f"{T.login_network_confirm(err.code)}\n{mapped}",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            is_valid = True

        if not is_valid:
            QMessageBox.warning(self, T.TITLE_LOGIN_INVALID, T.MSG_LOGIN_INVALID)
            return

        self.login_success.emit(cookie, self.remember_checkbox.isChecked())
        logger.info("LoginDialog confirmed success. remember_login=%s", self.remember_checkbox.isChecked())
        self.accept()


class SongConfirmDialog(QDialog):
    def __init__(self, result: SongDetectionResult) -> None:
        super().__init__()
        self.result = result
        self.setWindowTitle(T.SONG_CONFIRM_TITLE)
        self.resize(540, 280)

        layout = QVBoxLayout(self)
        grid = QGridLayout()
        grid.addWidget(QLabel(T.SONG_CONFIRM_ID), 0, 0)
        grid.addWidget(QLabel(result.song_id), 0, 1)
        grid.addWidget(QLabel(T.SONG_CONFIRM_NAME), 1, 0)
        grid.addWidget(QLabel(result.song_name or T.MSG_UNKNOWN), 1, 1)
        grid.addWidget(QLabel(T.SONG_CONFIRM_DURATION), 2, 0)
        grid.addWidget(QLabel(format_duration(result.duration_ms)), 2, 1)
        status = T.SONG_CONFIRM_CAN_DOWNLOAD if result.can_download else T.SONG_CONFIRM_CANT_DOWNLOAD
        status_label = QLabel(status)
        status_label.setStyleSheet("color: #1f7a1f;" if result.can_download else "color: #a32929;")
        grid.addWidget(QLabel(T.SONG_CONFIRM_STATUS), 3, 0)
        grid.addWidget(status_label, 3, 1)
        if result.unavailable_reason:
            reason = QLabel(result.unavailable_reason)
            reason.setWordWrap(True)
            grid.addWidget(QLabel(T.SONG_CONFIRM_REASON), 4, 0)
            grid.addWidget(reason, 4, 1)
        layout.addLayout(grid)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        close_button = QPushButton(T.BTN_CLOSE)
        close_button.clicked.connect(self.reject)
        self.download_button = QPushButton(T.BTN_DOWNLOAD)
        self.download_button.setEnabled(result.can_download)
        self.download_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        button_row.addWidget(self.download_button)
        layout.addLayout(button_row)


class DownloadOptionsDialog(QDialog):
    def __init__(self, result: SongDetectionResult, last_download_dir: str) -> None:
        super().__init__()
        self.result = result
        self.output_path: Optional[Path] = None
        self.selected_format: str = DEFAULT_GUI_TARGET_FORMAT
        self.setWindowTitle(T.DOWNLOAD_OPTIONS_TITLE)
        self.resize(640, 240)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.out_dir_input = QLineEdit(last_download_dir or DEFAULT_DOWNLOAD_DIR)
        browse_button = QPushButton(T.DOWNLOAD_DIR_PICKER_BTN)
        browse_button.clicked.connect(self._pick_directory)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.out_dir_input)
        dir_row.addWidget(browse_button)
        dir_widget = QWidget()
        dir_widget.setLayout(dir_row)

        default_name = sanitize_filename(
            f"{result.song_name}-{result.song_id}" if result.song_name else f"song-{result.song_id}"
        )
        self.rename_input = QLineEdit(default_name)
        self.format_combo = QComboBox()
        self.format_combo.addItems([fmt.upper() for fmt in SUPPORTED_GUI_AUDIO_FORMATS])
        self.format_combo.setCurrentText(DEFAULT_GUI_TARGET_FORMAT.upper())
        form.addRow(T.DOWNLOAD_OPTIONS_DIR, dir_widget)
        form.addRow(T.DOWNLOAD_OPTIONS_NAME, self.rename_input)
        form.addRow(T.DOWNLOAD_OPTIONS_FORMAT, self.format_combo)
        layout.addLayout(form)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        self._refresh_preview()
        self.out_dir_input.textChanged.connect(self._refresh_preview)
        self.rename_input.textChanged.connect(self._refresh_preview)
        self.format_combo.currentTextChanged.connect(self._refresh_preview)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton(T.BTN_CANCEL)
        cancel_button.clicked.connect(self.reject)
        ok_button = QPushButton(T.BTN_START_DOWNLOAD)
        ok_button.clicked.connect(self._on_confirm)
        button_row.addWidget(cancel_button)
        button_row.addWidget(ok_button)
        layout.addLayout(button_row)

    def _pick_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, T.DOWNLOAD_DIR_PICKER_TITLE, self.out_dir_input.text().strip())
        if selected:
            self.out_dir_input.setText(selected)

    def _refresh_preview(self) -> None:
        out_dir = Path(self.out_dir_input.text().strip() or ".").expanduser()
        rename = self.rename_input.text().strip() or f"song-{self.result.song_id}"
        selected_format = self.format_combo.currentText().lower().strip() or "mp3"
        preview = out_dir / f"{sanitize_filename(rename)}.{selected_format}"
        self.preview_label.setText(T.DOWNLOAD_OPTIONS_PREVIEW.format(path=preview))

    def _on_confirm(self) -> None:
        raw_out_dir = self.out_dir_input.text().strip()
        if not raw_out_dir:
            QMessageBox.warning(self, T.TITLE_PARAM_ERROR, T.MSG_NEED_PICK_DIR)
            return
        out_dir = Path(raw_out_dir).expanduser()
        rename = self.rename_input.text().strip()
        if not rename:
            QMessageBox.warning(self, T.TITLE_PARAM_ERROR, T.MSG_EMPTY_FILENAME)
            return
        selected_format = self.format_combo.currentText().lower().strip()
        if selected_format not in SUPPORTED_GUI_AUDIO_FORMATS:
            QMessageBox.warning(self, T.TITLE_PARAM_ERROR, T.MSG_UNSUPPORTED_FORMAT.format(fmt=selected_format))
            return
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            self.output_path = resolve_output_path(
                out_dir=out_dir,
                song_id=self.result.song_id,
                song_name=self.result.song_name,
                rename=rename,
                out_format=selected_format,
            )
            self.selected_format = selected_format
        except MusicFetchError as err:
            mapped = user_error_message(err.code, err.message)
            QMessageBox.warning(self, T.TITLE_PATH_ERROR, T.code_message(err.code, mapped))
            return
        self.accept()


class DownloadProgressDialog(QDialog):
    def __init__(self, song_id: str, output_path: Path, cookie: str, target_format: str) -> None:
        super().__init__()
        self.setWindowTitle(T.DOWNLOAD_PROGRESS_TITLE)
        self.resize(540, 190)
        self.output_path: Optional[Path] = None

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
        self.cancel_button = QPushButton(T.DOWNLOAD_PROGRESS_CANCEL)
        self.cancel_button.clicked.connect(self._on_cancel)
        button_row.addWidget(self.cancel_button)
        layout.addLayout(button_row)

        self.worker = DownloadWorker(
            song_id=song_id,
            output_path=output_path,
            cookie=cookie,
            target_format=target_format,
            timeout=30,
        )
        self.worker.progress.connect(self._on_progress)
        self.worker.failed.connect(self._on_failed)
        self.worker.canceled.connect(self._on_canceled)
        self.worker.succeeded.connect(self._on_succeeded)
        self.worker.start()

    def _on_cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.status_label.setText(T.STATUS_CANCELING)
        self.worker.request_cancel()

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
        mapped = user_error_message(code, message)
        QMessageBox.critical(self, T.TITLE_DOWNLOAD_FAIL, T.code_message(code, mapped))
        self.reject()

    def _on_canceled(self) -> None:
        QMessageBox.information(self, T.TITLE_DOWNLOAD_CANCELED, T.MSG_DOWNLOAD_CANCELED)
        self.reject()

    def _on_succeeded(self, output_path: str, file_size: int) -> None:
        self.output_path = Path(output_path)
        QMessageBox.information(
            self,
            T.TITLE_DOWNLOAD_DONE,
            T.DOWNLOAD_PROGRESS_DONE_BODY.format(
                name=self.output_path.name,
                size=format_bytes(file_size),
                path=self.output_path,
            ),
        )
        self.accept()


class DownloadManagerDialog(QDialog):
    def __init__(self, history_store: DownloadHistoryStore, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.history_store = history_store
        self.records: list[DownloadRecord] = []
        self.setWindowTitle(T.MANAGER_TITLE)
        self.resize(900, 420)

        layout = QVBoxLayout(self)
        self.empty_label = QLabel(T.MSG_DOWNLOADS_EMPTY)
        self.empty_label.setStyleSheet("color: #666666;")
        self.empty_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.empty_label)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [
                T.MANAGER_COL_SONG,
                T.MANAGER_COL_FILENAME,
                T.MANAGER_COL_SIZE,
                T.MANAGER_COL_TIME,
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
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.table)

        button_row = QHBoxLayout()
        self.open_folder_button = QPushButton(T.MANAGER_BTN_OPEN_FOLDER)
        self.open_folder_button.clicked.connect(self._open_selected_folder)
        self.delete_button = QPushButton(T.MANAGER_BTN_DELETE_FILE)
        self.delete_button.clicked.connect(self._delete_selected_file)
        refresh_button = QPushButton(T.MANAGER_BTN_REFRESH)
        refresh_button.clicked.connect(self.refresh)
        close_button = QPushButton(T.BTN_CLOSE)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(self.open_folder_button)
        button_row.addWidget(self.delete_button)
        button_row.addStretch(1)
        button_row.addWidget(refresh_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.refresh()

    def refresh(self) -> None:
        self.records = self.history_store.load()
        self.empty_label.setVisible(len(self.records) == 0)
        self.table.setVisible(len(self.records) > 0)
        self.table.setRowCount(len(self.records))
        for row, record in enumerate(self.records):
            file_name = Path(record.output_path).name
            self.table.setItem(row, 0, QTableWidgetItem(record.song_name))
            self.table.setItem(row, 1, QTableWidgetItem(file_name))
            self.table.setItem(row, 2, QTableWidgetItem(format_bytes(record.size_bytes)))
            self.table.setItem(row, 3, QTableWidgetItem(record.downloaded_at))
            self.table.setItem(row, 4, QTableWidgetItem(record.output_path))
        logger.info("Download manager refreshed. count=%s", len(self.records))

    def _selected_record(self) -> Optional[DownloadRecord]:
        current = self.table.currentRow()
        if current < 0 or current >= len(self.records):
            return None
        return self.records[current]

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


class MainWindow(QMainWindow):
    def __init__(self, session_store: SessionStore, history_store: DownloadHistoryStore, session: AppSession) -> None:
        super().__init__()
        self.session_store = session_store
        self.history_store = history_store
        self.session = session
        self.inspect_worker: Optional[InspectWorker] = None
        self.account_profile: Optional[AccountProfile] = None
        self._avatar_error_notified = False
        self.setWindowTitle(T.APP_TITLE)
        self.resize(860, 320)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        account_row = QHBoxLayout()
        self.avatar_button = QToolButton()
        self.avatar_button.setFixedSize(52, 52)
        self.avatar_button.setIconSize(QSize(44, 44))
        self.avatar_button.setText(T.ACCOUNT_BTN_FALLBACK)
        self.avatar_button.setToolButtonStyle(Qt.ToolButtonTextOnly)

        self.account_menu = QMenu(self)
        switch_action = QAction(T.ACCOUNT_MENU_SWITCH, self)
        switch_action.triggered.connect(self._on_switch_account)
        logout_action = QAction(T.ACCOUNT_MENU_LOGOUT, self)
        logout_action.triggered.connect(self._on_logout_account)
        self.account_menu.addAction(switch_action)
        self.account_menu.addAction(logout_action)
        self.avatar_button.setPopupMode(QToolButton.InstantPopup)
        self.avatar_button.setMenu(self.account_menu)
        account_row.addWidget(self.avatar_button)

        account_text = QVBoxLayout()
        self.nickname_label = QLabel(T.ACCOUNT_LABEL_NICKNAME_LOGOUT)
        self.vip_label = QLabel(T.ACCOUNT_LABEL_VIP_UNKNOWN)
        account_text.addWidget(self.nickname_label)
        account_text.addWidget(self.vip_label)
        account_row.addLayout(account_text)

        account_row.addStretch(1)
        self.manager_button = QPushButton(T.BTN_DOWNLOAD_MANAGER)
        self.manager_button.clicked.connect(self._open_download_manager)
        account_row.addWidget(self.manager_button)
        layout.addLayout(account_row)

        description = QLabel(T.APP_DESC)
        description.setWordWrap(True)
        layout.addWidget(description)

        row = QHBoxLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(T.INPUT_PLACEHOLDER.format(url=URL_EXAMPLE_LONG))
        row.addWidget(self.url_input, stretch=1)
        help_button = QToolButton()
        help_button.setText("?")
        help_button.setToolTip(T.HELP_TOOLTIP.format(url=URL_EXAMPLE_LONG))
        row.addWidget(help_button)
        self.detect_button = QPushButton(T.BTN_DETECT)
        self.detect_button.clicked.connect(self._on_detect_clicked)
        row.addWidget(self.detect_button)
        layout.addLayout(row)

        self.status_label = QLabel(T.STATUS_IDLE)
        layout.addWidget(self.status_label)

        self._refresh_account_profile()

    def _apply_account_profile(self, profile: Optional[AccountProfile]) -> None:
        self.account_profile = profile
        if not profile:
            self.nickname_label.setText(T.ACCOUNT_LABEL_NICKNAME_LOGOUT)
            self.vip_label.setText(T.ACCOUNT_LABEL_VIP_UNKNOWN)
            self.vip_label.setStyleSheet("color: #666666;")
            self.avatar_button.setIcon(QIcon())
            self.avatar_button.setText(T.ACCOUNT_BTN_FALLBACK)
            self.avatar_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            return

        self.nickname_label.setText(T.nickname_text(profile.nickname))
        vip_text = T.ACCOUNT_LABEL_VIP if profile.is_vip else T.ACCOUNT_LABEL_NORMAL
        self.vip_label.setText(vip_text)
        self.vip_label.setStyleSheet("color: #b07500;" if profile.is_vip else "color: #666666;")

        icon = load_avatar_icon(profile.avatar_url)
        if icon:
            self.avatar_button.setIcon(icon)
            self.avatar_button.setText("")
            self.avatar_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            self.avatar_button.setIconSize(QSize(44, 44))
            self._avatar_error_notified = False
        else:
            self.avatar_button.setIcon(QIcon())
            self.avatar_button.setText(T.ACCOUNT_BTN_FALLBACK)
            self.avatar_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            if profile.avatar_url and not self._avatar_error_notified:
                self._avatar_error_notified = True
                QMessageBox.information(self, T.TITLE_AVATAR_FAIL, T.MSG_AVATAR_LOAD_FAILED)

    def _refresh_account_profile(self) -> None:
        if not self.session.cookie:
            self._apply_account_profile(None)
            return
        try:
            profile = fetch_account_profile(self.session.cookie, timeout=10)
            self._apply_account_profile(profile)
        except MusicFetchError as err:
            logger.warning("Failed to refresh account profile. code=%s message=%s", err.code, err.message)
            self._apply_account_profile(None)

    def _on_switch_account(self) -> None:
        logger.info("User requested switch account.")
        dialog = LoginDialog()
        dialog.login_success.connect(self._on_login_success)
        if dialog.exec() != QDialog.Accepted:
            QMessageBox.information(self, T.TITLE_SWITCH_CANCELED, T.MSG_SWITCH_CANCELED)
            logger.info("Switch account canceled; keep current session.")

    def _on_logout_account(self) -> None:
        if not self.session.cookie:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_NOT_LOGGED_IN)
            return
        answer = QMessageBox.question(
            self,
            T.TITLE_LOGOUT,
            T.MSG_LOGOUT_CONFIRM,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self.session.cookie = ""
        self.session_store.save(self.session)
        self._apply_account_profile(None)
        self.status_label.setText(T.STATUS_LOGOUT)
        logger.info("User logged out current account.")

    def _on_login_success(self, cookie: str, remember_login: bool) -> None:
        self.session.cookie = cookie
        self.session.remember_login = remember_login
        self.session_store.save(self.session)
        self._refresh_account_profile()
        logger.info("MainWindow login updated.")
        self.status_label.setText(T.STATUS_LOGIN_UPDATED)

    def _open_download_manager(self) -> None:
        logger.info("Open download manager.")
        dialog = DownloadManagerDialog(history_store=self.history_store, parent=self)
        dialog.exec()

    def _on_detect_clicked(self) -> None:
        song_url = self.url_input.text().strip()
        if not song_url:
            QMessageBox.warning(self, T.TITLE_PARAM_ERROR, T.MSG_NEED_INPUT_URL)
            return
        if not self.session.cookie:
            QMessageBox.warning(self, T.TITLE_NOT_LOGIN, T.MSG_NEED_LOGIN_ANY)
            return

        self.detect_button.setEnabled(False)
        self.status_label.setText(T.STATUS_DETECTING)
        logger.info("Detection started from GUI.")
        self.inspect_worker = InspectWorker(song_url=song_url, cookie=self.session.cookie, timeout=20)
        self.inspect_worker.failed.connect(self._on_detect_failed)
        self.inspect_worker.succeeded.connect(self._on_detect_succeeded)
        self.inspect_worker.finished.connect(lambda: self.detect_button.setEnabled(True))
        self.inspect_worker.start()

    def _on_detect_failed(self, code: str, message: str) -> None:
        logger.warning("Detection failed. code=%s message=%s", code, message)
        mapped = user_error_message(code, message)
        if code == "AUTH_EXPIRED":
            QMessageBox.warning(self, T.TITLE_LOGIN_EXPIRED, T.detect_auth_expired(code, mapped))
        else:
            QMessageBox.warning(self, T.TITLE_DETECT_FAIL, T.code_message(code, mapped))
        self.status_label.setText(T.STATUS_DETECT_FAILED)

    def _record_download(self, song_id: str, song_name: str, output_path: Path, size_bytes: int) -> None:
        record = DownloadRecord(
            song_id=song_id,
            song_name=song_name or f"song-{song_id}",
            output_path=str(output_path),
            size_bytes=size_bytes,
            downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
        self.history_store.add(record)

    def _on_detect_succeeded(self, result: SongDetectionResult) -> None:
        logger.info("Detection succeeded. song_id=%s", result.song_id)
        self.status_label.setText(T.STATUS_DETECT_DONE)
        confirm = SongConfirmDialog(result)
        if confirm.exec() != QDialog.Accepted:
            return

        options = DownloadOptionsDialog(result, last_download_dir=self.session.last_download_dir)
        if options.exec() != QDialog.Accepted or not options.output_path:
            return

        self.session.last_download_dir = str(options.output_path.parent)
        self.session_store.save(self.session)
        self.status_label.setText(T.STATUS_DOWNLOADING)

        progress = DownloadProgressDialog(
            song_id=result.song_id,
            output_path=options.output_path,
            cookie=self.session.cookie,
            target_format=options.selected_format,
        )
        if progress.exec() == QDialog.Accepted and progress.output_path:
            size_bytes = progress.output_path.stat().st_size if progress.output_path.exists() else 0
            self._record_download(
                song_id=result.song_id,
                song_name=result.song_name or "",
                output_path=progress.output_path,
                size_bytes=size_bytes,
            )
            self.status_label.setText(T.status_download_done(progress.output_path.name))
            logger.info("GUI flow finished successfully. output=%s", progress.output_path)
        else:
            self.status_label.setText(T.STATUS_DOWNLOAD_NOT_DONE)
            logger.info("GUI flow ended without completed download.")


def ensure_session_with_login(session_store: SessionStore) -> Optional[AppSession]:
    session = session_store.load()
    if session.cookie:
        try:
            if check_login_status(session.cookie, timeout=10):
                logger.info("Reused existing login session.")
                return session
        except MusicFetchError:
            logger.warning("Existing login session check failed due to network issue.")

    dialog = LoginDialog()
    holder: dict[str, object] = {}

    def on_login(cookie: str, remember: bool) -> None:
        holder["cookie"] = cookie
        holder["remember"] = remember

    dialog.login_success.connect(on_login)
    if dialog.exec() != QDialog.Accepted:
        logger.info("Login dialog canceled by user.")
        QMessageBox.information(None, T.TITLE_NOT_LOGIN, T.MSG_NO_LOGIN_ON_START)
        return None

    cookie = str(holder.get("cookie") or "")
    remember = bool(holder.get("remember", True))
    loaded = session_store.load()
    loaded.cookie = cookie if remember else ""
    loaded.remember_login = remember
    session_store.save(loaded)
    return AppSession(
        cookie=cookie,
        remember_login=remember,
        last_download_dir=loaded.last_download_dir,
    )


def main() -> int:
    log_path = setup_logging(default_log_path(), level=logging.INFO)
    app = QApplication(sys.argv)
    logger.info("GUI app started. log_path=%s", log_path)
    session_store = SessionStore(SESSION_FILE)
    history_store = DownloadHistoryStore(DOWNLOAD_HISTORY_FILE)
    session = ensure_session_with_login(session_store)
    if session is None:
        logger.info("GUI app exit due to missing session.")
        return 0
    window = MainWindow(session_store=session_store, history_store=history_store, session=session)
    window.show()
    exit_code = app.exec()
    logger.info("GUI app exited. code=%s", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
