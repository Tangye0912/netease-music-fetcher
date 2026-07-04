#!/usr/bin/env python3
"""
Application entry point.

Contains MainWindow (main UI), ensure_session_with_login (login flow), and
the top-level main() function.  Dialog classes and worker threads have been
extracted into _dialogs.py and _workers.py respectively for maintainability.
"""

from __future__ import annotations

import copy
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib import error

from PySide6.QtCore import Qt, QSize, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app_logging import default_log_path, get_logger, setup_logging
from app_settings import APP_VERSION, DEFAULT_DOWNLOAD_DIR, DOWNLOAD_HISTORY_FILE, PROJECT_GITHUB_URL, PROJECT_RELEASE_API, PROJECT_TAGS_API, SESSION_FILE
from app_stores import AppSession, DownloadHistoryStore, DownloadRecord, SessionStore
from download_tasks import TASK_STATE_CANCELED, TASK_STATE_DOWNLOADING, TASK_STATE_FAILED, TASK_STATE_PENDING, TASK_STATE_SUCCESS, DownloadTaskSnapshot, build_task_id, next_task_snapshot
from music_fetch import AccountProfile, MusicFetchError, SongDetectionResult, SUPPORTED_GUI_AUDIO_FORMATS, check_login_status, detect_song, fetch_account_profile, fetch_playlist_song_ids, is_ffmpeg_available, parse_input_resource
from error_texts import user_error_message
import ui_texts as T

# Re-export all names from extracted modules for backward compatibility.
from _batch_models import BatchDetectRow
from _workers import InspectWorker
from _gui_styles import apply_app_style, clamp_ui_font_size, set_button_role, set_label_state
from _dialogs import (
    BATCH_ROUTE_MIN_COUNT,
    WEB_ENGINE_AVAILABLE,
    LoginDialog,
    SongConfirmDialog,
    DownloadOptionsDialog,
    DownloadProgressDialog,
    DependencyManagerDialog,
    DownloadManagerDialog,
    UiSettingsDialog,
    clear_embedded_login_state,
    load_avatar_icon,
    validate_song_input,
)

logger = get_logger("music_fetch.gui")


from _version_check import version_key, fetch_latest_project_version


