#!/usr/bin/env python3
"""
All GUI dialog classes extracted from the original main.py.

Includes LoginDialog, SongConfirmDialog, DownloadOptionsDialog,
DownloadProgressDialog, DependencyManagerDialog, DownloadManagerDialog,
BatchRuntimeSettingsDialog, BatchDownloadDialog, and UiSettingsDialog.

Also contains shared helper functions (set_button_role, set_label_state, …)
and the WEB_ENGINE_AVAILABLE constant.
"""

from __future__ import annotations

import copy
import functools
import logging
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib import error, parse, request

from app_logging import default_log_path, get_logger, setup_logging
from batch_inputs import collect_batch_candidates, source_hint_map
from error_texts import user_error_message
from app_settings import (
    APP_VERSION,
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
)
from download_retry import can_retry_status, retry_target_format
from download_tasks import (
    build_task_id,
    DownloadTaskSnapshot,
    TASK_STATE_CANCELED,
    TASK_STATE_DOWNLOADING,
    TASK_STATE_FAILED,
    TASK_STATE_PENDING,
    TASK_STATE_SUCCESS,
    next_task_snapshot,
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
    fetch_playlist_song_ids,
    extract_url_from_input,
    is_netease_music_host,
    infer_audio_format_from_url,
    is_ffmpeg_available,
    parse_input_resource,
    resolve_output_path,
    sanitize_filename,
    SHORT_LINK_HOSTS,
)
import ui_texts as T
import _combo_utils
import _workers

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

try:
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile
    from PySide6.QtWebEngineWidgets import QWebEngineView

    WEB_ENGINE_AVAILABLE = True
except ImportError:
    WEB_ENGINE_AVAILABLE = False

logger = get_logger("music_fetch.gui")
BATCH_ROUTE_MIN_COUNT = 2


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


def build_cookie_from_fields(cookie_fields: dict[str, str]) -> str:
    """Build a Cookie header string from captured WebEngine cookies."""
    music_u = (cookie_fields.get("MUSIC_U") or "").strip()
    if not music_u:
        return ""

    parts: list[str] = []
    seen: set[str] = set()
    for key in ("MUSIC_U", "__csrf"):
        value = (cookie_fields.get(key) or "").strip()
        if value:
            parts.append(f"{key}={value}")
            seen.add(key)

    for key in sorted(cookie_fields.keys()):
        if key in seen:
            continue
        value = (cookie_fields.get(key) or "").strip()
        if value:
            parts.append(f"{key}={value}")
    return "; ".join(parts)


def clamp_ui_font_size(value: object) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return DEFAULT_UI_FONT_SIZE
    return max(MIN_UI_FONT_SIZE, min(MAX_UI_FONT_SIZE, parsed))


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


def apply_app_style(app: QApplication, font_size: int) -> int:
    normalized = clamp_ui_font_size(font_size)
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


