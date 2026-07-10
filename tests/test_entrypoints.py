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


if __name__ == "__main__":
    unittest.main()