class MainWindow(QMainWindow):
    def __init__(self, session_store: SessionStore, history_store: DownloadHistoryStore, session: AppSession) -> None:
        super().__init__()
        self.session_store = session_store
        self.history_store = history_store
        self.session = session
        self.ffmpeg_available = is_ffmpeg_available()
        self.inspect_worker: Optional[InspectWorker] = None
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
        self.setWindowTitle(T.APP_TITLE)
        self.resize(860, 340)

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
        self.dependency_hint_label = QLabel("")
        self.dependency_hint_label.setVisible(False)
        account_row.addWidget(self.dependency_hint_label)
        self.dependency_button = QPushButton(T.BTN_DEPENDENCY_MANAGER)
        self.dependency_button.clicked.connect(self._open_dependency_manager)
        account_row.addWidget(self.dependency_button)
        self.manager_button = QPushButton(T.BTN_DOWNLOAD_MANAGER)
        self.manager_button.clicked.connect(self._open_download_manager)
        account_row.addWidget(self.manager_button)
        self.settings_button = QPushButton(T.BTN_UI_SETTINGS)
        self.settings_button.clicked.connect(self._open_ui_settings)
        account_row.addWidget(self.settings_button)
        layout.addLayout(account_row)

        description = QLabel(T.APP_DESC)
        description.setWordWrap(True)
        layout.addWidget(description)

        row = QHBoxLayout()
        self.url_input = QPlainTextEdit()
        self.url_input.setPlaceholderText(T.INPUT_PLACEHOLDER)
        self.url_input.textChanged.connect(self._on_url_input_changed)
        self.url_input.setFixedHeight(72)
        row.addWidget(self.url_input, stretch=1)
        self.detect_button = QPushButton(T.BTN_DETECT)
        self.detect_button.clicked.connect(self._on_detect_clicked)
        set_button_role(self.detect_button, "primary")
        row.addWidget(self.detect_button)
        layout.addLayout(row)

        self.input_hint_label = QLabel(T.INPUT_MULTI_HINT)
        self.input_hint_label.setWordWrap(True)
        set_label_state(self.input_hint_label, "muted")
        layout.addWidget(self.input_hint_label)

        self.input_feedback_label = QLabel("")
        self.input_feedback_label.setWordWrap(True)
        set_label_state(self.input_feedback_label, "muted")
        layout.addWidget(self.input_feedback_label)

        self.status_label = QLabel("")
        set_label_state(self.status_label, "muted")
        self.status_label.setVisible(False)
        layout.addWidget(self.status_label)

        footer_row = QHBoxLayout()
        self.version_link_label = QLabel(f'<a href="check-update">{T.FOOTER_VERSION_LINK.format(version=APP_VERSION)}</a>')
        self.version_link_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.version_link_label.setOpenExternalLinks(False)
        self.version_link_label.linkActivated.connect(self._on_version_link_activated)
        set_label_state(self.version_link_label, "muted")
        footer_row.addWidget(self.version_link_label)
        footer_row.addStretch(1)
        self.github_link_label = QLabel(f'<a href="{PROJECT_GITHUB_URL}">{T.FOOTER_GITHUB_LINK}</a>')
        self.github_link_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.github_link_label.setOpenExternalLinks(True)
        set_label_state(self.github_link_label, "muted")
        footer_row.addWidget(self.github_link_label)
        layout.addLayout(footer_row)

        self.input_analyze_timer = QTimer(self)
        self.input_analyze_timer.setSingleShot(True)
        self.input_analyze_timer.timeout.connect(self._analyze_input_after_delay)

        self._refresh_ffmpeg_status()
        self._refresh_account_profile()
        self._on_url_input_changed()
        self._setup_accessibility()

    def _setup_accessibility(self) -> None:
        self.url_input.setAccessibleName(T.ACC_INPUT_SONG_LINK)
        self.detect_button.setAccessibleName(T.ACC_BTN_DETECT)
        self.dependency_button.setAccessibleName(T.ACC_BTN_DEP_MANAGER)
        self.manager_button.setAccessibleName(T.ACC_BTN_DOWNLOAD_MANAGER)
        self.settings_button.setAccessibleName(T.ACC_BTN_UI_SETTINGS)
        self.setTabOrder(self.url_input, self.detect_button)
        self.setTabOrder(self.detect_button, self.dependency_button)
        self.setTabOrder(self.dependency_button, self.manager_button)
        self.setTabOrder(self.manager_button, self.settings_button)

    def _set_status(self, text: str, state: str) -> None:
        normalized = (text or "").strip()
        self.status_label.setVisible(bool(normalized))
        self.status_label.setText(normalized)
        if normalized:
            set_label_state(self.status_label, state)

    def _on_version_link_activated(self, _link: str) -> None:
        self._set_status(T.STATUS_CHECKING_UPDATE, "muted")
        try:
            latest_version, release_url = fetch_latest_project_version(timeout=6)
        except RuntimeError as err:
            self._set_status("", "muted")
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_UPDATE_CHECK_FAIL.format(message=str(err)))
            return
        except (error.URLError, error.HTTPError, OSError) as err:
            self._set_status("", "muted")
            QMessageBox.information(self, T.TITLE_WARNING, T.MSG_UPDATE_CHECK_FAIL.format(message=str(err)))
            return
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
        from batch_inputs import collect_batch_candidates
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
        self.nickname_label.setText(f"昵称：{profile.nickname}")
        vip_text = T.ACCOUNT_LABEL_VIP if profile.is_vip else T.ACCOUNT_LABEL_NORMAL
        self.vip_label.setText(vip_text)
        set_label_state(self.vip_label, "warning" if profile.is_vip else "muted")
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
            self._sync_detect_button_state()
            return
        try:
            profile = fetch_account_profile(self.session.cookie, timeout=10)
            self._apply_account_profile(profile)
        except MusicFetchError as err:
            logger.warning("Failed to refresh account profile. code=%s message=%s", err.code, err.message)
            self._apply_account_profile(None)
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

    def _open_batch_download(self, input_text: str = "", auto_detect_on_open: bool = False) -> None:
        from _batch_dialogs import BatchDownloadDialog
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
        self.session_store.save(self.session)
        app = QApplication.instance()
        if app is not None:
            apply_app_style(app, normalized, theme=self.session.ui_theme)
        self._set_status(
            T.status_ui_settings_updated(normalized, self.session.detect_timeout_sec, self.session.download_timeout_sec, self.session.download_retry_count, self.session.download_concurrency),
            "success",
        )
        self._on_url_input_changed()

    def _on_detect_clicked(self) -> None:
        from batch_inputs import collect_batch_candidates

        if self._detect_busy:
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
        logger.info("Detection started from GUI.")
        self.inspect_worker = InspectWorker(song_url=song_url, cookie=self.session.cookie, timeout=self.session.detect_timeout_sec)
        self.inspect_worker.failed.connect(self._on_detect_failed)
        self.inspect_worker.succeeded.connect(self._on_detect_succeeded)
        self.inspect_worker.finished.connect(lambda: self._set_detect_busy(False))
        self.inspect_worker.start()

    def _on_detect_failed(self, code: str, message: str) -> None:
        logger.warning("Detection failed. code=%s message=%s", code, message)
        mapped = user_error_message(code, message)
        if code == "AUTH_EXPIRED":
            QMessageBox.warning(self, T.TITLE_LOGIN_EXPIRED, T.detect_auth_expired(code, mapped))
        else:
            QMessageBox.warning(self, T.TITLE_DETECT_FAIL, T.code_message(code, mapped))
        self._set_status(T.STATUS_DETECT_FAILED, "error")

    def _record_download_result(self, song_id: str, song_name: str, output_path: Path, size_bytes: int, status: str, error_code: str = "") -> None:
        record = DownloadRecord(song_id=song_id, song_name=song_name or f"song-{song_id}", output_path=str(output_path), size_bytes=size_bytes, downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"), status=status, error_code=error_code)
        self.history_store.add(record)

    def _on_detect_succeeded(self, result: SongDetectionResult) -> None:
        logger.info("Detection succeeded. song_id=%s", result.song_id)
        self._set_status(T.STATUS_DETECT_DONE, "success")
        confirm = SongConfirmDialog(result)
        if confirm.exec() != QDialog.Accepted:
            self._set_status(T.STATUS_DOWNLOAD_NOT_DONE, "warning")
            return
        self._refresh_ffmpeg_status()
        if not self.ffmpeg_available:
            answer = QMessageBox.question(self, T.TITLE_DEP_MISSING, f"{T.MSG_FFMPEG_CONFIRM_MP3}\n\n{T.MSG_FFMPEG_INSTALL_GUIDE}", QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if answer != QMessageBox.Yes:
                self._set_status(T.STATUS_DOWNLOAD_NOT_DONE, "warning")
                logger.info("Download canceled before options because ffmpeg is missing.")
                return
        options = DownloadOptionsDialog(result, last_download_dir=self.session.last_download_dir)
        if options.exec() != QDialog.Accepted or not options.output_path:
            self._set_status(T.STATUS_DOWNLOAD_NOT_DONE, "warning")
            return
        self._set_latest_task_state(result.song_id, options.output_path, TASK_STATE_PENDING)
        self.session.last_download_dir = str(options.output_path.parent)
        self.session_store.save(self.session)
        self._set_latest_task_state(result.song_id, options.output_path, TASK_STATE_DOWNLOADING)
        task_id = self.latest_download_task.task_id if self.latest_download_task and self.latest_download_task.song_id == result.song_id else build_task_id(result.song_id)
        logger.info("Download task started from detect flow. task_id=%s song_id=%s", task_id, result.song_id)
        self._set_status(T.STATUS_DOWNLOADING, "warning")
        progress = DownloadProgressDialog(
            task_id=task_id, song_id=result.song_id, output_path=options.output_path,
            cookie=self.session.cookie, target_format=options.selected_format,
            timeout=self.session.download_timeout_sec, retry_count=self.session.download_retry_count,
        )
        if progress.exec() == QDialog.Accepted and progress.output_path:
            size_bytes = progress.output_path.stat().st_size if progress.output_path.exists() else 0
            self._record_download_result(song_id=result.song_id, song_name=result.song_name or "", output_path=progress.output_path, size_bytes=size_bytes, status=TASK_STATE_SUCCESS)
            self._set_latest_task_state(result.song_id, progress.output_path, TASK_STATE_SUCCESS)
            status_text = T.status_download_done(progress.output_path.name)
            self._set_status(status_text, "success")
            logger.info("GUI flow finished successfully. task_id=%s output=%s", task_id, progress.output_path)
        else:
            if progress.result_state == TASK_STATE_FAILED:
                self._set_latest_task_state(result.song_id, options.output_path, TASK_STATE_FAILED, error_code=progress.error_code)
                self._record_download_result(song_id=result.song_id, song_name=result.song_name or "", output_path=options.output_path, size_bytes=0, status=TASK_STATE_FAILED, error_code=progress.error_code)
                logger.warning("GUI flow finished with failed task. task_id=%s code=%s", task_id, progress.error_code)
            else:
                self._set_latest_task_state(result.song_id, options.output_path, TASK_STATE_CANCELED)
                self._record_download_result(song_id=result.song_id, song_name=result.song_name or "", output_path=options.output_path, size_bytes=0, status=TASK_STATE_CANCELED)
                logger.info("GUI flow finished with canceled task. task_id=%s", task_id)
            self._set_status(T.STATUS_DOWNLOAD_NOT_DONE, "warning")
            logger.info("GUI flow ended without completed download. task_id=%s", task_id)


def ensure_session_with_login(session_store: SessionStore) -> Optional[AppSession]:
    session = session_store.load()
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
    return AppSession(cookie=cookie, remember_login=remember, last_download_dir=loaded.last_download_dir, ui_font_size=loaded.ui_font_size, detect_timeout_sec=loaded.detect_timeout_sec, download_timeout_sec=loaded.download_timeout_sec, download_retry_count=loaded.download_retry_count, download_concurrency=loaded.download_concurrency)


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
    session.ui_font_size = apply_app_style(app, session.ui_font_size, theme=session.ui_theme)
    window = MainWindow(session_store=session_store, history_store=history_store, session=session)
    window.show()
    exit_code = app.exec()
    logger.info("GUI app exited. code=%s", exit_code)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
