#!/usr/bin/env python3
"""
Application entry point.

Contains MainWindow (main UI), ensure_session_with_login (login flow), and
the top-level main() function.  Dialog classes and worker threads have been
extracted into music_fetch.dialogs.py and music_fetch.workers.py respectively for maintainability.
"""

from __future__ import annotations

import copy
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
from urllib import error

from PySide6.QtCore import Qt, QObject, QSize, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QDesktopServices, QIcon
from PySide6.QtNetwork import QNetworkProxy
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from music_fetch.app_logging import default_log_path, get_logger, setup_logging
from music_fetch.app_settings import APP_VERSION, DEFAULT_DOWNLOAD_DIR, DEFAULT_GUI_TARGET_FORMAT, DOWNLOAD_HISTORY_FILE, PROJECT_GITHUB_URL, SESSION_FILE, SUPPORTED_AUDIO_FORMATS
from music_fetch.app_stores import AppSession, DownloadHistoryStore, DownloadRecord, SessionStore
from music_fetch.download_tasks import TASK_STATE_CANCELED, TASK_STATE_DOWNLOADING, TASK_STATE_FAILED, TASK_STATE_PENDING, TASK_STATE_SUCCESS, DownloadTaskSnapshot, build_task_id, next_task_snapshot
from music_fetch.api import AccountProfile, MusicFetchError, SongDetectionResult, check_login_status, fetch_account_profile, parse_input_resource
from music_fetch.audio import is_ffmpeg_available, resolve_output_path, sanitize_filename
from music_fetch.batch_models import format_bytes, format_duration
from music_fetch.error_texts import user_error_message
from music_fetch.network import ProxyConfigError, configure_proxy, get_proxy_config
import music_fetch.ui_texts as T

# Re-export all names from extracted modules for backward compatibility.
from music_fetch.batch_models import BatchDetectRow
from music_fetch.workers import DownloadWorker, InspectWorker
from music_fetch.gui_styles import apply_app_style, clamp_ui_font_size, set_button_role, set_label_state
from music_fetch.dialogs import (
    BATCH_ROUTE_MIN_COUNT,
    WEB_ENGINE_AVAILABLE,
    LoginDialog,
    SongConfirmDialog,
    DownloadOptionsDialog,
    DownloadProgressDialog,
    DependencyManagerDialog,
    DownloadManagerDialog,
    DiagnosticsDialog,
    UiSettingsDialog,
    clear_embedded_login_state,
    load_avatar_icon,
    validate_song_input,
)

logger = get_logger("music_fetch.gui")

from music_fetch.version_check import version_key, fetch_latest_project_version


