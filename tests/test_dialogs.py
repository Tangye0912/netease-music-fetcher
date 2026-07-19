"""Tests for music_fetch.dialogs.py pure functions and dialog classes.

Covers the 7 dialog classes (LoginDialog, SongConfirmDialog,
DownloadOptionsDialog, DownloadProgressDialog, DependencyManagerDialog,
DownloadManagerDialog, UiSettingsDialog) and pure helper functions
(load_avatar_icon, build_cookie_from_fields, validate_song_input,
clamp_ui_font_size, build_app_stylesheet, etc.).
"""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

# QApplication is needed for QWidget-based dialogs; create a minimal instance.
from PySide6.QtWidgets import QApplication
_app = QApplication.instance()
if _app is None:
    _app = QApplication(["test"])

from PySide6.QtWidgets import QPushButton, QLabel, QDialog
from PySide6.QtCore import Qt

import music_fetch.dialogs
from music_fetch.gui_styles import (
    apply_app_style,
    clamp_ui_font_size,
    set_back_button,
    set_button_role,
    set_label_state,
    set_secondary_button,
)
from music_fetch.app_stores import DownloadHistoryStore, DownloadRecord
from music_fetch.download_tasks import TASK_STATE_SUCCESS, TASK_STATE_FAILED


# ---------------------------------------------------------------------------
# Pure function tests (no GUI needed beyond module-level QApplication)
# ---------------------------------------------------------------------------

class BuildCookieFromFieldsTests(unittest.TestCase):
    def test_empty_fields_returns_empty_string(self):
        self.assertEqual(music_fetch.dialogs.build_cookie_from_fields({}), "")
        self.assertEqual(music_fetch.dialogs.build_cookie_from_fields({"MUSIC_U": "  "}), "")

    def test_music_u_only(self):
        result = music_fetch.dialogs.build_cookie_from_fields({"MUSIC_U": "abc123"})
        self.assertIn("MUSIC_U=abc123", result)

    def test_music_u_and_csrf(self):
        result = music_fetch.dialogs.build_cookie_from_fields(
            {"MUSIC_U": "abc", "__csrf": "xyz"}
        )
        self.assertIn("MUSIC_U=abc", result)
        self.assertIn("__csrf=xyz", result)

    def test_extra_fields_sorted(self):
        result = music_fetch.dialogs.build_cookie_from_fields(
            {"MUSIC_U": "abc", "extra_b": "v2", "extra_a": "v1"}
        )
        parts = result.split("; ")
        self.assertIn("MUSIC_U=abc", parts)
        # extra fields should appear after MUSIC_U and __csrf, sorted
        extra_idx = [i for i, p in enumerate(parts) if p.startswith("extra_")]
        self.assertEqual(len(extra_idx), 2)
        self.assertLess(extra_idx[0], extra_idx[1])


class ValidateSongInputTests(unittest.TestCase):
    def test_empty_input(self):
        ok, msg = music_fetch.dialogs.validate_song_input("")
        self.assertFalse(ok)
        self.assertTrue(len(msg) > 0)

    def test_pure_song_id(self):
        ok, msg = music_fetch.dialogs.validate_song_input("33894312")
        self.assertTrue(ok)

    def test_bad_host(self):
        ok, msg = music_fetch.dialogs.validate_song_input("https://example.com/foo")
        self.assertFalse(ok)

    def test_netease_url_with_song_id(self):
        ok, msg = music_fetch.dialogs.validate_song_input(
            "https://music.163.com/song?id=33894312"
        )
        self.assertTrue(ok)

    def test_short_link_host(self):
        ok, msg = music_fetch.dialogs.validate_song_input("https://163cn.tv/abc")
        self.assertTrue(ok)


