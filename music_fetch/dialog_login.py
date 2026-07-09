#!/usr/bin/env python3
"""
Login dialog — embedded web login with QR code scanning.

Extracted from music_fetch.dialogs.py to reduce module size.
"""

from __future__ import annotations

from typing import Callable, Optional

from music_fetch.app_logging import get_logger
from music_fetch.app_settings import (
    NETEASE_LOGIN_URL,
)
from music_fetch.error_texts import user_error_message
from music_fetch.api import ErrorCode, MusicFetchError, build_cookie_string, check_login_status
import music_fetch.ui_texts as T

from music_fetch.gui_styles import (
    set_back_button,
    set_button_role,
)

try:
    from PySide6.QtCore import Qt, QObject, QThread, QUrl, Signal
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QDialog,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QMessageBox,
        QPushButton,
        QVBoxLayout,
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


class _TaskThread(QThread):
    """Minimal QThread that runs a callable as its task."""

    def __init__(self, task: Callable[[], None], parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._task = task

    def run(self) -> None:
        self._task()


__all__ = ['LoginDialog', 'build_cookie_from_fields', 'WEB_ENGINE_AVAILABLE']
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


class LoginDialog(QDialog):
    login_success = Signal(str, bool)
    _login_check_done = Signal(object)  # True, False, or MusicFetchError

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(T.LOGIN_DIALOG_TITLE)
        self.cookie_fields: dict[str, str] = {}
        self._pending_cookie = ""
        self._pending_remember = True
        self._login_check_thread: Optional[QThread] = None
        self._login_checking = False
        self._configure_window_size()

        root_layout = QVBoxLayout(self)
        info = QLabel(T.LOGIN_INFO)
        info.setWordWrap(True)
        root_layout.addWidget(info)

        self.remember_checkbox = QCheckBox(T.LOGIN_REMEMBER)
        self.remember_checkbox.setAccessibleName(T.ACC_BTN_REMEMBER)
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
        self.confirm_button.setAccessibleName(T.ACC_BTN_LOGIN_CONFIRM)
        self.confirm_button.clicked.connect(self._on_confirm)
        self.confirm_button.setEnabled(False)
        set_button_role(self.confirm_button, "primary")
        cancel_button = QPushButton(T.BTN_BACK)
        cancel_button.clicked.connect(self.reject)
        set_back_button(cancel_button)
        buttons.addWidget(cancel_button)
        buttons.addWidget(self.confirm_button)
        root_layout.addLayout(buttons)

        self._login_check_done.connect(self._on_login_check_done)

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
        if not self._login_checking:
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

        # Run check_login_status in a background thread to avoid blocking GUI.
        self._pending_cookie = cookie
        self._pending_remember = self.remember_checkbox.isChecked()
        self._login_checking = True
        self.confirm_button.setEnabled(False)

        def check_status() -> None:
            try:
                result = check_login_status(cookie, timeout=10)
                self._login_check_done.emit(result)
            except MusicFetchError as err:
                self._login_check_done.emit(err)
            except Exception as err:
                logger.exception("Login check unexpected error.")
                self._login_check_done.emit(
                    MusicFetchError(ErrorCode.NETWORK_ERROR, f"Unexpected error: {err}")
                )

        thread = _TaskThread(check_status)
        thread.finished.connect(thread.deleteLater)
        self._login_check_thread = thread  # prevent GC while running
        thread.start()

    def _on_login_check_done(self, result: object) -> None:
        """Handle login check result on the main thread."""
        self._login_checking = False
        self._login_check_thread = None
        self.confirm_button.setEnabled(bool(self.cookie_fields.get("MUSIC_U")))

        if isinstance(result, MusicFetchError):
            err = result
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
        else:
            is_valid = bool(result)

        if not is_valid:
            QMessageBox.warning(self, T.TITLE_LOGIN_INVALID, T.MSG_LOGIN_INVALID)
            return

        self.login_success.emit(self._pending_cookie, self._pending_remember)
        logger.info("LoginDialog confirmed success. remember_login=%s", self._pending_remember)
        self.accept()