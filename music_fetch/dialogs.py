#!/usr/bin/env python3
"""
All GUI dialog classes extracted from the original main.py.

Includes LoginDialog, SongConfirmDialog, DownloadOptionsDialog,
DownloadProgressDialog, DependencyManagerDialog, DownloadManagerDialog,
and UiSettingsDialog.

Also contains shared helper functions (set_button_role, set_label_state, …)
and the WEB_ENGINE_AVAILABLE constant.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib import error, parse, request

from music_fetch.app_logging import default_log_path, get_logger, setup_logging
from music_fetch.batch_inputs import collect_batch_candidates, source_hint_map
from music_fetch.error_texts import user_error_message
from music_fetch.app_settings import (
    APP_VERSION,
    clamp_download_settings,
    DEFAULT_DETECT_TIMEOUT_SEC,
    DETECT_TIMEOUT_OPTIONS,
    DOWNLOAD_TIMEOUT_OPTIONS,
    DEFAULT_DOWNLOAD_CONCURRENCY,
    DEFAULT_DOWNLOAD_DIR,
    DEFAULT_DOWNLOAD_RETRY_COUNT,
    DEFAULT_DOWNLOAD_TIMEOUT_SEC,
    DEFAULT_GUI_TARGET_FORMAT,
    DEFAULT_UI_FONT_SIZE,
    DOWNLOAD_HISTORY_FILE,
    MAX_DETECT_TIMEOUT_SEC,
    MAX_DOWNLOAD_CONCURRENCY,
    MAX_DOWNLOAD_RETRY_COUNT,
    MAX_DOWNLOAD_TIMEOUT_SEC,
    MAX_UI_FONT_SIZE,
    MIN_DETECT_TIMEOUT_SEC,
    MIN_DOWNLOAD_CONCURRENCY,
    MIN_DOWNLOAD_RETRY_COUNT,
    MIN_DOWNLOAD_TIMEOUT_SEC,
    MIN_UI_FONT_SIZE,
    NETEASE_LOGIN_URL,
    PROJECT_GITHUB_URL,
    PROJECT_RELEASE_API,
    PROJECT_TAGS_API,
    SESSION_FILE,
    clamp,
)
from music_fetch.download_retry import can_retry_status, retry_target_format
from music_fetch.download_tasks import (
    build_task_id,
    DownloadTaskSnapshot,
    TASK_STATE_CANCELED,
    TASK_STATE_DOWNLOADING,
    TASK_STATE_FAILED,
    TASK_STATE_PENDING,
    TASK_STATE_SUCCESS,
    next_task_snapshot,
)
from music_fetch.app_stores import AppSession, DownloadHistoryStore, DownloadRecord, SessionStore
from music_fetch.api import AccountProfile, MusicFetchError, SongDetectionResult, SUPPORTED_GUI_AUDIO_FORMATS, build_cookie_string, check_login_status, detect_song, fetch_account_profile, fetch_playlist_song_ids, extract_url_from_input, is_netease_music_host, parse_input_resource, SHORT_LINK_HOSTS
from music_fetch.audio import convert_audio_file, download_song_with_fallback, infer_audio_format_from_url, is_ffmpeg_available, resolve_output_path, sanitize_filename
import music_fetch.ui_texts as T
import music_fetch.combo_utils
import music_fetch.workers
from music_fetch.batch_models import format_bytes, format_duration
from music_fetch.gui_styles import (
    apply_app_style,
    build_app_stylesheet,
    clamp_ui_font_size,
    set_back_button,
    set_button_role,
    set_label_state,
    set_secondary_button,
)
from music_fetch.dialog_login import LoginDialog, build_cookie_from_fields, WEB_ENGINE_AVAILABLE
from music_fetch.dialog_progress import DownloadProgressDialog
from music_fetch.dialog_manager import DownloadManagerDialog

try:
    from PySide6.QtCore import QSize, QThread, Qt, QTimer, QUrl, Signal
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
        QPlainTextEdit,
        QPushButton,
        QProgressBar,
        QSizePolicy,
        QTableWidget,
        QTableWidgetItem,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
except ImportError as err:
    raise SystemExit(
        "Missing dependency: PySide6. Install it with `python3 -m pip install PySide6` before running main.py."
    ) from err

logger = get_logger("music_fetch.gui")
BATCH_ROUTE_MIN_COUNT = 2



__all__ = ['BATCH_ROUTE_MIN_COUNT', 'WEB_ENGINE_AVAILABLE', 'LoginDialog', 'SongConfirmDialog', 'DownloadOptionsDialog', 'DownloadProgressDialog', 'DependencyManagerDialog', 'DownloadManagerDialog', 'UiSettingsDialog', 'apply_app_style', 'clamp_ui_font_size', 'clear_embedded_login_state', 'load_avatar_icon', 'set_button_role', 'set_label_state', 'validate_song_input']
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


def clear_embedded_login_state() -> None:
    """Best-effort cleanup for embedded web login state."""
    if not WEB_ENGINE_AVAILABLE:
        return
    try:
        # Ensure the next login dialog always starts from a logged-out web context.
        profile = QWebEngineProfile.defaultProfile()
        profile.cookieStore().deleteAllCookies()
        profile.clearHttpCache()
        logger.info("Embedded login web state cleared.")
    except Exception:  # pragma: no cover - depends on Qt runtime.
        logger.exception("Failed to clear embedded login web state.")


def validate_song_input(value: str) -> tuple[bool, str]:
    raw = value.strip()
    if not raw:
        return False, T.INPUT_VALIDATION_EMPTY
    if raw.isdigit():
        return True, T.INPUT_VALIDATION_OK_ID

    embedded_url = extract_url_from_input(raw)
    target = embedded_url if embedded_url else raw
    parsed = parse.urlparse(target)
    host = parsed.netloc.lower()
    if host and not is_netease_music_host(host) and host not in SHORT_LINK_HOSTS:
        return False, T.INPUT_VALIDATION_BAD_HOST

    if host in SHORT_LINK_HOSTS:
        return True, T.INPUT_VALIDATION_SHORT_LINK

    id_patterns = (
        parse.parse_qs(parsed.query).get("id", []),
        re.findall(r"id=(\d+)", parsed.fragment or ""),
        re.findall(r"/song/(\d+)", parsed.path or ""),
        re.findall(r"id=(\d+)", target),
    )
    has_song_id = any(any(part.isdigit() for part in pattern) for pattern in id_patterns if pattern)
    if has_song_id:
        return True, T.INPUT_VALIDATION_OK_URL
    return False, T.INPUT_VALIDATION_ID_MISSING


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
        set_label_state(status_label, "success" if result.can_download else "error")
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
        close_button = QPushButton(T.BTN_BACK)
        close_button.clicked.connect(self.reject)
        set_back_button(close_button)
        self.download_button = QPushButton(T.BTN_DOWNLOAD)
        self.download_button.setEnabled(result.can_download)
        self.download_button.clicked.connect(self.accept)
        set_button_role(self.download_button, "primary")
        button_row.addWidget(close_button)
        button_row.addWidget(self.download_button)
        layout.addLayout(button_row)


class DownloadOptionsDialog(QDialog):
    def __init__(self, result: SongDetectionResult, last_download_dir: str) -> None:
        super().__init__()
        self.result = result
        self.output_path: Optional[Path] = None
        self.selected_format: str = DEFAULT_GUI_TARGET_FORMAT
        self.ffmpeg_available = is_ffmpeg_available()
        self._format_guard = False
        self.setWindowTitle(T.DOWNLOAD_OPTIONS_TITLE)
        self.resize(760, 240)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.out_dir_input = QLineEdit(last_download_dir or DEFAULT_DOWNLOAD_DIR)
        self.out_dir_input.setMinimumWidth(400)
        self.out_dir_input.setToolTip(self.out_dir_input.text())
        self.out_dir_input.textChanged.connect(self.out_dir_input.setToolTip)
        browse_button = QPushButton(T.DOWNLOAD_DIR_PICKER_BTN)
        browse_button.setMinimumWidth(100)
        browse_button.clicked.connect(self._pick_directory)
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.out_dir_input, stretch=1)
        dir_row.addWidget(browse_button)
        dir_widget = QWidget()
        dir_widget.setLayout(dir_row)

        default_name = sanitize_filename(
            f"{result.song_name}-{result.song_id}" if result.song_name else f"song-{result.song_id}"
        )
        self.rename_input = QLineEdit(default_name)
        self.format_combo = QComboBox()
        self.format_combo.addItems([fmt.upper() for fmt in SUPPORTED_GUI_AUDIO_FORMATS])
        self.format_combo.setMinimumWidth(160)
        self.format_combo.setMinimumContentsLength(10)
        self.format_combo.view().setMinimumWidth(180)
        self.format_combo.setCurrentText(DEFAULT_GUI_TARGET_FORMAT.upper())
        form.addRow(T.DOWNLOAD_OPTIONS_DIR, dir_widget)
        form.addRow(T.DOWNLOAD_OPTIONS_NAME, self.rename_input)
        form.addRow(T.DOWNLOAD_OPTIONS_FORMAT, self.format_combo)
        layout.addLayout(form)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        self.form_feedback_label = QLabel("")
        self.form_feedback_label.setWordWrap(True)
        set_label_state(self.form_feedback_label, "muted")
        layout.addWidget(self.form_feedback_label)
        self._refresh_preview()
        self.out_dir_input.textChanged.connect(self._on_form_text_changed)
        self.rename_input.textChanged.connect(self._on_form_text_changed)
        self.format_combo.currentTextChanged.connect(self._on_format_changed)
        self.format_combo.currentTextChanged.connect(self._on_form_text_changed)

        if not self.ffmpeg_available:
            self._apply_ffmpeg_unavailable_constraints()

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton(T.BTN_BACK)
        cancel_button.clicked.connect(self.reject)
        set_back_button(cancel_button)
        self.ok_button = QPushButton(T.BTN_START_DOWNLOAD)
        self.ok_button.clicked.connect(self._on_confirm)
        set_button_role(self.ok_button, "primary")
        button_row.addWidget(cancel_button)
        button_row.addWidget(self.ok_button)
        layout.addLayout(button_row)
        self._sync_form_state()

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

    def _on_form_text_changed(self, *_args: object) -> None:
        self._refresh_preview()
        self._sync_form_state()

    def _sync_form_state(self) -> None:
        out_dir = self.out_dir_input.text().strip()
        rename = self.rename_input.text().strip()
        if not out_dir:
            self.ok_button.setEnabled(False)
            self.form_feedback_label.setText(T.DOWNLOAD_OPTIONS_HINT_PICK_DIR)
            set_label_state(self.form_feedback_label, "error")
            return
        if not rename:
            self.ok_button.setEnabled(False)
            self.form_feedback_label.setText(T.DOWNLOAD_OPTIONS_HINT_RENAME)
            set_label_state(self.form_feedback_label, "error")
            return
        self.ok_button.setEnabled(True)
        self.form_feedback_label.setText(T.DOWNLOAD_OPTIONS_HINT_READY)
        set_label_state(self.form_feedback_label, "success")

    def _apply_ffmpeg_unavailable_constraints(self) -> None:
        model = self.format_combo.model()
        for idx, fmt in enumerate(SUPPORTED_GUI_AUDIO_FORMATS):
            if fmt == "mp3":
                continue
            item = model.item(idx) if hasattr(model, "item") else None
            if item is not None:
                item.setEnabled(False)
                item.setToolTip(T.MSG_FFMPEG_NEED_INSTALL)
        self._set_format_safely("MP3")
        logger.warning("ffmpeg not found. locked convertible formats in download options.")

    def _set_format_safely(self, value: str) -> None:
        self._format_guard = True
        try:
            self.format_combo.setCurrentText(value)
        finally:
            self._format_guard = False

    def _on_format_changed(self, value: str) -> None:
        if self._format_guard:
            return
        if self.ffmpeg_available:
            return
        if value.lower().strip() == "mp3":
            return
        QMessageBox.information(self, T.TITLE_DEP_MISSING, T.MSG_FFMPEG_NEED_INSTALL)
        self._set_format_safely("MP3")

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
        if not self.ffmpeg_available and selected_format != "mp3":
            QMessageBox.information(self, T.TITLE_DEP_MISSING, T.MSG_FFMPEG_NEED_INSTALL)
            self._set_format_safely("MP3")
            selected_format = "mp3"
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


class DependencyManagerDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(T.DEP_MANAGER_TITLE)
        self.resize(780, 280)

        layout = QVBoxLayout(self)
        desc = QLabel(T.DEP_MANAGER_DESC)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        self.table = QTableWidget(1, 4)
        self.table.setHorizontalHeaderLabels(
            [
                T.DEP_MANAGER_COL_NAME,
                T.DEP_MANAGER_COL_STATUS,
                T.DEP_MANAGER_COL_IMPACT,
                T.DEP_MANAGER_COL_INSTALL,
            ]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.table, stretch=1)

        button_row = QHBoxLayout()
        button_row.setAlignment(Qt.AlignVCenter)
        button_row.setSpacing(10)
        button_row.addStretch(1)
        refresh_button = QPushButton(T.MANAGER_BTN_REFRESH)
        refresh_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        set_secondary_button(refresh_button)
        refresh_button.clicked.connect(self.refresh)
        close_button = QPushButton(T.BTN_BACK)
        close_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        close_button.clicked.connect(self.accept)
        set_back_button(close_button)
        button_row.addWidget(refresh_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.refresh()

    def refresh(self) -> None:
        # Keep this dialog runtime-driven so users can install dependency
        # and click "刷新" to verify immediately without restarting app.
        ffmpeg_ok = is_ffmpeg_available()
        self.table.setItem(0, 0, QTableWidgetItem(T.DEP_MANAGER_ITEM_FFMPEG))
        self.table.setItem(
            0, 1, QTableWidgetItem(T.DEP_MANAGER_STATUS_OK if ffmpeg_ok else T.DEP_MANAGER_STATUS_MISSING)
        )
        self.table.setItem(
            0, 2, QTableWidgetItem(T.DEP_MANAGER_IMPACT_OK if ffmpeg_ok else T.DEP_MANAGER_IMPACT_MISSING)
        )
        self.table.setItem(
            0, 3, QTableWidgetItem(T.DEP_MANAGER_INSTALL_OK if ffmpeg_ok else T.DEP_MANAGER_INSTALL_FFMPEG)
        )
        logger.info("Dependency manager refreshed. ffmpeg_available=%s", ffmpeg_ok)


class UiSettingsDialog(QDialog):
    def __init__(
        self,
        current_font_size: int,
        detect_timeout_sec: int,
        download_timeout_sec: int,
        download_retry_count: int,
        download_concurrency: int,
        current_theme: str = "light",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.font_size = clamp_ui_font_size(current_font_size)
        self.detect_timeout_sec, self.download_timeout_sec, self.download_retry_count, self.download_concurrency = clamp_download_settings(
            detect_timeout_sec, download_timeout_sec, download_retry_count, download_concurrency,
        )
        from music_fetch.app_settings import DEFAULT_UI_THEME, UI_THEME_OPTIONS
        self.ui_theme = (current_theme or "").strip().lower()
        if self.ui_theme not in UI_THEME_OPTIONS:
            self.ui_theme = DEFAULT_UI_THEME
        self.setWindowTitle(T.UI_SETTINGS_TITLE)
        self.resize(520, 380)

        layout = QVBoxLayout(self)
        desc = QLabel(T.UI_SETTINGS_DESC)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.font_size_input = music_fetch.combo_utils.build_value_combo(MIN_UI_FONT_SIZE, MAX_UI_FONT_SIZE, "px")
        music_fetch.combo_utils.set_combo_value(self.font_size_input, self.font_size)
        self.font_size_input.currentIndexChanged.connect(self._on_font_size_changed)
        form.addRow(T.UI_SETTINGS_FONT_SIZE, self.font_size_input)
        # Theme selector
        self.theme_combo = QComboBox()
        theme_labels = {"light": T.UI_SETTINGS_THEME_LIGHT, "dark": T.UI_SETTINGS_THEME_DARK}
        for theme_key in UI_THEME_OPTIONS:
            self.theme_combo.addItem(theme_labels.get(theme_key, theme_key), theme_key)
        idx = self.theme_combo.findData(self.ui_theme)
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._on_theme_changed)
        form.addRow(T.UI_SETTINGS_THEME, self.theme_combo)
        layout.addLayout(form)

        download_title = QLabel(T.UI_SETTINGS_DOWNLOAD_GROUP)
        set_label_state(download_title, "muted")
        layout.addWidget(download_title)
        download_form = QFormLayout()
        download_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.detect_timeout_input = music_fetch.combo_utils.build_options_combo(DETECT_TIMEOUT_OPTIONS, "s")
        music_fetch.combo_utils.set_combo_value(self.detect_timeout_input, self.detect_timeout_sec)
        self.detect_timeout_input.currentIndexChanged.connect(self._on_download_settings_changed)
        download_form.addRow(T.UI_SETTINGS_DETECT_TIMEOUT, self.detect_timeout_input)

        self.download_timeout_input = music_fetch.combo_utils.build_options_combo(DOWNLOAD_TIMEOUT_OPTIONS, "s")
        music_fetch.combo_utils.set_combo_value(self.download_timeout_input, self.download_timeout_sec)
        self.download_timeout_input.currentIndexChanged.connect(self._on_download_settings_changed)
        download_form.addRow(T.UI_SETTINGS_DOWNLOAD_TIMEOUT, self.download_timeout_input)

        self.download_retry_input = music_fetch.combo_utils.build_value_combo(MIN_DOWNLOAD_RETRY_COUNT, MAX_DOWNLOAD_RETRY_COUNT, T.COUNT_SUFFIX)
        music_fetch.combo_utils.set_combo_value(self.download_retry_input, self.download_retry_count)
        self.download_retry_input.currentIndexChanged.connect(self._on_download_settings_changed)
        download_form.addRow(T.UI_SETTINGS_DOWNLOAD_RETRY, self.download_retry_input)

        self.download_concurrency_input = music_fetch.combo_utils.build_value_combo(
            MIN_DOWNLOAD_CONCURRENCY, MAX_DOWNLOAD_CONCURRENCY, T.CONCURRENCY_SUFFIX
        )
        music_fetch.combo_utils.set_combo_value(self.download_concurrency_input, self.download_concurrency)
        self.download_concurrency_input.currentIndexChanged.connect(self._on_download_settings_changed)
        download_form.addRow(T.UI_SETTINGS_DOWNLOAD_CONCURRENCY, self.download_concurrency_input)

        download_hint = QLabel(T.UI_SETTINGS_DOWNLOAD_CONCURRENCY_HINT)
        download_hint.setWordWrap(True)
        set_label_state(download_hint, "muted")
        download_form.addRow(download_hint)
        layout.addLayout(download_form)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        layout.addWidget(self.preview_label)
        self._refresh_preview()

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        reset_button = QPushButton(T.UI_SETTINGS_RESET)
        set_secondary_button(reset_button)
        reset_button.clicked.connect(self._reset_default)
        back_button = QPushButton(T.BTN_BACK)
        back_button.clicked.connect(self.reject)
        set_back_button(back_button)
        save_button = QPushButton(T.UI_SETTINGS_SAVE)
        save_button.clicked.connect(self.accept)
        set_button_role(save_button, "primary")
        button_row.addWidget(reset_button)
        button_row.addWidget(back_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    def _on_theme_changed(self, _index: int) -> None:
        self.ui_theme = str(self.theme_combo.currentData() or DEFAULT_UI_THEME)
        self._refresh_preview()

    def _on_font_size_changed(self, _index: int) -> None:
        self.font_size = clamp_ui_font_size(music_fetch.combo_utils.combo_int_value(self.font_size_input, DEFAULT_UI_FONT_SIZE))
        self._refresh_preview()

    def _on_download_settings_changed(self, *_args: object) -> None:
        self.detect_timeout_sec, self.download_timeout_sec, self.download_retry_count, self.download_concurrency = clamp_download_settings(
            music_fetch.combo_utils.combo_int_value(self.detect_timeout_input, DEFAULT_DETECT_TIMEOUT_SEC),
            music_fetch.combo_utils.combo_int_value(self.download_timeout_input, DEFAULT_DOWNLOAD_TIMEOUT_SEC),
            music_fetch.combo_utils.combo_int_value(self.download_retry_input, DEFAULT_DOWNLOAD_RETRY_COUNT),
            music_fetch.combo_utils.combo_int_value(self.download_concurrency_input, DEFAULT_DOWNLOAD_CONCURRENCY),
        )
        self._refresh_preview()

    def _reset_default(self) -> None:
        music_fetch.combo_utils.set_combo_value(self.font_size_input, DEFAULT_UI_FONT_SIZE)
        music_fetch.combo_utils.set_combo_value(self.detect_timeout_input, DEFAULT_DETECT_TIMEOUT_SEC)
        music_fetch.combo_utils.set_combo_value(self.download_timeout_input, DEFAULT_DOWNLOAD_TIMEOUT_SEC)
        music_fetch.combo_utils.set_combo_value(self.download_retry_input, DEFAULT_DOWNLOAD_RETRY_COUNT)
        music_fetch.combo_utils.set_combo_value(self.download_concurrency_input, DEFAULT_DOWNLOAD_CONCURRENCY)
        self._on_download_settings_changed()
        self._on_font_size_changed(0)

    def _refresh_preview(self) -> None:
        self.preview_label.setText(
            T.ui_settings_preview(self.font_size)
            + "\n"
            + T.status_ui_settings_updated(
                self.font_size,
                self.detect_timeout_sec,
                self.download_timeout_sec,
                self.download_retry_count,
                self.download_concurrency,
                prefix=False,
            )
        )
        set_label_state(self.preview_label, "muted")