class LoadAvatarIconTests(unittest.TestCase):
    def test_empty_url_returns_none(self):
        self.assertIsNone(music_fetch.dialogs.load_avatar_icon(""))

    @mock.patch("music_fetch.dialogs.request.urlopen")
    def test_http_error_returns_none(self, mock_urlopen):
        from urllib.error import HTTPError
        mock_urlopen.side_effect = HTTPError(
            "http://x.com", 404, "Not Found", {}, None
        )
        result = music_fetch.dialogs.load_avatar_icon("http://x.com/avatar.png")
        self.assertIsNone(result)

    @mock.patch("music_fetch.dialogs.request.urlopen")
    def test_invalid_image_data_returns_none(self, mock_urlopen):
        mock_urlopen.return_value.__enter__.return_value.read.return_value = (
            b"not-an-image"
        )
        result = music_fetch.dialogs.load_avatar_icon("http://x.com/avatar.png")
        self.assertIsNone(result)


class ClearEmbeddedLoginStateTests(unittest.TestCase):
    def test_no_webengine_does_nothing(self):
        with mock.patch.object(music_fetch.dialogs, "WEB_ENGINE_AVAILABLE", False):
            # Should not raise
            music_fetch.dialogs.clear_embedded_login_state()


# ---------------------------------------------------------------------------
# GUI style helper tests
# ---------------------------------------------------------------------------

class StyleHelperTests(unittest.TestCase):
    def test_clamp_ui_font_size_within_range(self):
        result = clamp_ui_font_size(14)
        self.assertGreaterEqual(result, 12)
        self.assertLessEqual(result, 20)

    def test_clamp_ui_font_size_below_min(self):
        from music_fetch.app_settings import MIN_UI_FONT_SIZE
        result = clamp_ui_font_size(1)
        self.assertEqual(result, MIN_UI_FONT_SIZE)

    def test_clamp_ui_font_size_above_max(self):
        from music_fetch.app_settings import MAX_UI_FONT_SIZE
        result = clamp_ui_font_size(999)
        self.assertEqual(result, MAX_UI_FONT_SIZE)

    def test_apply_app_style_returns_normalized_size(self):
        from music_fetch.app_settings import DEFAULT_UI_FONT_SIZE
        result = apply_app_style(_app, 9999)
        self.assertLessEqual(result, 20)


class SetButtonRoleTests(unittest.TestCase):
    def test_primary_sets_default(self):
        btn = QPushButton("Test")
        set_button_role(btn, "primary")
        self.assertTrue(btn.isDefault())
        self.assertTrue(btn.autoDefault())

    def test_non_primary_clears_role(self):
        btn = QPushButton("Test")
        set_button_role(btn, None)
        self.assertFalse(btn.isDefault())

    def test_back_button(self):
        btn = QPushButton("Test")
        set_back_button(btn)
        self.assertFalse(btn.isDefault())

    def test_secondary_button(self):
        btn = QPushButton("Test")
        set_secondary_button(btn)
        self.assertFalse(btn.isDefault())

    def test_set_label_state(self):
        label = QLabel("Test")
        set_label_state(label, "success")
        self.assertEqual(label.property("state"), "success")


# ---------------------------------------------------------------------------
# Dialog class tests
# ---------------------------------------------------------------------------

class LoginDialogTests(unittest.TestCase):
    def test_creates_without_crash(self):
        dlg = music_fetch.dialogs.LoginDialog()
        self.assertIsInstance(dlg, QDialog)
        self.assertFalse(dlg.confirm_button.isEnabled())
        dlg.close()

    def test_cookie_from_fields_empty_initially(self):
        dlg = music_fetch.dialogs.LoginDialog()
        self.assertEqual(dlg.cookie_fields, {})
        dlg.close()

    def test_remember_checkbox_default_checked(self):
        dlg = music_fetch.dialogs.LoginDialog()
        self.assertTrue(dlg.remember_checkbox.isChecked())
        dlg.close()