class _TaskThread(QThread):
    """Minimal QThread that runs a callable as its task."""

    def __init__(self, task: Callable[[], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._task = task

    def run(self) -> None:
        self._task()


class MainWindow(QMainWindow):
    # Signals for thread-safe UI updates (emitted from worker threads,
    # connected to slots that run on the main thread).
    _version_check_done = Signal(object)   # (latest_version, release_url) or Exception
    _profile_refresh_done = Signal(object)  # AccountProfile or None

    def __init__(self, session_store: SessionStore, history_store: DownloadHistoryStore, session: AppSession) -> None:
        super().__init__()
        self.session_store = session_store
        self.history_store = history_store
        self.session = session
        self.ffmpeg_available = is_ffmpeg_available()
        self.inspect_worker: Optional[InspectWorker] = None
        self.download_worker: Optional[DownloadWorker] = None
        self.current_detection: Optional[SongDetectionResult] = None
        self._download_paused = False
        self._inline_format_guard = False
        self._inline_download_output_path: Optional[Path] = None
        self._inline_result_input = ""
        self._normal_input_height = 112
        self._compact_input_height = 64
        self._detect_button_width = 120
        self.account_profile: Optional[AccountProfile] = None
        self._avatar_error_notified = False
        self._detect_busy = False
        self._input_analysis_ready = False
        self._analysis_candidate_count = 0
        self._analysis_valid_candidate_count = 0
        self._analysis_single_valid = False
        self._batch_cached_signature = ""
        self._batch_cached_rows: list[BatchDetectRow] = []
        self.latest_download_task: Optional[DownloadTaskSnapshot] = None
        self._version_thread: Optional[QThread] = None
        self._profile_thread: Optional[QThread] = None
        self._version_check_done.connect(self._on_version_check_done)
        self._profile_refresh_done.connect(self._on_profile_refresh_done)
        self.setWindowTitle(T.APP_TITLE)
        self.setMinimumSize(860, 540)
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.availableGeometry()
            self.resize(max(860, int(geo.width() * 0.58)), max(540, int(geo.height() * 0.62)))
        else:
            self.resize(920, 580)

        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(28, 26, 28, 18)
        layout.setSpacing(16)

        hero_panel = QFrame()
        hero_panel.setObjectName("heroPanel")
        hero_panel.setMaximumHeight(150)
        hero_row = QHBoxLayout(hero_panel)
        hero_row.setContentsMargins(22, 18, 18, 18)
        hero_row.setSpacing(20)

        brand_column = QVBoxLayout()
        brand_column.setSpacing(3)
        eyebrow = QLabel(T.HOME_EYEBROW)
        eyebrow.setObjectName("brandEyebrow")
        brand_column.addWidget(eyebrow)
        title = QLabel(T.APP_TITLE)
        title.setObjectName("brandTitle")
        brand_column.addWidget(title)
        description = QLabel(T.APP_DESC)
        description.setObjectName("brandSubtitle")
        description.setWordWrap(True)
        brand_column.addWidget(description)
        hero_row.addLayout(brand_column, stretch=1)

        account_panel = QFrame()
        account_panel.setObjectName("accountPanel")
        account_row = QHBoxLayout(account_panel)
        account_row.setContentsMargins(12, 10, 14, 10)
        account_row.setSpacing(11)
        self.avatar_button = QToolButton()
        self.avatar_button.setObjectName("avatarButton")
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
        account_text.setSpacing(1)
        self.nickname_label = QLabel(T.ACCOUNT_LABEL_NICKNAME_LOGOUT)
        self.nickname_label.setObjectName("accountName")
        self.vip_label = QLabel(T.ACCOUNT_LABEL_VIP_UNKNOWN)
        self.vip_label.setObjectName("accountMeta")
        account_text.addWidget(self.nickname_label)
        account_text.addWidget(self.vip_label)
        account_row.addLayout(account_text)
        hero_row.addWidget(account_panel)
        layout.addWidget(hero_panel)

        toolbar_panel = QFrame()
        toolbar_panel.setObjectName("toolbarPanel")
        toolbar_panel.setMaximumHeight(72)
        toolbar_row = QHBoxLayout(toolbar_panel)
        toolbar_row.setContentsMargins(16, 10, 12, 10)
        toolbar_row.setSpacing(8)
        toolbar_title = QLabel(T.HOME_TOOLBAR_TITLE)
        toolbar_title.setObjectName("toolbarTitle")
        toolbar_row.addWidget(toolbar_title)
        self.dependency_hint_label = QLabel("")
        self.dependency_hint_label.setVisible(False)
        toolbar_row.addWidget(self.dependency_hint_label)
        toolbar_row.addStretch(1)
        self.search_button = QPushButton(T.SEARCH_BTN)
        self.search_button.clicked.connect(self._open_search)
        toolbar_row.addWidget(self.search_button)
        self.playlist_button = QPushButton(T.PLAYLIST_BTN_MY)
        self.playlist_button.clicked.connect(self._open_playlists)
        toolbar_row.addWidget(self.playlist_button)
        self.manager_button = QPushButton(T.BTN_DOWNLOAD_MANAGER)
        self.manager_button.clicked.connect(self._open_download_manager)
        toolbar_row.addWidget(self.manager_button)
        self.dependency_button = QPushButton(T.BTN_DEPENDENCY_MANAGER)
        self.dependency_button.clicked.connect(self._open_dependency_manager)
        toolbar_row.addWidget(self.dependency_button)
        self.diagnostics_button = QPushButton(T.BTN_DIAGNOSTICS)
        self.diagnostics_button.clicked.connect(self._open_diagnostics)
        toolbar_row.addWidget(self.diagnostics_button)
        self.settings_button = QPushButton(T.BTN_UI_SETTINGS)
        self.settings_button.clicked.connect(self._open_ui_settings)
        toolbar_row.addWidget(self.settings_button)
        layout.addWidget(toolbar_panel)

        self.input_panel = QFrame()
        self.input_panel.setObjectName("inputPanel")
        self.input_layout = QVBoxLayout(self.input_panel)
        self.input_layout.setContentsMargins(22, 19, 22, 18)
        self.input_layout.setSpacing(9)
        self.input_title = QLabel(T.HOME_INPUT_TITLE)
        self.input_title.setObjectName("sectionTitle")
        self.input_layout.addWidget(self.input_title)
        self.input_description = QLabel(T.HOME_INPUT_DESC)
        self.input_description.setObjectName("sectionSubtitle")
        self.input_description.setWordWrap(True)
        self.input_layout.addWidget(self.input_description)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.url_input = QPlainTextEdit()
        self.url_input.setObjectName("urlInput")
        self.url_input.setPlaceholderText(T.INPUT_PLACEHOLDER)
        self.url_input.textChanged.connect(self._on_url_input_changed)
        row.addWidget(self.url_input, stretch=1)
        self.detect_button = QPushButton(T.BTN_DETECT)
        self.detect_button.setObjectName("detectButton")
        self.detect_button.setAccessibleName(T.ACC_BTN_DETECT)
        self.detect_button.clicked.connect(self._on_detect_clicked)
        set_button_role(self.detect_button, "primary")
        row.addWidget(self.detect_button)
        self.input_layout.addLayout(row)

        self.input_hint_label = QLabel(T.INPUT_MULTI_HINT)
        self.input_hint_label.setWordWrap(True)
        set_label_state(self.input_hint_label, "muted")
        self.input_layout.addWidget(self.input_hint_label)

        self.input_feedback_label = QLabel("")
        self.input_feedback_label.setWordWrap(True)
        set_label_state(self.input_feedback_label, "muted")
        self.input_layout.addWidget(self.input_feedback_label)
        layout.addWidget(self.input_panel)

        self.single_panel = QFrame()
        self.single_panel.setObjectName("singlePanel")
        self.single_panel.setVisible(False)
        single_layout = QVBoxLayout(self.single_panel)
        single_layout.setContentsMargins(22, 18, 22, 18)
        single_layout.setSpacing(10)

        single_title = QLabel(T.HOME_SINGLE_TITLE)
        single_title.setObjectName("sectionTitle")
        single_layout.addWidget(single_title)
        single_description = QLabel(T.HOME_SINGLE_DESC)
        single_description.setObjectName("sectionSubtitle")
        single_description.setWordWrap(True)
        single_layout.addWidget(single_description)

        self.single_body_widget = QWidget()
        single_body_row = QHBoxLayout(self.single_body_widget)
        single_body_row.setContentsMargins(0, 0, 0, 0)
        single_body_row.setSpacing(18)

        self.single_content_widget = QWidget()
        single_content_row = QHBoxLayout(self.single_content_widget)
        single_content_row.setContentsMargins(0, 0, 0, 0)
        single_content_row.setSpacing(14)
        self.single_cover_label = QLabel("封面")
        self.single_cover_label.setObjectName("singleCover")
        self.single_cover_label.setAlignment(Qt.AlignCenter)
        self.single_cover_label.setScaledContents(True)
        single_content_row.addWidget(self.single_cover_label)

        single_info_layout = QVBoxLayout()
        single_info_layout.setSpacing(4)
        self.single_song_label = QLabel("")
        self.single_song_label.setObjectName("singleSongName")
        self.single_song_label.setWordWrap(True)
        self.single_artist_label = QLabel("")
        self.single_album_label = QLabel("")
        self.single_duration_label = QLabel("")
        self.single_availability_label = QLabel("")
        for label in (
            self.single_artist_label,
            self.single_album_label,
            self.single_duration_label,
            self.single_availability_label,
        ):
            label.setObjectName("singleMeta")
            label.setWordWrap(True)
        single_info_layout.addWidget(self.single_song_label)
        single_info_layout.addWidget(self.single_artist_label)
        single_info_layout.addWidget(self.single_album_label)
        single_info_layout.addWidget(self.single_duration_label)
        single_info_layout.addWidget(self.single_availability_label)
        single_content_row.addLayout(single_info_layout, stretch=1)
        single_body_row.addWidget(self.single_content_widget, stretch=0)

        self.single_controls_widget = QWidget()
        single_controls_layout = QVBoxLayout(self.single_controls_widget)
        single_controls_layout.setContentsMargins(0, 0, 0, 0)
        single_controls_layout.setSpacing(10)

        dir_row = QHBoxLayout()
        dir_row.setSpacing(8)
        dir_row.addWidget(QLabel(T.INLINE_DOWNLOAD_DIR))
        self.single_dir_input = QLineEdit()
        self.single_dir_input.textChanged.connect(self._refresh_inline_download_preview)
        dir_row.addWidget(self.single_dir_input, stretch=1)
        self.single_dir_button = QPushButton(T.INLINE_DOWNLOAD_PICK_DIR)
        self.single_dir_button.clicked.connect(self._pick_inline_download_dir)
        dir_row.addWidget(self.single_dir_button)
        single_controls_layout.addLayout(dir_row)

        name_row = QHBoxLayout()
        name_row.setSpacing(8)
        name_row.addWidget(QLabel(T.INLINE_DOWNLOAD_NAME))
        self.single_name_input = QLineEdit()
        self.single_name_input.textChanged.connect(self._refresh_inline_download_preview)
        name_row.addWidget(self.single_name_input, stretch=1)
        name_row.addWidget(QLabel(T.INLINE_DOWNLOAD_FORMAT))
        self.single_format_combo = QComboBox()
        self.single_format_combo.addItems([fmt.upper() for fmt in SUPPORTED_AUDIO_FORMATS])
        self.single_format_combo.setCurrentText(DEFAULT_GUI_TARGET_FORMAT.upper())
        self.single_format_combo.currentTextChanged.connect(self._on_inline_format_changed)
        name_row.addWidget(self.single_format_combo)
        single_controls_layout.addLayout(name_row)

        self.single_preview_label = QLabel("")
        self.single_preview_label.setWordWrap(True)
        set_label_state(self.single_preview_label, "muted")
        single_controls_layout.addWidget(self.single_preview_label)

        self.single_progress_bar = QProgressBar()
        self.single_progress_bar.setRange(0, 100)
        self.single_progress_bar.setValue(0)
        self.single_progress_bar.setVisible(False)
        single_controls_layout.addWidget(self.single_progress_bar)
        progress_meta_row = QHBoxLayout()
        self.single_download_status_label = QLabel("")
        self.single_download_status_label.setWordWrap(True)
        set_label_state(self.single_download_status_label, "muted")
        self.single_speed_label = QLabel("")
        set_label_state(self.single_speed_label, "muted")
        progress_meta_row.addWidget(self.single_download_status_label, stretch=1)
        progress_meta_row.addWidget(self.single_speed_label)
        single_controls_layout.addLayout(progress_meta_row)

        single_button_row = QHBoxLayout()
        single_button_row.addStretch(1)
        self.single_pause_button = QPushButton(T.DOWNLOAD_PROGRESS_PAUSE)
        self.single_pause_button.clicked.connect(self._toggle_inline_download_pause)
        self.single_pause_button.setVisible(False)
        single_button_row.addWidget(self.single_pause_button)
        self.single_cancel_button = QPushButton(T.DOWNLOAD_PROGRESS_CANCEL)
        self.single_cancel_button.clicked.connect(self._cancel_inline_download)
        self.single_cancel_button.setVisible(False)
        single_button_row.addWidget(self.single_cancel_button)
        self.single_download_button = QPushButton(T.BTN_START_DOWNLOAD)
        self.single_download_button.clicked.connect(self._start_inline_download)
        set_button_role(self.single_download_button, "primary")
        single_button_row.addWidget(self.single_download_button)
        single_controls_layout.addLayout(single_button_row)
        single_body_row.addWidget(self.single_controls_widget, stretch=1)
        single_layout.addWidget(self.single_body_widget)
        layout.addWidget(self.single_panel)

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        set_label_state(self.status_label, "muted")
        self.status_label.setMinimumHeight(24)
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        footer_row = QHBoxLayout()
        self.version_link_label = QLabel(f'<a href="check-update">{T.FOOTER_VERSION_LINK.format(version=APP_VERSION)}</a>')
        self.version_link_label.setObjectName("footerLabel")
        self.version_link_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.version_link_label.setOpenExternalLinks(False)
        self.version_link_label.linkActivated.connect(self._on_version_link_activated)
        set_label_state(self.version_link_label, "muted")
        footer_row.addWidget(self.version_link_label)
        footer_row.addStretch(1)
        self.github_link_label = QLabel(f'<a href="{PROJECT_GITHUB_URL}">{T.FOOTER_GITHUB_LINK}</a>')
        self.github_link_label.setObjectName("footerLabel")
        self.github_link_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.github_link_label.setOpenExternalLinks(True)
        set_label_state(self.github_link_label, "muted")
        footer_row.addWidget(self.github_link_label)
        layout.addLayout(footer_row)

        self.input_analyze_timer = QTimer(self)
        self.input_analyze_timer.setSingleShot(True)
        self.input_analyze_timer.timeout.connect(self._analyze_input_after_delay)

        self._tray_icon: Optional[QSystemTrayIcon] = None
        self._clipboard_timer: Optional[QTimer] = None
        self._last_clipboard_text = ""
        self._refresh_visual_metrics()
        self._refresh_ffmpeg_status()
        self._refresh_account_profile()
        self._on_url_input_changed()
        self._setup_accessibility()
        self._restore_window_geometry()
        self._setup_tray_icon()
        self._setup_clipboard_timer()

    def _refresh_visual_metrics(self) -> None:
        """Keep fixed-size controls in sync with the selected UI font size."""
        font_size = clamp_ui_font_size(self.session.ui_font_size)
        avatar_size = max(52, min(64, int(font_size * 3.8)))
        self.avatar_button.setFixedSize(avatar_size, avatar_size)
        self.avatar_button.setIconSize(QSize(avatar_size - 12, avatar_size - 12))
        input_height = max(96, min(132, int(font_size * 7.2)))
        self._normal_input_height = input_height
        self._compact_input_height = max(56, min(72, int(font_size * 4.2)))
        self._detect_button_width = max(112, int(font_size * 7.4))
        self._apply_input_density(self.single_panel.isVisible())
        cover_size = max(88, min(112, int(font_size * 6)))
        self.single_cover_label.setFixedSize(cover_size, cover_size)
        self.single_content_widget.setMinimumWidth(max(330, int(font_size * 21)))
        self.single_body_widget.setMinimumHeight(cover_size + 44)
        self.single_panel.setMinimumHeight(max(260, int(font_size * 16)))
        self.single_download_button.setMinimumSize(max(112, int(font_size * 7.4)), max(36, int(font_size * 2.4)))

    def _apply_input_density(self, compact: bool) -> None:
        input_height = self._compact_input_height if compact else self._normal_input_height
        self.url_input.setFixedHeight(input_height)
        self.detect_button.setFixedSize(self._detect_button_width, input_height)
        self.input_panel.setMaximumHeight(input_height + (52 if compact else 180))
        if compact:
            self.input_layout.setContentsMargins(22, 11, 22, 11)
        else:
            self.input_layout.setContentsMargins(22, 19, 22, 18)
        self.input_layout.setSpacing(6 if compact else 9)
        self.input_title.setVisible(not compact)
        self.input_description.setVisible(not compact)
        self.input_hint_label.setVisible(not compact)
        self.input_feedback_label.setVisible(not compact)

    def _setup_accessibility(self) -> None:
        self.url_input.setAccessibleName(T.ACC_INPUT_SONG_LINK)
        self.detect_button.setAccessibleName(T.ACC_BTN_DETECT)
        self.single_panel.setAccessibleName(T.ACC_SINGLE_RESULT)
        self.single_dir_input.setAccessibleName(T.ACC_SINGLE_DIR)
        self.single_dir_button.setAccessibleName(T.ACC_SINGLE_PICK_DIR)
        self.single_name_input.setAccessibleName(T.ACC_SINGLE_NAME)
        self.single_format_combo.setAccessibleName(T.ACC_SINGLE_FORMAT)
        self.single_download_button.setAccessibleName(T.ACC_SINGLE_DOWNLOAD)
        self.single_pause_button.setAccessibleName(T.ACC_SINGLE_PAUSE)
        self.single_cancel_button.setAccessibleName(T.ACC_SINGLE_CANCEL)
        self.dependency_button.setAccessibleName(T.ACC_BTN_DEP_MANAGER)
        self.manager_button.setAccessibleName(T.ACC_BTN_DOWNLOAD_MANAGER)
        self.diagnostics_button.setAccessibleName(T.ACC_BTN_DIAGNOSTICS)
        self.settings_button.setAccessibleName(T.ACC_BTN_UI_SETTINGS)
        self.setTabOrder(self.url_input, self.detect_button)
        self.setTabOrder(self.detect_button, self.single_dir_input)
        self.setTabOrder(self.single_dir_input, self.single_dir_button)
        self.setTabOrder(self.single_dir_button, self.single_name_input)
        self.setTabOrder(self.single_name_input, self.single_format_combo)
        self.setTabOrder(self.single_format_combo, self.single_download_button)
        self.setTabOrder(self.single_download_button, self.single_pause_button)
        self.setTabOrder(self.single_pause_button, self.single_cancel_button)
        self.setTabOrder(self.single_cancel_button, self.search_button)
        self.setTabOrder(self.search_button, self.playlist_button)
        self.setTabOrder(self.playlist_button, self.manager_button)
        self.setTabOrder(self.manager_button, self.dependency_button)
        self.setTabOrder(self.dependency_button, self.diagnostics_button)
        self.setTabOrder(self.diagnostics_button, self.settings_button)


    def _restore_window_geometry(self) -> None:
        geo_str = self.session.window_geometry
        if geo_str:
            parts = geo_str.split(",")
            if len(parts) == 4:
                try:
                    x, y, w, h = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
                    self.move(x, y)
                    self.resize(max(self.minimumWidth(), w), max(self.minimumHeight(), h))
                    logger.info("Window geometry restored. x=%s y=%s w=%s h=%s", x, y, w, h)
                except (ValueError, TypeError):
                    pass

    def _save_window_geometry(self) -> None:
        geo = self.geometry()
        self.session.window_geometry = f"{geo.x()},{geo.y()},{geo.width()},{geo.height()}"
        self.session_store.save(self.session)

    def _setup_tray_icon(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            logger.warning("System tray not available.")
            return
        self._tray_icon = QSystemTrayIcon(self)
        self._tray_icon.setToolTip(T.TRAY_TOOLTIP)
        tray_menu = QMenu(self)
        show_action = QAction(T.TRAY_SHOW, self)
        show_action.triggered.connect(self._show_from_tray)
        quit_action = QAction(T.TRAY_QUIT, self)
        quit_action.triggered.connect(self._quit_from_tray)
        tray_menu.addAction(show_action)
        tray_menu.addSeparator()
        tray_menu.addAction(quit_action)
        self._tray_icon.setContextMenu(tray_menu)
        self._tray_icon.activated.connect(self._on_tray_activated)
        self._tray_icon.show()
        logger.info("System tray icon initialized.")

    def _show_from_tray(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _quit_from_tray(self) -> None:
        self._save_window_geometry()
        if self._tray_icon:
            self._tray_icon.hide()
        QApplication.quit()

    def _on_tray_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.DoubleClick:
            self._show_from_tray()

    def _show_tray_notification(self, title: str, message: str) -> None:
        if self._tray_icon and self._tray_icon.isVisible():
            self._tray_icon.showMessage(title, message, QSystemTrayIcon.Information, 5000)

    def _setup_clipboard_timer(self) -> None:
        self._clipboard_timer = QTimer(self)
        self._clipboard_timer.setSingleShot(False)
        self._clipboard_timer.timeout.connect(self._check_clipboard)
        self._clipboard_timer.start(2000)
        self._last_clipboard_text = ""

    def _check_clipboard(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return
        text = clipboard.text().strip()
        if not text or text == self._last_clipboard_text:
            return
        self._last_clipboard_text = text
        # Only auto-fill if input is empty and text looks like a netease URL
        if self.url_input.toPlainText().strip():
            return
        from music_fetch.app_settings import SHORT_LINK_HOSTS
        from urllib import parse as url_parse
        try:
            parsed = url_parse.urlparse(text)
            host = parsed.netloc.lower()
            if "music.163.com" in host or host in SHORT_LINK_HOSTS:
                self.url_input.setPlainText(text)
                self._set_status(T.TRAY_CLIPBOARD_DETECTED, "muted")
                logger.info("Clipboard URL detected and auto-filled.")
        except (ValueError, TypeError, OSError):
            pass

    def closeEvent(self, event) -> None:
        if self._tray_icon and self._tray_icon.isVisible():
            event.ignore()
            self.hide()
            self._save_window_geometry()
            self._tray_icon.showMessage(
                T.APP_TITLE,
                T.TRAY_TOOLTIP,
                QSystemTrayIcon.Information,
                2000,
            )
        else:
            self._save_window_geometry()
            event.accept()

    def _set_status(self, text: str, state: str) -> None:
        normalized = (text or "").strip()
        self.status_label.setVisible(bool(normalized))
        self.status_label.setText(normalized)
        if normalized:
            set_label_state(self.status_label, state)

    def _on_version_link_activated(self, _link: str) -> None:
        self._set_status(T.STATUS_CHECKING_UPDATE, "muted")

        def check_and_notify() -> None:
            try:
                latest_version, release_url = fetch_latest_project_version(timeout=6)
            except (RuntimeError, error.URLError, error.HTTPError, OSError) as err:
                self._version_check_done.emit(err)
                return
            self._version_check_done.emit((latest_version, release_url))

        thread = _TaskThread(check_and_notify)
        thread.finished.connect(thread.deleteLater)
        if self._version_thread is not None and self._version_thread is not thread:
            self._version_thread = thread  # replace ref; old thread self-cleans via deleteLater
        else:
            self._version_thread = thread
        thread.start()

    def _on_version_check_done(self, result: object) -> None:
        """Handle version check result on the main thread."""
        if isinstance(result, Exception):
            self._set_status("", "muted")
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_UPDATE_CHECK_FAIL.format(message=str(result)))
            return
        result_tuple: Any = result
        latest_version, release_url = result_tuple[0], result_tuple[1]
        current_key = version_key(APP_VERSION)
        latest_key = version_key(latest_version)
        if latest_key > current_key:
            self._set_status(T.status_update_available(latest_version), "warning")
            answer = QMessageBox.question(self, T.TITLE_WARNING, T.MSG_UPDATE_AVAILABLE.format(latest=latest_version, current=APP_VERSION), QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer == QMessageBox.Yes:
                QDesktopServices.openUrl(QUrl(release_url or PROJECT_GITHUB_URL))
            return
        self._set_status(T.status_update_latest(APP_VERSION), "success")
        QMessageBox.information(self, T.TITLE_WARNING, T.MSG_UPDATE_LATEST.format(current=APP_VERSION))

    def _set_detect_busy(self, busy: bool) -> None:
        self._detect_busy = busy
        self._sync_detect_button_state()

    def _on_url_input_changed(self, *_args: object) -> None:
        raw = self.url_input.toPlainText().strip()
        if self.download_worker is None:
            self._clear_inline_single_result()
        self._input_analysis_ready = False
        self._analysis_candidate_count = 0
        self._analysis_valid_candidate_count = 0
        self._analysis_single_valid = False
        if not raw:
            self.input_analyze_timer.stop()
            self.input_feedback_label.setText("")
            set_label_state(self.input_feedback_label, "muted")
            self._sync_detect_button_state()
            return
        self.input_feedback_label.setText(T.INPUT_ANALYZING)
        set_label_state(self.input_feedback_label, "muted")
        self.input_analyze_timer.start(1000)
        self._sync_detect_button_state()

    def _analyze_input_after_delay(self) -> None:
        from music_fetch.batch_inputs import collect_batch_candidates
        raw = self.url_input.toPlainText().strip()
        if not raw:
            self._input_analysis_ready = False
            self._analysis_candidate_count = 0
            self._analysis_valid_candidate_count = 0
            self._analysis_single_valid = False
            self.input_feedback_label.setText("")
            set_label_state(self.input_feedback_label, "muted")
            self._sync_detect_button_state()
            return
        candidates = collect_batch_candidates(raw)
        self._analysis_candidate_count = len(candidates)
        self._analysis_valid_candidate_count = sum(1 for value in candidates if validate_song_input(value)[0])
        self._analysis_single_valid = False
        if len(candidates) >= BATCH_ROUTE_MIN_COUNT and self._analysis_valid_candidate_count > 0:
            self.input_feedback_label.setText(T.INPUT_DETECT_MULTIPLE.format(count=len(candidates)))
            set_label_state(self.input_feedback_label, "success")
            self._input_analysis_ready = True
            self._sync_detect_button_state()
            return
        target = candidates[0] if candidates else raw
        valid, message = validate_song_input(target)
        self._analysis_single_valid = valid
        self._input_analysis_ready = True
        if valid:
            self.input_feedback_label.setText(T.INPUT_DETECT_SINGLE)
            set_label_state(self.input_feedback_label, "success")
        else:
            self.input_feedback_label.setText(message or T.INPUT_DETECT_INVALID)
            set_label_state(self.input_feedback_label, "error")
        self._sync_detect_button_state()

    def _sync_detect_button_state(self) -> None:
        if not self._input_analysis_ready:
            self.detect_button.setEnabled(False)
            return
        if self.download_worker is not None:
            self.detect_button.setEnabled(False)
            return
        if self._analysis_candidate_count >= BATCH_ROUTE_MIN_COUNT:
            if self._analysis_valid_candidate_count <= 0:
                self.detect_button.setEnabled(False)
                return
            can_detect = bool(self.session.cookie) and not self._detect_busy
            self.detect_button.setEnabled(can_detect)
            return
        can_detect = bool(self.session.cookie) and self._analysis_single_valid and not self._detect_busy
        self.detect_button.setEnabled(can_detect)

    def _set_latest_task_state(self, song_id: str, output_path: Path, state: str, error_code: str = "") -> None:
        self.latest_download_task = next_task_snapshot(self.latest_download_task, song_id=song_id, output_path=output_path, state=state, error_code=error_code)
        logger.info("Download task state updated. task_id=%s song_id=%s state=%s error_code=%s", self.latest_download_task.task_id, self.latest_download_task.song_id, self.latest_download_task.state, self.latest_download_task.error_code)

    def _refresh_ffmpeg_status(self) -> None:
        from music_fetch.audio import invalidate_ffmpeg_cache
        invalidate_ffmpeg_cache()
        self.ffmpeg_available = is_ffmpeg_available()
        if self.ffmpeg_available:
            self.dependency_hint_label.setVisible(False)
            return
        self.dependency_hint_label.setVisible(True)
        self.dependency_hint_label.setText(T.DEPENDENCY_HINT_LIMITED)
        self.dependency_hint_label.setToolTip(T.DEPENDENCY_HINT_LIMITED_TIP)
        set_label_state(self.dependency_hint_label, "warning")

    def _apply_account_profile(self, profile: Optional[AccountProfile]) -> None:
        self.account_profile = profile
        if not profile:
            self.nickname_label.setText(T.ACCOUNT_LABEL_NICKNAME_LOGOUT)
            self.vip_label.setText(T.ACCOUNT_LABEL_VIP_UNKNOWN)
            set_label_state(self.vip_label, "muted")
            self.avatar_button.setIcon(QIcon())
            self.avatar_button.setText(T.ACCOUNT_BTN_FALLBACK)
            self.avatar_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
            return
        self.nickname_label.setText(T.nickname_text(profile.nickname))
        vip_text = T.ACCOUNT_LABEL_VIP if profile.is_vip else T.ACCOUNT_LABEL_NORMAL
        self.vip_label.setText(vip_text)
        set_label_state(self.vip_label, "warning" if profile.is_vip else "muted")
        icon = load_avatar_icon(profile.avatar_url)
        if icon:
            self.avatar_button.setIcon(icon)
            self.avatar_button.setText("")
            self.avatar_button.setToolButtonStyle(Qt.ToolButtonIconOnly)
            self.avatar_button.setIconSize(QSize(self.avatar_button.width() - 12, self.avatar_button.height() - 12))
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
            self._sync_detect_button_state()
            return

        def fetch_and_update() -> None:
            try:
                profile = fetch_account_profile(self.session.cookie, timeout=10)
                self._profile_refresh_done.emit(profile)
            except MusicFetchError as err:
                logger.warning("Failed to refresh account profile. code=%s message=%s", err.code, err.message)
                self._profile_refresh_done.emit(None)

        thread = _TaskThread(fetch_and_update)
        thread.finished.connect(thread.deleteLater)
        self._profile_thread = thread  # prevent GC while running
        thread.start()

    def _on_profile_refresh_done(self, profile: object) -> None:
        """Handle profile refresh result on the main thread."""
        self._apply_account_profile(profile)  # type: ignore[arg-type]
        self._sync_detect_button_state()

    def _on_switch_account(self) -> None:
        logger.info("User requested switch account.")
        clear_embedded_login_state()
        dialog = LoginDialog()
        dialog.login_success.connect(self._on_login_success)
        if dialog.exec() != QDialog.Accepted:
            QMessageBox.information(self, T.TITLE_SWITCH_CANCELED, T.MSG_SWITCH_CANCELED)
            logger.info("Switch account canceled; keep current session.")

    def _on_logout_account(self) -> None:
        if not self.session.cookie:
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_NOT_LOGGED_IN)
            return
        answer = QMessageBox.question(self, T.TITLE_LOGOUT, T.MSG_LOGOUT_CONFIRM, QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if answer != QMessageBox.Yes:
            return
        self.session.cookie = ""
        self.session_store.save(self.session)
        clear_embedded_login_state()
        self._apply_account_profile(None)
        self._set_status(T.STATUS_LOGOUT, "muted")
        self._sync_detect_button_state()
        logger.info("User logged out current account.")

    def _on_login_success(self, cookie: str, remember_login: bool) -> None:
        self.session.cookie = cookie
        self.session.remember_login = remember_login
        self.session_store.save(self.session)
        self._refresh_account_profile()
        logger.info("MainWindow login updated.")
        self._set_status(T.STATUS_LOGIN_UPDATED, "success")
        self._sync_detect_button_state()

    def _open_download_manager(self) -> None:
        logger.info("Open download manager.")
        dialog = DownloadManagerDialog(history_store=self.history_store, cookie=self.session.cookie, download_timeout_sec=self.session.download_timeout_sec, download_retry_count=self.session.download_retry_count, parent=self)
        dialog.exec()

    def _open_dependency_manager(self) -> None:
        logger.info("Open dependency manager.")
        dialog = DependencyManagerDialog(parent=self)
        dialog.exec()
        self._refresh_ffmpeg_status()

    def _open_diagnostics(self) -> None:
        logger.info("Open diagnostics center.")
        proxy = get_proxy_config()
        dialog = DiagnosticsDialog(
            log_path=default_log_path(),
            cookie=self.session.cookie,
            proxy_type=proxy.proxy_type,
            proxy_host=proxy.host,
            proxy_port=proxy.port,
            proxy_username=proxy.username,
            proxy_password=proxy.password,
            ffmpeg_available=self.ffmpeg_available,
            latest_task=self.latest_download_task,
            parent=self,
        )
        dialog.exec()

    def _open_search(self) -> None:
        from music_fetch.search_dialog import SearchDialog
        logger.info("Open search dialog.")
        if not self.session.cookie:
            QMessageBox.warning(self, T.TITLE_NOT_LOGIN, T.MSG_NEED_LOGIN_ANY)
            return
        dialog = SearchDialog(cookie=self.session.cookie, timeout=self.session.detect_timeout_sec, parent=self)
        if dialog.exec() == QDialog.Accepted and dialog.selected_result:
            result = dialog.selected_result
            logger.info("Search selected song_id=%s name=%s", result.song_id, result.song_name)
            self._submit_selected_input(result.song_id)

    def _submit_selected_input(self, value: str) -> None:
        """Analyze and submit an input selected from another GUI surface."""
        self.url_input.setPlainText(value)
        self.input_analyze_timer.stop()
        self._analyze_input_after_delay()
        self._on_detect_clicked()

    def _open_playlists(self) -> None:
        from music_fetch.playlist_dialog import PlaylistDialog
        logger.info("Open playlists dialog.")
        if not self.session.cookie:
            QMessageBox.warning(self, T.TITLE_NOT_LOGIN, T.MSG_NEED_LOGIN_ANY)
            return
        dialog = PlaylistDialog(cookie=self.session.cookie, timeout=self.session.detect_timeout_sec, parent=self)
        if dialog.exec() == QDialog.Accepted and dialog.selected_playlist:
            pl = dialog.selected_playlist
            logger.info("Playlist selected. id=%s name=%s", pl.playlist_id, pl.name)
            playlist_url = f"https://music.163.com/#/playlist?id={pl.playlist_id}"
            self._submit_selected_input(playlist_url)

    def _open_batch_download(self, input_text: str = "", auto_detect_on_open: bool = False) -> None:
        from music_fetch.batch_dialogs import BatchDownloadDialog
        logger.info("Open batch download dialog.")
        normalized_input = input_text.strip()
        use_cached = bool(normalized_input and normalized_input == self._batch_cached_signature and self._batch_cached_rows)
        dialog = BatchDownloadDialog(
            cookie=self.session.cookie, history_store=self.history_store,
            last_download_dir=self.session.last_download_dir,
            detect_timeout_sec=self.session.detect_timeout_sec,
            download_timeout_sec=self.session.download_timeout_sec,
            download_retry_count=self.session.download_retry_count,
            download_concurrency=self.session.download_concurrency,
            initial_input_text=input_text,
            auto_detect_on_open=auto_detect_on_open and not use_cached,
            preloaded_rows=copy.deepcopy(self._batch_cached_rows) if use_cached else None,
            preloaded_signature=self._batch_cached_signature if use_cached else "",
            parent=self,
        )
        dialog.exec()
        self.session.detect_timeout_sec = dialog.detect_timeout_sec
        self.session.download_timeout_sec = dialog.download_timeout_sec
        self.session.download_retry_count = dialog.download_retry_count
        self.session.download_concurrency = dialog.download_concurrency
        self.session_store.save(self.session)
        if dialog._last_detect_signature and dialog.rows:
            self._batch_cached_signature = dialog._last_detect_signature
            self._batch_cached_rows = copy.deepcopy(dialog.rows)

    def _open_ui_settings(self) -> None:
        logger.info("Open ui settings dialog.")
        dialog = UiSettingsDialog(
            current_font_size=self.session.ui_font_size,
            detect_timeout_sec=self.session.detect_timeout_sec,
            download_timeout_sec=self.session.download_timeout_sec,
            download_retry_count=self.session.download_retry_count,
            download_concurrency=self.session.download_concurrency,
            current_theme=self.session.ui_theme,
            proxy_type=self.session.proxy_type,
            proxy_host=self.session.proxy_host,
            proxy_port=self.session.proxy_port,
            proxy_username=self.session.proxy_username,
            proxy_password=self.session.proxy_password,
            parent=self,
        )
        if dialog.exec() != QDialog.Accepted:
            return
        normalized = clamp_ui_font_size(dialog.font_size)
        self.session.ui_font_size = normalized
        self.session.detect_timeout_sec = dialog.detect_timeout_sec
        self.session.download_timeout_sec = dialog.download_timeout_sec
        self.session.download_retry_count = dialog.download_retry_count
        self.session.download_concurrency = dialog.download_concurrency
        self.session.ui_theme = dialog.ui_theme
        self.session.proxy_type = dialog.proxy_type
        self.session.proxy_host = dialog.proxy_host
        self.session.proxy_port = dialog.proxy_port
        self.session.proxy_username = dialog.proxy_username
        self.session.proxy_password = dialog.proxy_password
        self.session_store.save(self.session)
        apply_session_proxy(self.session)
        app = QApplication.instance()
        if app is not None:
            apply_app_style(app, normalized, theme=self.session.ui_theme)  # type: ignore[arg-type]
        self._refresh_visual_metrics()
        self._set_status(
            T.status_ui_settings_updated(normalized, self.session.detect_timeout_sec, self.session.download_timeout_sec, self.session.download_retry_count, self.session.download_concurrency)
            + " "
            + T.proxy_settings_summary(
                self.session.proxy_type,
                self.session.proxy_host,
                self.session.proxy_port,
                bool(self.session.proxy_username),
            ),
            "success",
        )
        self._on_url_input_changed()

    def _on_inspect_finished(self) -> None:
        self._set_detect_busy(False)
        self.inspect_worker = None

    def _on_detect_clicked(self) -> None:
        from music_fetch.batch_inputs import collect_batch_candidates

        if self._detect_busy:
            return
        if self.download_worker is not None:
            self._set_status(T.STATUS_DOWNLOADING, "warning")
            return
        if not self._input_analysis_ready:
            return
        song_input = self.url_input.toPlainText().strip()
        candidates = collect_batch_candidates(song_input)
        if not candidates:
            QMessageBox.warning(self, T.TITLE_PARAM_ERROR, T.MSG_NEED_INPUT_URL)
            self._set_status(T.STATUS_DETECT_FAILED, "error")
            return
        has_playlist_resource = False
        for candidate in candidates:
            try:
                resource_type, _resource_id = parse_input_resource(candidate)
                if resource_type == "playlist":
                    has_playlist_resource = True
                    break
            except MusicFetchError:
                continue
        if len(candidates) >= BATCH_ROUTE_MIN_COUNT or has_playlist_resource:
            logger.info("Detect routed to batch flow. candidate_count=%s", len(candidates))
            self._set_status(T.STATUS_BATCH_ROUTE, "warning")
            self._open_batch_download(input_text=song_input, auto_detect_on_open=True)
            return
        song_url = candidates[0] if candidates else song_input
        valid, message = validate_song_input(song_url)
        if not valid:
            self.input_feedback_label.setText(message)
            set_label_state(self.input_feedback_label, "error")
            QMessageBox.warning(self, T.TITLE_PARAM_ERROR, message)
            self._set_status(T.STATUS_DETECT_FAILED, "error")
            return
        if not self.session.cookie:
            QMessageBox.warning(self, T.TITLE_NOT_LOGIN, T.MSG_NEED_LOGIN_ANY)
            self._set_status(T.MSG_NEED_LOGIN_ANY, "warning")
            return
        self._set_detect_busy(True)
        self._set_status(T.STATUS_DETECTING, "warning")
        if self.download_worker is None:
            self._clear_inline_single_result()
        logger.info("Detection started from GUI.")
        self.inspect_worker = InspectWorker(song_url=song_url, cookie=self.session.cookie, timeout=self.session.detect_timeout_sec)
        self.inspect_worker.failed.connect(self._on_detect_failed)
        self.inspect_worker.succeeded.connect(self._on_detect_succeeded)
        self.inspect_worker.finished.connect(self._on_inspect_finished)
        self.inspect_worker.finished.connect(self.inspect_worker.deleteLater)
        self.inspect_worker.start()

    def _on_detect_failed(self, code: str, message: str) -> None:
        logger.warning("Detection failed. code=%s message=%s", code, message)
        mapped = user_error_message(code, message)
        if code == "AUTH_EXPIRED":
            answer = QMessageBox.warning(
                self, T.TITLE_LOGIN_EXPIRED,
                T.detect_auth_expired(code, mapped),
                QMessageBox.Ok | QMessageBox.Cancel,
                QMessageBox.Ok,
            )
            if answer == QMessageBox.Ok:
                self._on_switch_account()
        else:
            QMessageBox.warning(self, T.TITLE_DETECT_FAIL, T.code_message(code, mapped))
        self._set_status(T.STATUS_DETECT_FAILED, "error")

    def _record_download_result(self, song_id: str, song_name: str, output_path: Path, size_bytes: int, status: str, error_code: str = "") -> None:
        record = DownloadRecord(song_id=song_id, song_name=song_name or f"song-{song_id}", output_path=str(output_path), size_bytes=size_bytes, downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), status=status, error_code=error_code)
        self.history_store.add(record)

    def _clear_inline_single_result(self) -> None:
        self.current_detection = None
        self._inline_download_output_path = None
        self._inline_result_input = ""
        self._download_paused = False
        self.single_panel.setVisible(False)
        self.single_cover_label.clear()
        self.single_cover_label.setText("封面")
        self.single_song_label.setText("")
        self.single_artist_label.setText("")
        self.single_album_label.setText("")
        self.single_duration_label.setText("")
        self.single_availability_label.setText("")
        self.single_preview_label.setText("")
        self.single_download_status_label.setText("")
        self.single_speed_label.setText("")
        self.single_progress_bar.setVisible(False)
        self.single_progress_bar.setRange(0, 100)
        self.single_progress_bar.setValue(0)
        self._apply_input_density(False)
        self._set_inline_download_active(False)

    def _show_inline_single_result(self, result: SongDetectionResult) -> None:
        self.current_detection = result
        self._inline_download_output_path = None
        self._inline_result_input = self.url_input.toPlainText().strip()
        self._download_paused = False
        self.single_panel.setVisible(True)
        self._apply_input_density(True)
        self.single_progress_bar.setVisible(False)
        self.single_progress_bar.setRange(0, 100)
        self.single_progress_bar.setValue(0)
        self.single_speed_label.setText("")
        self.single_download_status_label.setText("")
        set_label_state(self.single_download_status_label, "muted")

        self.single_cover_label.clear()
        self.single_cover_label.setText("封面")
        if result.cover_url:
            cover_icon = load_avatar_icon(result.cover_url)
            if cover_icon:
                self.single_cover_label.setPixmap(cover_icon.pixmap(self.single_cover_label.size()))
                self.single_cover_label.setText("")

        song_name = result.song_name or f"song-{result.song_id}"
        self.single_song_label.setText(song_name)
        self.single_artist_label.setText(f"{T.SONG_CONFIRM_ARTIST}：{result.artist or T.MSG_UNKNOWN}")
        self.single_album_label.setText(f"{T.SONG_CONFIRM_ALBUM}：{result.album_name or T.MSG_UNKNOWN}")
        self.single_duration_label.setText(f"{T.SONG_CONFIRM_DURATION}：{format_duration(result.duration_ms)}")
        if result.can_download:
            self.single_availability_label.setText(T.SONG_CONFIRM_CAN_DOWNLOAD)
            set_label_state(self.single_availability_label, "success")
        else:
            reason = result.unavailable_reason or T.MSG_UNKNOWN
            self.single_availability_label.setText(T.INLINE_DOWNLOAD_UNAVAILABLE.format(reason=reason))
            set_label_state(self.single_availability_label, "error")

        self.single_dir_input.setText(self.session.last_download_dir or DEFAULT_DOWNLOAD_DIR)
        self.single_name_input.setText(sanitize_filename(f"{song_name}-{result.song_id}"))
        self._refresh_ffmpeg_status()
        self._apply_inline_ffmpeg_constraints()
        self._set_inline_download_active(False)
        self._refresh_inline_download_preview()

    def _pick_inline_download_dir(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            T.DOWNLOAD_DIR_PICKER_TITLE,
            self.single_dir_input.text().strip() or DEFAULT_DOWNLOAD_DIR,
        )
        if selected:
            self.single_dir_input.setText(selected)

    def _inline_selected_format(self) -> str:
        return self.single_format_combo.currentText().lower().strip() or DEFAULT_GUI_TARGET_FORMAT

    def _set_inline_format_safely(self, value: str) -> None:
        self._inline_format_guard = True
        try:
            self.single_format_combo.setCurrentText(value)
        finally:
            self._inline_format_guard = False

    def _apply_inline_ffmpeg_constraints(self) -> None:
        model = self.single_format_combo.model()
        for idx, fmt in enumerate(SUPPORTED_AUDIO_FORMATS):
            item_getter = getattr(model, "item", None)
            item = item_getter(idx) if item_getter else None
            if item is None:
                continue
            enabled = self.ffmpeg_available or fmt == "mp3"
            item.setEnabled(enabled)
            item.setToolTip("" if enabled else T.MSG_FFMPEG_NEED_INSTALL)
        if not self.ffmpeg_available and self._inline_selected_format() != "mp3":
            self._set_inline_format_safely("MP3")

    def _on_inline_format_changed(self, value: str) -> None:
        if self._inline_format_guard:
            return
        if not self.ffmpeg_available and value.lower().strip() != "mp3":
            self._set_inline_format_safely("MP3")
            self.single_download_status_label.setText(T.MSG_FFMPEG_NEED_INSTALL)
            set_label_state(self.single_download_status_label, "warning")
        self._refresh_inline_download_preview()

    def _inline_preview_path(self) -> Optional[Path]:
        raw_dir = self.single_dir_input.text().strip()
        rename = self.single_name_input.text().strip()
        if not raw_dir or not rename:
            return None
        return Path(raw_dir).expanduser() / f"{sanitize_filename(rename)}.{self._inline_selected_format()}"

    def _refresh_inline_download_preview(self, *_args: object) -> None:
        result = self.current_detection
        if result is None:
            self.single_download_button.setEnabled(False)
            return
        preview_path = self._inline_preview_path()
        if not result.can_download:
            reason = result.unavailable_reason or T.MSG_UNKNOWN
            self.single_preview_label.setText(T.INLINE_DOWNLOAD_UNAVAILABLE.format(reason=reason))
            set_label_state(self.single_preview_label, "error")
            self.single_download_button.setEnabled(False)
            return
        if preview_path is None:
            self.single_preview_label.setText(T.DOWNLOAD_OPTIONS_HINT_PICK_DIR if not self.single_dir_input.text().strip() else T.DOWNLOAD_OPTIONS_HINT_RENAME)
            set_label_state(self.single_preview_label, "error")
            self.single_download_button.setEnabled(False)
            return
        self.single_preview_label.setText(T.INLINE_DOWNLOAD_PREVIEW.format(path=preview_path))
        set_label_state(self.single_preview_label, "muted")
        self.single_download_button.setEnabled(self.download_worker is None)

    def _set_inline_download_active(self, active: bool) -> None:
        for widget in (
            self.single_dir_input,
            self.single_dir_button,
            self.single_name_input,
            self.single_format_combo,
        ):
            widget.setEnabled(not active)
        self.single_download_button.setVisible(not active)
        self.single_pause_button.setVisible(active)
        self.single_cancel_button.setVisible(active)
        self.single_pause_button.setEnabled(active)
        self.single_cancel_button.setEnabled(active)
        if active:
            self.single_pause_button.setText(T.DOWNLOAD_PROGRESS_PAUSE)
            self.single_progress_bar.setVisible(True)
            return
        self._download_paused = False
        self.single_pause_button.setText(T.DOWNLOAD_PROGRESS_PAUSE)
        self._refresh_inline_download_preview()

    def _start_inline_download(self) -> None:
        result = self.current_detection
        if result is None or self.download_worker is not None:
            return
        if not result.can_download:
            self._refresh_inline_download_preview()
            return
        raw_dir = self.single_dir_input.text().strip()
        rename = self.single_name_input.text().strip()
        if not raw_dir or not rename:
            self._refresh_inline_download_preview()
            return
        selected_format = self._inline_selected_format()
        if selected_format not in SUPPORTED_AUDIO_FORMATS:
            self.single_download_status_label.setText(T.MSG_UNSUPPORTED_FORMAT.format(fmt=selected_format))
            set_label_state(self.single_download_status_label, "error")
            return
        if not self.ffmpeg_available and selected_format != "mp3":
            self._set_inline_format_safely("MP3")
            selected_format = "mp3"
        out_dir = Path(raw_dir).expanduser()
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            output_path = resolve_output_path(
                out_dir=out_dir,
                song_id=result.song_id,
                song_name=result.song_name,
                rename=rename,
                out_format=selected_format,
            )
        except OSError as err:
            self.single_download_status_label.setText(str(err))
            set_label_state(self.single_download_status_label, "error")
            return

        self._inline_download_output_path = output_path
        self.session.last_download_dir = str(out_dir)
        self.session_store.save(self.session)
        self._set_latest_task_state(result.song_id, output_path, TASK_STATE_PENDING)
        self._set_latest_task_state(result.song_id, output_path, TASK_STATE_DOWNLOADING)
        task_id = self.latest_download_task.task_id if self.latest_download_task else build_task_id(result.song_id)
        worker = DownloadWorker(
            task_id=task_id,
            song_id=result.song_id,
            output_path=output_path,
            cookie=self.session.cookie,
            target_format=selected_format,
            timeout=self.session.download_timeout_sec,
            retry_count=self.session.download_retry_count,
            tags={
                "title": result.song_name or "",
                "artist": result.artist,
                "album": result.album_name,
                "cover_url": result.cover_url,
            },
        )
        self.download_worker = worker
        worker.progress.connect(self._on_inline_download_progress)
        worker.succeeded.connect(self._on_inline_download_succeeded)
        worker.failed.connect(self._on_inline_download_failed)
        worker.canceled.connect(self._on_inline_download_canceled)
        worker.finished.connect(self._on_inline_download_finished)
        worker.finished.connect(worker.deleteLater)
        self.single_download_status_label.setText(T.DOWNLOAD_PROGRESS_INIT)
        set_label_state(self.single_download_status_label, "warning")
        self.single_speed_label.setText(T.DOWNLOAD_PROGRESS_SPEED)
        self._set_inline_download_active(True)
        self._set_status(T.STATUS_DOWNLOADING, "warning")
        logger.info("Inline download started. task_id=%s song_id=%s output=%s", task_id, result.song_id, output_path)
        worker.start()

    def _on_inline_download_progress(self, downloaded: int, total: int, speed: float) -> None:
        if total <= 0:
            self.single_progress_bar.setRange(0, 0)
            self.single_download_status_label.setText(T.DOWNLOAD_PROGRESS_TEXT_SIMPLE.format(downloaded=format_bytes(downloaded)))
        else:
            self.single_progress_bar.setRange(0, total)
            self.single_progress_bar.setValue(min(downloaded, total))
            self.single_download_status_label.setText(
                T.DOWNLOAD_PROGRESS_TEXT_FULL.format(downloaded=format_bytes(downloaded), total=format_bytes(total))
            )
        set_label_state(self.single_download_status_label, "warning")
        self.single_speed_label.setText(T.speed_text(format_bytes(int(speed))))

    def _inline_result_and_path(self) -> tuple[Optional[SongDetectionResult], Optional[Path]]:
        return self.current_detection, self._inline_download_output_path

    def _on_inline_download_succeeded(self, output_path: str, file_size: int) -> None:
        result, _requested_path = self._inline_result_and_path()
        if result is None:
            return
        final_path = Path(output_path)
        self._inline_download_output_path = final_path
        self._record_download_result(result.song_id, result.song_name or "", final_path, file_size, TASK_STATE_SUCCESS)
        self._set_latest_task_state(result.song_id, final_path, TASK_STATE_SUCCESS)
        self.single_progress_bar.setRange(0, max(file_size, 1))
        self.single_progress_bar.setValue(max(file_size, 1))
        status_text = T.status_download_done(final_path.name)
        self.single_download_status_label.setText(status_text)
        set_label_state(self.single_download_status_label, "success")
        self._set_status(status_text, "success")
        self._show_tray_notification(T.TRAY_DOWNLOAD_DONE, T.TRAY_DOWNLOAD_DONE_BODY.format(name=final_path.name))
        logger.info("Inline download succeeded. output=%s size=%s", final_path, file_size)

    def _on_inline_download_failed(self, code: str, message: str) -> None:
        result, output_path = self._inline_result_and_path()
        if result is None or output_path is None:
            return
        mapped = user_error_message(code, message)
        self._record_download_result(result.song_id, result.song_name or "", output_path, 0, TASK_STATE_FAILED, error_code=code)
        self._set_latest_task_state(result.song_id, output_path, TASK_STATE_FAILED, error_code=code)
        self.single_download_status_label.setText(T.code_message(code, mapped))
        set_label_state(self.single_download_status_label, "error")
        self._set_status(T.STATUS_DOWNLOAD_NOT_DONE, "warning")
        self._show_tray_notification(T.TRAY_DOWNLOAD_FAILED, code)
        logger.warning("Inline download failed. song_id=%s code=%s", result.song_id, code)

    def _on_inline_download_canceled(self) -> None:
        result, output_path = self._inline_result_and_path()
        if result is None or output_path is None:
            return
        self._record_download_result(result.song_id, result.song_name or "", output_path, 0, TASK_STATE_CANCELED)
        self._set_latest_task_state(result.song_id, output_path, TASK_STATE_CANCELED)
        self.single_download_status_label.setText(T.MSG_DOWNLOAD_CANCELED)
        set_label_state(self.single_download_status_label, "warning")
        self._set_status(T.STATUS_DOWNLOAD_NOT_DONE, "warning")
        logger.info("Inline download canceled. song_id=%s", result.song_id)

    def _on_inline_download_finished(self) -> None:
        self.download_worker = None
        if self.url_input.toPlainText().strip() != self._inline_result_input:
            self._clear_inline_single_result()
        else:
            self._set_inline_download_active(False)
        self._sync_detect_button_state()

    def _toggle_inline_download_pause(self) -> None:
        if self.download_worker is None:
            return
        if self._download_paused:
            self.download_worker.request_resume()
            self._download_paused = False
            self.single_pause_button.setText(T.DOWNLOAD_PROGRESS_PAUSE)
            self.single_download_status_label.setText(T.DOWNLOAD_PROGRESS_RESUMING)
            set_label_state(self.single_download_status_label, "warning")
            return
        self.download_worker.request_pause()
        self._download_paused = True
        self.single_pause_button.setText(T.DOWNLOAD_PROGRESS_RESUME)
        self.single_download_status_label.setText(T.INLINE_DOWNLOAD_PAUSED)
        set_label_state(self.single_download_status_label, "warning")

    def _cancel_inline_download(self) -> None:
        if self.download_worker is None:
            return
        self.single_cancel_button.setEnabled(False)
        self.single_pause_button.setEnabled(False)
        self.single_download_status_label.setText(T.INLINE_DOWNLOAD_CANCELING)
        set_label_state(self.single_download_status_label, "warning")
        self.download_worker.request_cancel()

    def _on_detect_succeeded(self, result: SongDetectionResult) -> None:
        logger.info("Detection succeeded. song_id=%s", result.song_id)
        self._set_status(T.STATUS_DETECT_DONE, "success")
        self._show_inline_single_result(result)


def apply_session_proxy(session: AppSession) -> bool:
    """Apply persisted proxy settings to project and Qt network clients."""
    try:
        config = configure_proxy(
            session.proxy_type,
            session.proxy_host,
            session.proxy_port,
            session.proxy_username,
            session.proxy_password,
        )
    except ProxyConfigError as err:
        logger.warning(
            "Invalid persisted proxy configuration; falling back to direct mode. type=%s host=%s port=%s reason=%s",
            session.proxy_type,
            session.proxy_host,
            session.proxy_port,
            err,
        )
        configure_proxy()
        QNetworkProxy.setApplicationProxy(QNetworkProxy(QNetworkProxy.DefaultProxy))
        return False

    if config.enabled:
        proxy_kind = QNetworkProxy.Socks5Proxy if config.proxy_type == "socks5" else QNetworkProxy.HttpProxy
        qt_proxy = QNetworkProxy(proxy_kind, config.host, config.port, config.username, config.password)
    else:
        qt_proxy = QNetworkProxy(QNetworkProxy.DefaultProxy)
    QNetworkProxy.setApplicationProxy(qt_proxy)
    return True


def ensure_session_with_login(session_store: SessionStore) -> Optional[AppSession]:
    session = session_store.load()
    apply_session_proxy(session)
    if session.cookie:
        try:
            if check_login_status(session.cookie, timeout=10):
                logger.info("Reused existing login session.")
                return session
        except MusicFetchError:
            logger.warning("Existing login session check failed due to network issue.")

    if not WEB_ENGINE_AVAILABLE:
        QMessageBox.warning(None, T.TITLE_DEP_MISSING, T.MSG_LOGIN_REQUIRES_WEBENGINE)
        logger.warning("Cannot continue login flow because Qt WebEngine is unavailable.")
        return None

    clear_embedded_login_state()
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
    # Keep the freshly authenticated cookie available for this process even
    # when the user chose not to persist it. Returning the loaded object also
    # preserves newer settings fields such as proxy configuration.
    loaded.cookie = cookie
    return loaded


def main() -> int:
    log_path = setup_logging(default_log_path(), level=logging.WARNING)
    app = QApplication(sys.argv)
    logger.info("GUI app started. log_path=%s", log_path)
    session_store = SessionStore(SESSION_FILE)
    history_store = DownloadHistoryStore(DOWNLOAD_HISTORY_FILE)
    session = ensure_session_with_login(session_store)
    if session is None:
        logger.info("GUI app exit due to missing session.")
        return 0
    session.ui_font_size = apply_app_style(app, session.ui_font_size, theme=session.ui_theme)
    window = MainWindow(session_store=session_store, history_store=history_store, session=session)
    window.show()
    exit_code = app.exec()
    logger.info("GUI app exited. code=%s", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