class LoginDialog(QDialog):
    login_success = Signal(str, bool)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(T.LOGIN_DIALOG_TITLE)
        self.cookie_fields: dict[str, str] = {}
        self._configure_window_size()

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

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.confirm_button = QPushButton(T.LOGIN_BTN_CONFIRM)
        self.confirm_button.clicked.connect(self._on_confirm)
        self.confirm_button.setEnabled(False)
        set_button_role(self.confirm_button, "primary")
        cancel_button = QPushButton(T.BTN_BACK)
        cancel_button.clicked.connect(self.reject)
        set_back_button(cancel_button)
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.confirm_button)
        root_layout.addLayout(buttons)

    def _configure_window_size(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(520, 760)
            return
        geometry = screen.availableGeometry()
        width = max(500, min(760, int(geometry.width() * 0.45)))
        height = max(700, min(980, int(geometry.height() * 0.88)))
        self.resize(width, height)

    def _build_web_login_group(self) -> QGroupBox:
        group = QGroupBox(T.LOGIN_WEB_GROUP)
        layout = QVBoxLayout(group)

        # Use an off-the-record profile so each login starts clean.
        self.web_profile = QWebEngineProfile(group)
        self.web_page = QWebEnginePage(self.web_profile, group)
        self.web_view = QWebEngineView(group)
        self.web_view.setPage(self.web_page)
        self.web_view.setUrl(QUrl(NETEASE_LOGIN_URL))
        self.web_view.loadFinished.connect(self._try_focus_qr_login)
        self.web_profile.cookieStore().cookieAdded.connect(self._on_cookie_added)

        tip = QLabel(T.LOGIN_WEB_HINT)
        tip.setWordWrap(True)
        layout.addWidget(tip)
        layout.addWidget(self.web_view, stretch=1)
        return group

    def _try_focus_qr_login(self, ok: bool) -> None:
        if not ok:
            return
        # Best-effort: auto switch to the QR tab so users do not need extra clicks.
        script = """
        (() => {
          const nodes = Array.from(document.querySelectorAll('a,button,div,span'));
          const target = nodes.find((el) => {
            const text = (el.innerText || el.textContent || '').trim();
            return text.includes('扫码登录');
          });
          if (target) {
            target.click();
            return true;
          }
          return false;
        })();
        """
        self.web_page.runJavaScript(script, self._on_qr_focus_result)

    def _on_qr_focus_result(self, switched: object) -> None:
        logger.info("Login dialog QR focus attempted. switched=%s", bool(switched))

    def _on_cookie_added(self, cookie) -> None:
        try:
            name = bytes(cookie.name()).decode("utf-8", errors="ignore")
            value = bytes(cookie.value()).decode("utf-8", errors="ignore")
        except (TypeError, RuntimeError):
            logger.debug("Failed to decode cookie from WebEngine.")
            return
        if not name or not value:
            return
        self.cookie_fields[name] = value
        self.confirm_button.setEnabled(bool(self.cookie_fields.get("MUSIC_U")))
        if name in {"MUSIC_U", "__csrf", "NMTID", "MUSIC_A"}:
            logger.info("Captured login cookie field from web page. name=%s", name)

    def _on_confirm(self) -> None:
        if not WEB_ENGINE_AVAILABLE:
            QMessageBox.warning(self, T.TITLE_DEP_MISSING, T.MSG_LOGIN_REQUIRES_WEBENGINE)
            return

        cookie = build_cookie_from_fields(self.cookie_fields)
        if not cookie:
            cookie = build_cookie_string(
                self.cookie_fields.get("MUSIC_U", ""),
                self.cookie_fields.get("__csrf", ""),
            )

        if not cookie or "MUSIC_U=" not in cookie:
            logger.info("Login confirm blocked because MUSIC_U is missing.")
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
        grid.addWidget(QLabel(_workers.format_duration(result.duration_ms)), 2, 1)
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
        self.out_dir_input.setMinimumWidth(520)
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

        self.worker = _workers.DownloadWorker(
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
        self.worker.start()
        self.result_state = TASK_STATE_DOWNLOADING
        logger.info(
            "Download progress dialog opened. task_id=%s song_id=%s timeout=%ss retry_count=%s",
            self.task_id,
            song_id,
            self.timeout,
            self.retry_count,
        )

    def _on_cancel(self) -> None:
        self.cancel_button.setEnabled(False)
        self.status_label.setText(T.STATUS_CANCELING)
        self.result_state = TASK_STATE_CANCELED
        self.worker.request_cancel()
        logger.info("Download cancel requested. task_id=%s", self.task_id)

    def _on_progress(self, downloaded: int, total: int, speed: float) -> None:
        if total <= 0:
            self.progress_bar.setRange(0, 0)
            self.status_label.setText(T.DOWNLOAD_PROGRESS_TEXT_SIMPLE.format(downloaded=_workers.format_bytes(downloaded)))
        else:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(downloaded, total))
            self.status_label.setText(
                T.DOWNLOAD_PROGRESS_TEXT_FULL.format(downloaded=_workers.format_bytes(downloaded), total=_workers.format_bytes(total))
            )
        self.speed_label.setText(T.speed_text(_workers.format_bytes(int(speed))))

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
                    size=_workers.format_bytes(file_size),
                    path=self.output_path,
                )
                + fallback_note,
            )
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
        self.filter_combo.currentIndexChanged.connect(self.refresh)
        filter_row.addWidget(self.filter_label)
        filter_row.addWidget(self.filter_combo)
        filter_row.addStretch(1)
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

        button_row = QHBoxLayout()
        self.open_folder_button = QPushButton(T.MANAGER_BTN_OPEN_FOLDER)
        self.open_folder_button.clicked.connect(self._open_selected_folder)
        self.delete_button = QPushButton(T.MANAGER_BTN_DELETE_FILE)
        self.delete_button.clicked.connect(self._delete_selected_file)
        self.retry_failed_button = QPushButton(T.MANAGER_BTN_RETRY_FAILED)
        self.retry_failed_button.clicked.connect(self._retry_selected_failed)
        refresh_button = QPushButton(T.MANAGER_BTN_REFRESH)
        refresh_button.clicked.connect(self.refresh)
        close_button = QPushButton(T.BTN_BACK)
        close_button.clicked.connect(self.accept)
        set_back_button(close_button)
        button_row.addWidget(self.open_folder_button)
        button_row.addWidget(self.delete_button)
        button_row.addWidget(self.retry_failed_button)
        button_row.addStretch(1)
        button_row.addWidget(refresh_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.table.itemSelectionChanged.connect(self._sync_action_buttons)
        self.refresh()

    def refresh(self, *_args: object) -> None:
        self.records = self.history_store.load()
        status_filter = str(self.filter_combo.currentData())
        if status_filter == "all":
            self.filtered_records = list(self.records)
        else:
            self.filtered_records = [record for record in self.records if record.status == status_filter]
        if not self.records:
            self.empty_label.setText(T.MSG_DOWNLOADS_EMPTY)
        elif not self.filtered_records:
            self.empty_label.setText(T.MSG_DOWNLOADS_FILTER_EMPTY)
        else:
            self.empty_label.setText("")
        self.empty_label.setVisible(len(self.filtered_records) == 0)
        self.table.setVisible(len(self.filtered_records) > 0)
        self.table.setRowCount(len(self.filtered_records))
        for row, record in enumerate(self.filtered_records):
            file_name = Path(record.output_path).name
            self.table.setItem(row, 0, QTableWidgetItem(record.song_name))
            self.table.setItem(row, 1, QTableWidgetItem(file_name))
            self.table.setItem(row, 2, QTableWidgetItem(_workers.format_bytes(record.size_bytes)))
            self.table.setItem(row, 3, QTableWidgetItem(record.downloaded_at))
            self.table.setItem(row, 4, QTableWidgetItem(T.manager_status_text(record.status)))
            self.table.setItem(row, 5, QTableWidgetItem(record.output_path))
        logger.info(
            "Download manager refreshed. total=%s filtered=%s filter=%s",
            len(self.records),
            len(self.filtered_records),
            status_filter,
        )
        self._sync_action_buttons()

    def _selected_record(self) -> Optional[DownloadRecord]:
        current = self.table.currentRow()
        if current < 0 or current >= len(self.filtered_records):
            return None
        return self.filtered_records[current]

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
        self.detect_timeout_sec = int(detect_timeout_sec)
        self.download_timeout_sec = int(download_timeout_sec)
        self.download_retry_count = int(download_retry_count)
        self.download_concurrency = int(download_concurrency)
        self.setWindowTitle(T.BATCH_BTN_SETTINGS)
        self.resize(420, 240)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)

        self.detect_timeout_input = _combo_utils.build_options_combo(DETECT_TIMEOUT_OPTIONS, "s")
        _combo_utils.set_combo_value(self.detect_timeout_input, self.detect_timeout_sec)
        form.addRow(T.UI_SETTINGS_DETECT_TIMEOUT, self.detect_timeout_input)

        self.download_timeout_input = _combo_utils.build_options_combo(DOWNLOAD_TIMEOUT_OPTIONS, "s")
        _combo_utils.set_combo_value(self.download_timeout_input, self.download_timeout_sec)
        form.addRow(T.UI_SETTINGS_DOWNLOAD_TIMEOUT, self.download_timeout_input)

        self.download_retry_input = _combo_utils.build_value_combo(MIN_DOWNLOAD_RETRY_COUNT, MAX_DOWNLOAD_RETRY_COUNT, "次")
        _combo_utils.set_combo_value(self.download_retry_input, self.download_retry_count)
        form.addRow(T.UI_SETTINGS_DOWNLOAD_RETRY, self.download_retry_input)

        self.download_concurrency_input = _combo_utils.build_value_combo(
            MIN_DOWNLOAD_CONCURRENCY, MAX_DOWNLOAD_CONCURRENCY, "路"
        )
        _combo_utils.set_combo_value(self.download_concurrency_input, self.download_concurrency)
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
        self.detect_timeout_sec = max(
            MIN_DETECT_TIMEOUT_SEC,
            min(MAX_DETECT_TIMEOUT_SEC, _combo_utils.combo_int_value(self.detect_timeout_input, DEFAULT_DETECT_TIMEOUT_SEC)),
        )
        self.download_timeout_sec = max(
            MIN_DOWNLOAD_TIMEOUT_SEC,
            min(
                MAX_DOWNLOAD_TIMEOUT_SEC,
                _combo_utils.combo_int_value(self.download_timeout_input, DEFAULT_DOWNLOAD_TIMEOUT_SEC),
            ),
        )
        self.download_retry_count = max(
            MIN_DOWNLOAD_RETRY_COUNT,
            min(
                MAX_DOWNLOAD_RETRY_COUNT,
                _combo_utils.combo_int_value(self.download_retry_input, DEFAULT_DOWNLOAD_RETRY_COUNT),
            ),
        )
        self.download_concurrency = max(
            MIN_DOWNLOAD_CONCURRENCY,
            min(
                MAX_DOWNLOAD_CONCURRENCY,
                _combo_utils.combo_int_value(self.download_concurrency_input, DEFAULT_DOWNLOAD_CONCURRENCY),
            ),
        )
        self.accept()


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
        preloaded_rows: Optional[list[_workers.BatchDetectRow]] = None,
        preloaded_signature: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.cookie = cookie
        self.history_store = history_store
        self.detect_timeout_sec = max(MIN_DETECT_TIMEOUT_SEC, min(MAX_DETECT_TIMEOUT_SEC, int(detect_timeout_sec)))
        self.download_timeout_sec = max(MIN_DOWNLOAD_TIMEOUT_SEC, min(MAX_DOWNLOAD_TIMEOUT_SEC, int(download_timeout_sec)))
        self.download_retry_count = max(MIN_DOWNLOAD_RETRY_COUNT, min(MAX_DOWNLOAD_RETRY_COUNT, int(download_retry_count)))
        self.download_concurrency = max(MIN_DOWNLOAD_CONCURRENCY, min(MAX_DOWNLOAD_CONCURRENCY, int(download_concurrency)))
        self.ffmpeg_available = is_ffmpeg_available()
        self.rows: list[_workers.BatchDetectRow] = []
        self.inspect_worker: Optional[_workers.BatchInspectWorker] = None
        self.auto_detect_on_open = auto_detect_on_open
        self._last_detect_signature = ""
        self._restored_from_cache = False
        self._table_syncing = False
        self._downloading = False
        self._download_cancel_requested = False
        self._download_queue: list[_workers.BatchDetectRow] = []
        self._download_total = 0
        self._download_next_index = 0
        self._download_cursor = 0
        self._download_success = 0
        self._download_failed = 0
        self._download_canceled = 0
        self._download_workers: dict[int, _workers.DownloadWorker] = {}
        self._worker_rows: dict[int, _workers.BatchDetectRow] = {}
        self._worker_output_paths: dict[int, Path] = {}

        self.setWindowTitle(T.BATCH_DIALOG_TITLE)
        self.resize(980, 620)

        root = QVBoxLayout(self)
        desc = QLabel(T.BATCH_DIALOG_DESC)
        desc.setWordWrap(True)
        root.addWidget(desc)

        root.addWidget(QLabel(T.BATCH_INPUT_LABEL))
        self.input_edit = QPlainTextEdit()
        self.input_edit.setPlaceholderText(T.BATCH_INPUT_PLACEHOLDER)
        self.input_edit.setFixedHeight(84)
        self.input_edit.textChanged.connect(self._on_input_changed)
        if initial_input_text.strip():
            self.input_edit.setPlainText(initial_input_text.strip())
        self._sync_input_edit_height()
        root.addWidget(self.input_edit)

        form = QFormLayout()
        out_row = QHBoxLayout()
        self.out_dir_input = QLineEdit(last_download_dir or DEFAULT_DOWNLOAD_DIR)
        self.out_dir_input.setMinimumWidth(620)
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
        header.setSectionResizeMode(5, QHeaderView.Fixed)
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
        self.cancel_download_button = QPushButton(T.BATCH_BTN_CANCEL)
        self.cancel_download_button.setEnabled(False)
        self.cancel_download_button.setVisible(False)
        self.cancel_download_button.clicked.connect(self._on_cancel_download_clicked)
        back_button = QPushButton(T.BTN_BACK)
        set_back_button(back_button)
        back_button.clicked.connect(self.reject)
        button_row.addWidget(self.detect_button)
        button_row.addWidget(self.batch_settings_button)
        button_row.addWidget(self.select_all_button)
        button_row.addWidget(self.invert_select_button)
        button_row.addWidget(self.selection_summary_label)
        button_row.addWidget(self.download_button)
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
            ready_count = len([row for row in self.rows if row.status == "ready"])
            duplicate_count = len([row for row in self.rows if row.status == "duplicate"])
            bad_count = len([row for row in self.rows if row.status in {"failed", "unavailable"}])
            self.batch_progress.setRange(0, max(len(self.rows), 1))
            self.batch_progress.setValue(len(self.rows))
            self.status_label.setText(
                T.BATCH_STATUS_SUMMARY.format(
                    total=len(self.rows),
                    ready=ready_count,
                    duplicate=duplicate_count,
                    bad=bad_count,
                )
            )
            set_label_state(self.status_label, "success" if ready_count else "warning")

        self._update_detect_button_state()
        self._update_download_button_state()
        if self.auto_detect_on_open and not self._restored_from_cache and self.input_edit.toPlainText().strip():
            QTimer.singleShot(0, self._on_detect_clicked)
        QTimer.singleShot(0, self._adjust_table_columns)

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
            self.format_combo.setCurrentIndex(idx)
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

    def _selected_ready_rows(self) -> list[_workers.BatchDetectRow]:
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
            f"下载设置已更新：检测超时 {self.detect_timeout_sec}s，下载超时 {self.download_timeout_sec}s，"
            f"重试 {self.download_retry_count}，并发 {self.download_concurrency} 路。"
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
        self.inspect_worker = _workers.BatchInspectWorker(raw_text, self.cookie, timeout=self.detect_timeout_sec)
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

    def _on_detect_completed(self, rows: list[_workers.BatchDetectRow]) -> None:
        self._last_detect_signature = self._current_input_signature()
        self.rows = rows
        for row in self.rows:
            if row.status == "ready":
                row.selected = False
        self._render_rows()
        ready_count = len([row for row in rows if row.status == "ready"])
        duplicate_count = len([row for row in rows if row.status == "duplicate"])
        bad_count = len([row for row in rows if row.status in {"failed", "unavailable"}])
        self.batch_progress.setRange(0, max(len(rows), 1))
        self.batch_progress.setValue(len(rows))
        self.status_label.setText(
            T.BATCH_STATUS_SUMMARY.format(
                total=len(rows),
                ready=ready_count,
                duplicate=duplicate_count,
                bad=bad_count,
            )
        )
        set_label_state(self.status_label, "success" if ready_count else "warning")
        self._update_detect_button_state()
        self._update_download_button_state()
        QTimer.singleShot(0, self._adjust_table_columns)

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
            size_text = _workers.format_bytes(row.media_size_bytes) if row.media_size_bytes > 0 else T.MSG_UNKNOWN
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

        out_dir_raw = self.out_dir_input.text().strip()
        if not out_dir_raw:
            QMessageBox.warning(self, T.TITLE_PARAM_ERROR, T.MSG_BATCH_DOWNLOAD_NO_OUTPUT)
            return
        out_dir = Path(out_dir_raw).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        self._downloading = True
        self._download_cancel_requested = False
        self._download_queue = list(ready_rows)
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
        self.status_label.setText(f"{T.BATCH_STATUS_DOWNLOADING}（并发 {self.download_concurrency} 路）")
        set_label_state(self.status_label, "warning")
        self.input_edit.setEnabled(False)
        self.cancel_download_button.setVisible(True)
        self.cancel_download_button.setEnabled(True)
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
            worker = _workers.DownloadWorker(
                task_id=task_id,
                song_id=row.song_id,
                output_path=output_path,
                cookie=self.cookie,
                target_format=selected_format,
                timeout=self.download_timeout_sec,
                retry_count=self.download_retry_count,
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

    def _on_download_progress(self, worker: _workers.DownloadWorker, downloaded: int, total: int, speed: float) -> None:
        row = self._worker_rows.get(id(worker))
        if not row:
            return
        active_count = len(self._download_workers)
        finished = self._download_cursor
        if total > 0:
            self.status_label.setText(
                f"{T.BATCH_STATUS_DOWNLOADING} {finished}/{self._download_total}（并发中 {active_count}） - "
                f"{row.song_name or row.song_id} "
                f"({_workers.format_bytes(downloaded)}/{_workers.format_bytes(total)} {T.speed_text(_workers.format_bytes(int(speed)))})"
            )
        else:
            self.status_label.setText(
                f"{T.BATCH_STATUS_DOWNLOADING} {finished}/{self._download_total}（并发中 {active_count}） - "
                f"{row.song_name or row.song_id} "
                f"({_workers.format_bytes(downloaded)} {T.speed_text(_workers.format_bytes(int(speed)))})"
            )
        set_label_state(self.status_label, "warning")

    def _on_download_succeeded(self, worker: _workers.DownloadWorker, output_path: str, file_size: int) -> None:
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

    def _on_download_failed(self, worker: _workers.DownloadWorker, code: str, message: str) -> None:
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

    def _on_download_canceled(self, worker: _workers.DownloadWorker) -> None:
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

    def _on_download_worker_finished(self, worker: _workers.DownloadWorker) -> None:
        # Defensive cleanup: worker may finish unexpectedly without status callbacks.
        if id(worker) not in self._download_workers:
            return
        row = self._worker_rows.get(id(worker))
        if row and row.status == "downloading":
            row.status = "download_failed"
            row.selected = False
            row.message = "UNKNOWN_ERROR: 下载线程异常结束"
            self._download_failed += 1
        self._finalize_download_worker(worker)

    def _finalize_download_worker(self, worker: _workers.DownloadWorker) -> None:
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
            f"{T.BATCH_STATUS_DOWNLOADING} 已完成 {self._download_cursor}/{self._download_total}，并发中 {active_count} 路"
        )
        set_label_state(self.status_label, "warning")

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
        self._downloading = False
        self._download_cancel_requested = False
        self._download_workers = {}
        self._worker_rows = {}
        self._worker_output_paths = {}
        self._download_queue = []
        self._download_next_index = 0
        self.input_edit.setEnabled(True)
        self.cancel_download_button.setVisible(False)
        self.cancel_download_button.setEnabled(False)
        if stopped:
            self.status_label.setText(
                T.BATCH_DOWNLOAD_STOPPED.format(
                    processed=processed,
                    total=total,
                    success=self._download_success,
                    failed=self._download_failed,
                    canceled=self._download_canceled,
                    pending=pending,
                )
            )
            set_label_state(self.status_label, "warning")
        else:
            self.status_label.setText(
                T.BATCH_DOWNLOAD_SUMMARY.format(
                    success=self._download_success,
                    failed=self._download_failed,
                    canceled=self._download_canceled,
                )
            )
            set_label_state(self.status_label, "success" if self._download_failed == 0 else "warning")
        self._update_detect_button_state()
        self._update_download_button_state()