class SongConfirmDialogTests(unittest.TestCase):
    def test_unavailable_song(self):
        from music_fetch import SongDetectionResult
        result = SongDetectionResult(
            song_id="123",
            song_name="Test Song",
            can_download=False,
            duration_ms=None,
            media_url=None,
            unavailable_reason="版权限制",
        )
        dlg = music_fetch.dialogs.SongConfirmDialog(result)
        self.assertIsInstance(dlg, QDialog)
        dlg.close()

    def test_available_song(self):
        from music_fetch import SongDetectionResult
        result = SongDetectionResult(
            song_id="123",
            song_name="Test Song",
            can_download=True,
            media_url="https://example.com/song.mp4",
            duration_ms=240000,
            unavailable_reason=None,
        )
        dlg = music_fetch.dialogs.SongConfirmDialog(result)
        self.assertIsInstance(dlg, QDialog)
        dlg.close()


class DownloadOptionsDialogTests(unittest.TestCase):
    def test_creates_with_valid_data(self):
        from music_fetch import SongDetectionResult
        result = SongDetectionResult(
            song_id="123",
            song_name="Test Song",
            can_download=True,
            duration_ms=None,
            media_url=None,
            unavailable_reason=None,
        )
        dlg = music_fetch.dialogs.DownloadOptionsDialog(
            result=result,
            last_download_dir="/tmp",
        )
        self.assertIsInstance(dlg, QDialog)
        dlg.close()

    def test_accepts_without_form_feedback(self):
        from music_fetch import SongDetectionResult
        result = SongDetectionResult(
            song_id="123",
            song_name="Test Song",
            can_download=True,
            duration_ms=None,
            media_url=None,
            unavailable_reason=None,
        )
        dlg = music_fetch.dialogs.DownloadOptionsDialog(
            result=result,
            last_download_dir="/tmp",
        )
        dlg.close()


