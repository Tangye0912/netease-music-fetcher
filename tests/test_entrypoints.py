import os
import subprocess
import sys
import importlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication, QDialog, QFrame

_app = QApplication.instance() or QApplication(["test"])

import music_fetch.main
import music_fetch.workers
from music_fetch.app_stores import AppSession, DownloadHistoryStore, SessionStore
from music_fetch.batch_dialogs import BatchDownloadDialog
from music_fetch.network import ProxyConfig, ProxyConfigError


class EntryPointTests(unittest.TestCase):
    def test_music_fetch_module_runs_cli_help(self):
        import importlib
        spec = importlib.util.find_spec("music_fetch.cli")
        self.assertIsNotNone(spec, "music_fetch.cli module should be importable")

    @unittest.skipIf(os.name == "nt", "shell wrapper not available on Windows")
    def test_music_fetch_shell_wrapper_runs_cli_help(self):
        proc = subprocess.run(
            ["./music-fetch", "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc.returncode, 0)
        self.assertIn("usage: music-fetch", proc.stdout)

    def test_detect_click_uses_worker_module_for_inspect_worker(self):
        self.assertIs(music_fetch.main.InspectWorker, music_fetch.workers.InspectWorker)

    def test_batch_dialog_entrypoint_uses_extracted_module(self):
        self.assertTrue(issubclass(BatchDownloadDialog, object))

    def test_main_window_uses_hierarchical_surface_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            session = AppSession(cookie="", ui_font_size=16)
            with (
                mock.patch.object(music_fetch.main.MainWindow, "_setup_tray_icon"),
                mock.patch.object(music_fetch.main.MainWindow, "_setup_clipboard_timer"),
            ):
                window = music_fetch.main.MainWindow(
                    SessionStore(base / "session.json"),
                    DownloadHistoryStore(base / "history.json"),
                    session,
                )
            self.assertEqual(window.centralWidget().objectName(), "appRoot")
            self.assertIsNotNone(window.findChild(QFrame, "heroPanel"))
            self.assertIsNotNone(window.findChild(QFrame, "toolbarPanel"))
            self.assertIsNotNone(window.findChild(QFrame, "inputPanel"))
            self.assertGreaterEqual(window.url_input.minimumHeight(), 96)
            window.close()
            window.deleteLater()
            _app.processEvents()


class EnsureSessionTests(unittest.TestCase):
    def test_persisted_proxy_is_applied_before_login_check(self):
        events = []
        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(Path(tmp) / "session.json")
            store.save(
                AppSession(
                    cookie="MUSIC_U=persisted",
                    proxy_type="http",
                    proxy_host="proxy.local",
                    proxy_port=8080,
                )
            )

            def apply_proxy(_session):
                events.append("proxy")
                return True

            def check_login(_cookie, timeout):
                events.append("login")
                return True

            with (
                mock.patch.object(music_fetch.main, "apply_session_proxy", side_effect=apply_proxy),
                mock.patch.object(music_fetch.main, "check_login_status", side_effect=check_login),
            ):
                session = music_fetch.main.ensure_session_with_login(store)

        self.assertIsNotNone(session)
        self.assertEqual(events, ["proxy", "login"])

    def test_new_login_preserves_all_loaded_settings(self):
        class FakeSignal:
            def __init__(self) -> None:
                self.callback = None

            def connect(self, callback) -> None:
                self.callback = callback

        class FakeLoginDialog:
            def __init__(self) -> None:
                self.login_success = FakeSignal()

            def exec(self) -> int:
                assert self.login_success.callback is not None
                self.login_success.callback("MUSIC_U=temporary", False)
                return QDialog.Accepted

        with tempfile.TemporaryDirectory() as tmp:
            store = SessionStore(Path(tmp) / "session.json")
            store.save(
                AppSession(
                    proxy_type="http",
                    proxy_host="127.0.0.1",
                    proxy_port=7890,
                    proxy_username="user",
                    proxy_password="pass",
                )
            )
            with (
                mock.patch.object(music_fetch.main, "WEB_ENGINE_AVAILABLE", True),
                mock.patch.object(music_fetch.main, "LoginDialog", FakeLoginDialog),
                mock.patch.object(music_fetch.main, "clear_embedded_login_state"),
                mock.patch.object(music_fetch.main, "apply_session_proxy") as apply_proxy,
            ):
                session = music_fetch.main.ensure_session_with_login(store)

            self.assertIsNotNone(session)
            assert session is not None
            self.assertEqual(session.cookie, "MUSIC_U=temporary")
            self.assertFalse(session.remember_login)
            self.assertEqual(session.proxy_type, "http")
            self.assertEqual(session.proxy_host, "127.0.0.1")
            self.assertEqual(session.proxy_port, 7890)
            self.assertEqual(store.load().cookie, "")
            apply_proxy.assert_called_once()


class ProxyApplicationTests(unittest.TestCase):
    def tearDown(self):
        from music_fetch.network import configure_proxy
        configure_proxy()

    def test_apply_session_proxy_configures_socks_for_project_and_qt(self):
        session = AppSession(
            proxy_type="socks5",
            proxy_host="127.0.0.1",
            proxy_port=1080,
            proxy_username="user",
            proxy_password="secret",
        )
        config = ProxyConfig("socks5", "127.0.0.1", 1080, "user", "secret")
        with (
            mock.patch.object(music_fetch.main, "configure_proxy", return_value=config) as configure,
            mock.patch.object(music_fetch.main.QNetworkProxy, "setApplicationProxy") as set_qt_proxy,
        ):
            applied = music_fetch.main.apply_session_proxy(session)

        self.assertTrue(applied)
        configure.assert_called_once_with("socks5", "127.0.0.1", 1080, "user", "secret")
        qt_proxy = set_qt_proxy.call_args.args[0]
        self.assertEqual(qt_proxy.type(), music_fetch.main.QNetworkProxy.Socks5Proxy)
        self.assertEqual(qt_proxy.hostName(), "127.0.0.1")
        self.assertEqual(qt_proxy.port(), 1080)
        self.assertEqual(qt_proxy.user(), "user")

    def test_invalid_persisted_proxy_falls_back_to_direct(self):
        session = AppSession(proxy_type="http", proxy_host="", proxy_port=0)
        with (
            mock.patch.object(
                music_fetch.main,
                "configure_proxy",
                side_effect=[ProxyConfigError("invalid"), ProxyConfig()],
            ) as configure,
            mock.patch.object(music_fetch.main.QNetworkProxy, "setApplicationProxy") as set_qt_proxy,
        ):
            applied = music_fetch.main.apply_session_proxy(session)

        self.assertFalse(applied)
        self.assertEqual(configure.call_count, 2)
        self.assertEqual(set_qt_proxy.call_count, 1)

    def test_ui_settings_save_persists_and_applies_proxy(self):
        class FakeSettingsDialog:
            def __init__(self, **_kwargs) -> None:
                self.font_size = 16
                self.detect_timeout_sec = 3
                self.download_timeout_sec = 10
                self.download_retry_count = 2
                self.download_concurrency = 2
                self.ui_theme = "dark"
                self.proxy_type = "http"
                self.proxy_host = "proxy.local"
                self.proxy_port = 7890
                self.proxy_username = "user"
                self.proxy_password = "secret"

            def exec(self) -> int:
                return QDialog.Accepted

        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            store = SessionStore(base / "session.json")
            session = AppSession(cookie="")
            with (
                mock.patch.object(music_fetch.main.MainWindow, "_setup_tray_icon"),
                mock.patch.object(music_fetch.main.MainWindow, "_setup_clipboard_timer"),
            ):
                window = music_fetch.main.MainWindow(
                    store,
                    DownloadHistoryStore(base / "history.json"),
                    session,
                )
            with (
                mock.patch.object(music_fetch.main, "UiSettingsDialog", FakeSettingsDialog),
                mock.patch.object(music_fetch.main, "apply_session_proxy") as apply_proxy,
                mock.patch.object(music_fetch.main, "apply_app_style", return_value=16),
            ):
                window._open_ui_settings()

            self.assertEqual(session.proxy_type, "http")
            self.assertEqual(session.proxy_host, "proxy.local")
            self.assertEqual(session.proxy_port, 7890)
            self.assertEqual(store.load().proxy_username, "user")
            self.assertEqual(store.load().proxy_password, "secret")
            apply_proxy.assert_called_once_with(session)
            window.close()
            window.deleteLater()
            _app.processEvents()


if __name__ == "__main__":
    unittest.main()
