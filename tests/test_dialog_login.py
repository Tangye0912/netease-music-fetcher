"""Tests for dialog_login.py — build_cookie_from_fields and LoginDialog logic."""
import unittest
from unittest import mock

from PySide6.QtWidgets import QApplication
_app = QApplication.instance()
if _app is None:
    _app = QApplication(["test"])

from music_fetch.api import MusicFetchError
from music_fetch.dialog_login import LoginDialog, build_cookie_from_fields


class BuildCookieFromFieldsTests(unittest.TestCase):
    def test_music_u_only(self):
        result = build_cookie_from_fields({"MUSIC_U": "abc"})
        self.assertEqual(result, "MUSIC_U=abc")

    def test_music_u_and_csrf(self):
        result = build_cookie_from_fields({"MUSIC_U": "abc", "__csrf": "def"})
        self.assertEqual(result, "MUSIC_U=abc; __csrf=def")

    def test_extra_fields_appended_sorted(self):
        result = build_cookie_from_fields({"MUSIC_U": "abc", "NMTID": "xyz", "__csrf": "def"})
        # MUSIC_U and __csrf first, then NMTID sorted
        self.assertEqual(result, "MUSIC_U=abc; __csrf=def; NMTID=xyz")

    def test_no_music_u_returns_empty(self):
        self.assertEqual(build_cookie_from_fields({"__csrf": "def"}), "")

    def test_empty_dict(self):
        self.assertEqual(build_cookie_from_fields({}), "")

    def test_strips_whitespace(self):
        result = build_cookie_from_fields({"MUSIC_U": "  abc  "})
        self.assertEqual(result, "MUSIC_U=abc")

    def test_skips_empty_values(self):
        result = build_cookie_from_fields({"MUSIC_U": "abc", "NMTID": ""})
        self.assertEqual(result, "MUSIC_U=abc")


class LoginDialogInitTests(unittest.TestCase):
    def setUp(self):
        self.dialog = LoginDialog()

    def tearDown(self):
        self.dialog.close()
        self.dialog.deleteLater()

    def test_initial_state(self):
        self.assertFalse(self.dialog._login_checking)
        self.assertEqual(self.dialog._pending_cookie, "")
        self.assertTrue(self.dialog._pending_remember)
        self.assertIsNone(self.dialog._login_check_thread)
        self.assertFalse(self.dialog.confirm_button.isEnabled())

    def test_close_releases_web_engine_objects(self):
        if not hasattr(self.dialog, "web_page"):
            self.skipTest("Qt WebEngine is unavailable")
        self.dialog.close()
        self.assertIsNone(self.dialog.web_view)
        self.assertIsNone(self.dialog.web_page)

    def test_login_checking_flag_on_confirm(self):
        """Verify _login_checking is set during confirm (with mocked thread)."""
        self.dialog.cookie_fields["MUSIC_U"] = "test_token"
        self.dialog.cookie_fields["__csrf"] = "csrf_val"
        self.dialog.confirm_button.setEnabled(True)

        # Mock _TaskThread to prevent actual thread start
        with mock.patch("music_fetch.dialog_login._TaskThread") as mock_thread_cls:
            mock_thread = mock.MagicMock()
            mock_thread_cls.return_value = mock_thread
            self.dialog._on_confirm()

        self.assertTrue(self.dialog._login_checking)
        self.assertFalse(self.dialog.confirm_button.isEnabled())
        self.assertEqual(self.dialog._pending_cookie, "MUSIC_U=test_token; __csrf=csrf_val")
        mock_thread.start.assert_called_once()

    def test_on_login_check_done_resets_flag(self):
        self.dialog._login_checking = True
        self.dialog._pending_cookie = "MUSIC_U=test"
        self.dialog._pending_remember = True
        self.dialog.cookie_fields["MUSIC_U"] = "test"

        self.dialog._on_login_check_done(True)

        self.assertFalse(self.dialog._login_checking)
        self.assertTrue(self.dialog.confirm_button.isEnabled())

    def test_on_login_check_done_with_error_shows_dialog(self):
        self.dialog._login_checking = True
        self.dialog.cookie_fields["MUSIC_U"] = "test"
        err = MusicFetchError("NETWORK_ERROR", "timeout")

        with mock.patch("music_fetch.dialog_login.QMessageBox.question", return_value=0):
            # 0 = QMessageBox.No
            self.dialog._on_login_check_done(err)

        self.assertFalse(self.dialog._login_checking)

    def test_on_login_check_done_false_shows_warning(self):
        self.dialog._login_checking = True
        self.dialog.cookie_fields["MUSIC_U"] = "test"

        with mock.patch("music_fetch.dialog_login.QMessageBox.warning"):
            self.dialog._on_login_check_done(False)

        self.assertFalse(self.dialog._login_checking)

    def test_on_login_check_done_success_emits_and_accepts(self):
        self.dialog._login_checking = True
        self.dialog._pending_cookie = "MUSIC_U=test"
        self.dialog._pending_remember = False
        self.dialog.cookie_fields["MUSIC_U"] = "test"

        emitted = []
        self.dialog.login_success.connect(lambda c, r: emitted.append((c, r)))

        with mock.patch.object(self.dialog, "accept"):
            self.dialog._on_login_check_done(True)

        self.assertEqual(emitted, [("MUSIC_U=test", False)])

    def test_cookie_added_updates_button_when_not_checking(self):
        mock_cookie = mock.MagicMock()
        mock_cookie.name.return_value = b"MUSIC_U"
        mock_cookie.value.return_value = b"token123"

        self.dialog._on_cookie_added(mock_cookie)

        self.assertEqual(self.dialog.cookie_fields["MUSIC_U"], "token123")
        self.assertTrue(self.dialog.confirm_button.isEnabled())

    def test_cookie_added_does_not_update_button_when_checking(self):
        self.dialog._login_checking = True
        self.dialog.confirm_button.setEnabled(False)

        mock_cookie = mock.MagicMock()
        mock_cookie.name.return_value = b"MUSIC_U"
        mock_cookie.value.return_value = b"token123"

        self.dialog._on_cookie_added(mock_cookie)

        self.assertEqual(self.dialog.cookie_fields["MUSIC_U"], "token123")
        # Button should remain disabled during checking
        self.assertFalse(self.dialog.confirm_button.isEnabled())


if __name__ == "__main__":
    unittest.main()