class DownloadProgressDialogTests(unittest.TestCase):
    def test_creates_with_basic_params(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "test.mp3"
            with mock.patch("music_fetch.dialog_progress.music_fetch.workers.DownloadWorker.start"):
                dlg = music_fetch.dialogs.DownloadProgressDialog(
                    task_id="task-1",
                    song_id="123",
                    output_path=output_path,
                    cookie="MUSIC_U=test",
                    target_format="mp3",
                    timeout=5,
                    retry_count=0,
                )
                self.assertIsInstance(dlg, QDialog)
                dlg.close()

    def test_progress_signals(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "test.mp3"
            with mock.patch("music_fetch.dialog_progress.music_fetch.workers.DownloadWorker.start"):
                dlg = music_fetch.dialogs.DownloadProgressDialog(
                    task_id="task-2",
                    song_id="456",
                    output_path=output_path,
                    cookie="MUSIC_U=test",
                    target_format="mp3",
                    timeout=3,
                    retry_count=0,
                )
                # Simulate progress update
                dlg._on_progress(1024, 10240, 5120.0)
                self.assertIn("1.0KB", dlg.status_label.text())
                dlg.close()


class DependencyManagerDialogTests(unittest.TestCase):
    def test_creates_and_displays(self):
        dlg = music_fetch.dialogs.DependencyManagerDialog()
        self.assertIsInstance(dlg, QDialog)
        dlg.close()


class DownloadManagerDialogTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.history_path = Path(self.tmp_dir.name) / "history.json"
        self.history_store = DownloadHistoryStore(self.history_path)

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_creates_empty_manager(self):
        dlg = music_fetch.dialogs.DownloadManagerDialog(
            history_store=self.history_store,
            cookie="MUSIC_U=test",
            download_timeout_sec=10,
            download_retry_count=1,
        )
        self.assertIsInstance(dlg, QDialog)
        dlg.close()

    def test_creates_with_existing_records(self):
        self.history_store.add(
            DownloadRecord(
                song_id="1",
                song_name="Song 1",
                output_path="/tmp/song1.mp3",
                size_bytes=1024,
                downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=TASK_STATE_SUCCESS,
            )
        )
        dlg = music_fetch.dialogs.DownloadManagerDialog(
            history_store=self.history_store,
            cookie="MUSIC_U=test",
            download_timeout_sec=10,
            download_retry_count=1,
        )
        self.assertEqual(dlg.table.rowCount(), 1)
        dlg.close()

    def test_filter_by_status(self):
        self.history_store.add(
            DownloadRecord(
                song_id="1",
                song_name="Song 1",
                output_path="/tmp/song1.mp3",
                size_bytes=1024,
                downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=TASK_STATE_SUCCESS,
            )
        )
        self.history_store.add(
            DownloadRecord(
                song_id="2",
                song_name="Song 2",
                output_path="/tmp/song2.mp3",
                size_bytes=2048,
                downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=TASK_STATE_FAILED,
                error_code="DOWNLOAD_FAILED",
            )
        )
        dlg = music_fetch.dialogs.DownloadManagerDialog(
            history_store=self.history_store,
            cookie="MUSIC_U=test",
            download_timeout_sec=10,
            download_retry_count=1,
        )
        # Initially shows all records
        self.assertEqual(dlg.table.rowCount(), 2)
        # Switch to "failed" filter
        index = dlg.filter_combo.findData("failed")
        if index >= 0:
            dlg.filter_combo.setCurrentIndex(index)
            dlg.refresh()
            self.assertEqual(dlg.table.rowCount(), 1)
        dlg.close()


class UiSettingsDialogTests(unittest.TestCase):
    def test_creates_with_defaults(self):
        dlg = music_fetch.dialogs.UiSettingsDialog(
            current_font_size=14,
            detect_timeout_sec=5,
            download_timeout_sec=10,
            download_retry_count=1,
            download_concurrency=2,
        )
        self.assertIsInstance(dlg, QDialog)
        dlg.close()

    def test_reset_button_restores_defaults(self):
        from music_fetch.app_settings import (
            DEFAULT_UI_FONT_SIZE,
            DEFAULT_DETECT_TIMEOUT_SEC,
            DEFAULT_DOWNLOAD_TIMEOUT_SEC,
            DEFAULT_DOWNLOAD_RETRY_COUNT,
            DEFAULT_DOWNLOAD_CONCURRENCY,
        )
        dlg = music_fetch.dialogs.UiSettingsDialog(
            current_font_size=18,
            detect_timeout_sec=1,
            download_timeout_sec=3,
            download_retry_count=0,
            download_concurrency=1,
        )
        # Trigger reset
        dlg._reset_default()
        self.assertEqual(dlg.font_size, DEFAULT_UI_FONT_SIZE)
        self.assertEqual(dlg.detect_timeout_sec, DEFAULT_DETECT_TIMEOUT_SEC)
        self.assertEqual(dlg.download_timeout_sec, DEFAULT_DOWNLOAD_TIMEOUT_SEC)
        self.assertEqual(dlg.download_retry_count, DEFAULT_DOWNLOAD_RETRY_COUNT)
        self.assertEqual(dlg.download_concurrency, DEFAULT_DOWNLOAD_CONCURRENCY)
        self.assertEqual(dlg.proxy_type, "")
        self.assertFalse(dlg.proxy_host_input.isEnabled())
        dlg.close()

    def test_clamps_extreme_values(self):
        from music_fetch.app_settings import (
            MIN_UI_FONT_SIZE,
            MAX_UI_FONT_SIZE,
        )
        dlg = music_fetch.dialogs.UiSettingsDialog(
            current_font_size=9999,
            detect_timeout_sec=9999,
            download_timeout_sec=9999,
            download_retry_count=9999,
            download_concurrency=9999,
        )
        self.assertLessEqual(dlg.font_size, MAX_UI_FONT_SIZE)
        self.assertGreaterEqual(dlg.font_size, MIN_UI_FONT_SIZE)
        dlg.close()

    def test_theme_defaults_to_light(self):
        dlg = music_fetch.dialogs.UiSettingsDialog(
            current_font_size=14,
            detect_timeout_sec=5,
            download_timeout_sec=10,
            download_retry_count=1,
            download_concurrency=2,
        )
        self.assertEqual(dlg.ui_theme, "light")
        dlg.close()

    def test_theme_dark(self):
        dlg = music_fetch.dialogs.UiSettingsDialog(
            current_font_size=14,
            detect_timeout_sec=5,
            download_timeout_sec=10,
            download_retry_count=1,
            download_concurrency=2,
            current_theme="dark",
        )
        self.assertEqual(dlg.ui_theme, "dark")
        dlg.close()

    def test_theme_invalid_falls_back(self):
        dlg = music_fetch.dialogs.UiSettingsDialog(
            current_font_size=14,
            detect_timeout_sec=5,
            download_timeout_sec=10,
            download_retry_count=1,
            download_concurrency=2,
            current_theme="invalid",
        )
        self.assertEqual(dlg.ui_theme, "dark")
        dlg.close()

    def test_proxy_defaults_to_direct_with_fields_disabled(self):
        dlg = music_fetch.dialogs.UiSettingsDialog(
            current_font_size=14,
            detect_timeout_sec=5,
            download_timeout_sec=10,
            download_retry_count=1,
            download_concurrency=2,
        )
        self.assertEqual(dlg.proxy_type_combo.currentData(), "")
        self.assertFalse(dlg.proxy_host_input.isEnabled())
        self.assertFalse(dlg.proxy_port_input.isEnabled())
        dlg.close()

    def test_proxy_existing_socks5_settings_are_loaded(self):
        dlg = music_fetch.dialogs.UiSettingsDialog(
            current_font_size=14,
            detect_timeout_sec=5,
            download_timeout_sec=10,
            download_retry_count=1,
            download_concurrency=2,
            proxy_type="socks5",
            proxy_host="127.0.0.1",
            proxy_port=1080,
            proxy_username="user",
            proxy_password="secret",
        )
        self.assertEqual(dlg.proxy_type_combo.currentData(), "socks5")
        self.assertTrue(dlg.proxy_host_input.isEnabled())
        self.assertEqual(dlg.proxy_host_input.text(), "127.0.0.1")
        self.assertEqual(dlg.proxy_port_input.value(), 1080)
        self.assertEqual(dlg.proxy_password_input.text(), "secret")
        self.assertIn("SOCKS5", dlg.preview_label.text())
        dlg.close()

    def test_proxy_invalid_settings_block_accept(self):
        dlg = music_fetch.dialogs.UiSettingsDialog(
            current_font_size=14,
            detect_timeout_sec=5,
            download_timeout_sec=10,
            download_retry_count=1,
            download_concurrency=2,
        )
        dlg.proxy_type_combo.setCurrentIndex(dlg.proxy_type_combo.findData("http"))
        dlg.proxy_host_input.setText("https://proxy.local/path")
        with mock.patch("music_fetch.dialogs.QMessageBox.warning") as warning:
            dlg.accept()
        warning.assert_called_once()
        self.assertNotEqual(dlg.result(), QDialog.Accepted)
        dlg.close()

    def test_proxy_valid_settings_are_normalized_on_accept(self):
        dlg = music_fetch.dialogs.UiSettingsDialog(
            current_font_size=14,
            detect_timeout_sec=5,
            download_timeout_sec=10,
            download_retry_count=1,
            download_concurrency=2,
        )
        dlg.proxy_type_combo.setCurrentIndex(dlg.proxy_type_combo.findData("http"))
        dlg.proxy_host_input.setText(" proxy.local ")
        dlg.proxy_port_input.setValue(7890)
        dlg.proxy_username_input.setText(" user ")
        dlg.proxy_password_input.setText("secret")

        dlg.accept()

        self.assertEqual(dlg.result(), QDialog.Accepted)
        self.assertEqual(dlg.proxy_type, "http")
        self.assertEqual(dlg.proxy_host, "proxy.local")
        self.assertEqual(dlg.proxy_port, 7890)
        self.assertEqual(dlg.proxy_username, "user")
        self.assertEqual(dlg.proxy_password, "secret")


if __name__ == "__main__":
    unittest.main()