class UiSettingsDialog(QDialog):
    def __init__(
        self,
        current_font_size: int,
        detect_timeout_sec: int,
        download_timeout_sec: int,
        download_retry_count: int,
        download_concurrency: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.font_size = clamp_ui_font_size(current_font_size)
        self.detect_timeout_sec = max(MIN_DETECT_TIMEOUT_SEC, min(MAX_DETECT_TIMEOUT_SEC, int(detect_timeout_sec)))
        self.download_timeout_sec = max(
            MIN_DOWNLOAD_TIMEOUT_SEC,
            min(MAX_DOWNLOAD_TIMEOUT_SEC, int(download_timeout_sec)),
        )
        self.download_retry_count = max(
            MIN_DOWNLOAD_RETRY_COUNT,
            min(MAX_DOWNLOAD_RETRY_COUNT, int(download_retry_count)),
        )
        self.download_concurrency = max(
            MIN_DOWNLOAD_CONCURRENCY,
            min(MAX_DOWNLOAD_CONCURRENCY, int(download_concurrency)),
        )
        self.setWindowTitle(T.UI_SETTINGS_TITLE)
        self.resize(520, 320)

        layout = QVBoxLayout(self)
        desc = QLabel(T.UI_SETTINGS_DESC)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.font_size_input = _combo_utils.build_value_combo(MIN_UI_FONT_SIZE, MAX_UI_FONT_SIZE, "px")
        _combo_utils.set_combo_value(self.font_size_input, self.font_size)
        self.font_size_input.currentIndexChanged.connect(self._on_font_size_changed)
        form.addRow(T.UI_SETTINGS_FONT_SIZE, self.font_size_input)
        layout.addLayout(form)

        download_title = QLabel(T.UI_SETTINGS_DOWNLOAD_GROUP)
        set_label_state(download_title, "muted")
        layout.addWidget(download_title)
        download_form = QFormLayout()
        download_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.detect_timeout_input = _combo_utils.build_options_combo(DETECT_TIMEOUT_OPTIONS, "s")
        _combo_utils.set_combo_value(self.detect_timeout_input, self.detect_timeout_sec)
        self.detect_timeout_input.currentIndexChanged.connect(self._on_download_settings_changed)
        download_form.addRow(T.UI_SETTINGS_DETECT_TIMEOUT, self.detect_timeout_input)

        self.download_timeout_input = _combo_utils.build_options_combo(DOWNLOAD_TIMEOUT_OPTIONS, "s")
        _combo_utils.set_combo_value(self.download_timeout_input, self.download_timeout_sec)
        self.download_timeout_input.currentIndexChanged.connect(self._on_download_settings_changed)
        download_form.addRow(T.UI_SETTINGS_DOWNLOAD_TIMEOUT, self.download_timeout_input)

        self.download_retry_input = _combo_utils.build_value_combo(MIN_DOWNLOAD_RETRY_COUNT, MAX_DOWNLOAD_RETRY_COUNT, "次")
        _combo_utils.set_combo_value(self.download_retry_input, self.download_retry_count)
        self.download_retry_input.currentIndexChanged.connect(self._on_download_settings_changed)
        download_form.addRow(T.UI_SETTINGS_DOWNLOAD_RETRY, self.download_retry_input)

        self.download_concurrency_input = _combo_utils.build_value_combo(
            MIN_DOWNLOAD_CONCURRENCY, MAX_DOWNLOAD_CONCURRENCY, "路"
        )
        _combo_utils.set_combo_value(self.download_concurrency_input, self.download_concurrency)
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

    def _on_font_size_changed(self, _index: int) -> None:
        self.font_size = clamp_ui_font_size(_combo_utils.combo_int_value(self.font_size_input, DEFAULT_UI_FONT_SIZE))
        self._refresh_preview()

    def _on_download_settings_changed(self, *_args: object) -> None:
        self.detect_timeout_sec = max(
            MIN_DETECT_TIMEOUT_SEC,
            min(
                MAX_DETECT_TIMEOUT_SEC,
                _combo_utils.combo_int_value(self.detect_timeout_input, DEFAULT_DETECT_TIMEOUT_SEC),
            ),
        )
        self.download_timeout_sec = max(
            MIN_DOWNLOAD_TIMEOUT_SEC,
            min(
                MAX_DOWNLOAD_TIMEOUT_SEC,
                _combo_utils.combo_int_value(self.download_timeout_input, DEFAULT_DOWNLOAD_TIMEOUT_SEC),
            ),
        )
        self.download_retry_count = max(
            MIN_DOWNLOAD_RETRY_COUNT,
            min(
                MAX_DOWNLOAD_RETRY_COUNT,
                _combo_utils.combo_int_value(self.download_retry_input, DEFAULT_DOWNLOAD_RETRY_COUNT),
            ),
        )
        self.download_concurrency = max(
            MIN_DOWNLOAD_CONCURRENCY,
            min(
                MAX_DOWNLOAD_CONCURRENCY,
                _combo_utils.combo_int_value(self.download_concurrency_input, DEFAULT_DOWNLOAD_CONCURRENCY),
            ),
        )
        self._refresh_preview()

    def _reset_default(self) -> None:
        _combo_utils.set_combo_value(self.font_size_input, DEFAULT_UI_FONT_SIZE)
        _combo_utils.set_combo_value(self.detect_timeout_input, DEFAULT_DETECT_TIMEOUT_SEC)
        _combo_utils.set_combo_value(self.download_timeout_input, DEFAULT_DOWNLOAD_TIMEOUT_SEC)
        _combo_utils.set_combo_value(self.download_retry_input, DEFAULT_DOWNLOAD_RETRY_COUNT)
        _combo_utils.set_combo_value(self.download_concurrency_input, DEFAULT_DOWNLOAD_CONCURRENCY)
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
            ).replace("状态：", "")
        )
        set_label_state(self.preview_label, "muted")
