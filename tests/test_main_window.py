import copy
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PySide6.QtWidgets import QApplication, QDialog

import music_fetch.main
from music_fetch.api import SongDetectionResult
from music_fetch.app_stores import AppSession, DownloadHistoryStore, SessionStore
from music_fetch.download_tasks import (
    TASK_STATE_CANCELED,
    TASK_STATE_FAILED,
    TASK_STATE_SUCCESS,
)

_app = QApplication.instance() or QApplication(["test"])


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks = []

    def connect(self, callback) -> None:
        self.callbacks.append(callback)


class _FakeInspectWorker:
    instances = []

    def __init__(self, *, song_url: str, cookie: str, timeout: int) -> None:
        self.song_url = song_url
        self.cookie = cookie
        self.timeout = timeout
        self.failed = _FakeSignal()
        self.succeeded = _FakeSignal()
        self.finished = _FakeSignal()
        self.started = False
        self.instances.append(self)

    def start(self) -> None:
        self.started = True

    def deleteLater(self) -> None:
        pass


class MainWindowBehaviorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp_dir.cleanup)
        self.base = Path(self.tmp_dir.name)
        self.session_store = SessionStore(self.base / "session.json")
        self.history_store = DownloadHistoryStore(self.base / "history.json")
        self.session = AppSession(cookie="MUSIC_U=test", ui_font_size=16)
        self.patchers = [
            mock.patch.object(music_fetch.main.MainWindow, "_setup_tray_icon"),
            mock.patch.object(music_fetch.main.MainWindow, "_setup_clipboard_timer"),
            mock.patch.object(music_fetch.main.MainWindow, "_refresh_account_profile"),
            mock.patch.object(music_fetch.main, "is_ffmpeg_available", return_value=True),
        ]
        for patcher in self.patchers:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.window = music_fetch.main.MainWindow(
            self.session_store,
            self.history_store,
            self.session,
        )
        self.addCleanup(self._close_window)
        _FakeInspectWorker.instances.clear()

    def _close_window(self) -> None:
        self.window.close()
        self.window.deleteLater()
        _app.processEvents()

    @staticmethod
    def _result() -> SongDetectionResult:
        return SongDetectionResult(
            song_id="42",
            song_name="Test Song",
            duration_ms=120_000,
            media_url="https://example.com/song.mp3",
            can_download=True,
            unavailable_reason=None,
            artist="Artist",
            album_name="Album",
        )

    def _run_download_result(
        self,
        state: str,
        *,
        error_code: str = "",
    ) -> tuple[Path, mock.MagicMock]:
        output_path = self.base / "downloads" / "test-song.mp3"
        if state == TASK_STATE_SUCCESS:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(b"audio")

        class FakeConfirmDialog:
            def __init__(self, _result: SongDetectionResult) -> None:
                pass

            def exec(self) -> int:
                return QDialog.Accepted

        class FakeOptionsDialog:
            def __init__(self, _result: SongDetectionResult, *, last_download_dir: str) -> None:
                self.output_path = output_path
                self.selected_format = "mp3"

            def exec(self) -> int:
                return QDialog.Accepted

        class FakeProgressDialog:
            def __init__(self, **_kwargs) -> None:
                self.output_path = output_path if state == TASK_STATE_SUCCESS else None
                self.result_state = state
                self.error_code = error_code

            def exec(self) -> int:
                return QDialog.Accepted if state == TASK_STATE_SUCCESS else QDialog.Rejected

        with (
            mock.patch.object(music_fetch.main, "SongConfirmDialog", FakeConfirmDialog),
            mock.patch.object(music_fetch.main, "DownloadOptionsDialog", FakeOptionsDialog),
            mock.patch.object(music_fetch.main, "DownloadProgressDialog", FakeProgressDialog),
            mock.patch.object(self.window, "_refresh_ffmpeg_status"),
            mock.patch.object(self.window, "_show_tray_notification") as notify,
        ):
            self.window._on_detect_succeeded(self._result())
        return output_path, notify

    def test_search_selection_is_analyzed_and_starts_detection(self) -> None:
        class FakeSearchDialog:
            def __init__(self, **_kwargs) -> None:
                self.selected_result = SimpleNamespace(song_id="42", song_name="Test Song")

            def exec(self) -> int:
                return QDialog.Accepted

        with (
            mock.patch("music_fetch.search_dialog.SearchDialog", FakeSearchDialog),
            mock.patch.object(music_fetch.main, "InspectWorker", _FakeInspectWorker),
        ):
            self.window._open_search()

        self.assertEqual(self.window.url_input.toPlainText(), "42")
        self.assertTrue(self.window._input_analysis_ready)
        self.assertFalse(self.window.input_analyze_timer.isActive())
        self.assertEqual(len(_FakeInspectWorker.instances), 1)
        worker = _FakeInspectWorker.instances[0]
        self.assertEqual(worker.song_url, "42")
        self.assertTrue(worker.started)
        self.assertTrue(self.window._detect_busy)

    def test_playlist_selection_is_analyzed_and_routes_to_batch(self) -> None:
        class FakePlaylistDialog:
            def __init__(self, **_kwargs) -> None:
                self.selected_playlist = SimpleNamespace(playlist_id="987", name="My Playlist")

            def exec(self) -> int:
                return QDialog.Accepted

        with (
            mock.patch("music_fetch.playlist_dialog.PlaylistDialog", FakePlaylistDialog),
            mock.patch.object(self.window, "_open_batch_download") as open_batch,
        ):
            self.window._open_playlists()

        playlist_url = "https://music.163.com/#/playlist?id=987"
        self.assertEqual(self.window.url_input.toPlainText(), playlist_url)
        self.assertTrue(self.window._input_analysis_ready)
        self.assertFalse(self.window.input_analyze_timer.isActive())
        open_batch.assert_called_once_with(
            input_text=playlist_url,
            auto_detect_on_open=True,
        )

    def test_single_song_detection_starts_worker_and_sets_busy_state(self) -> None:
        self.window.url_input.setPlainText("123456")
        self.window._analyze_input_after_delay()
        with mock.patch.object(music_fetch.main, "InspectWorker", _FakeInspectWorker):
            self.window._on_detect_clicked()

        worker = _FakeInspectWorker.instances[0]
        self.assertEqual(worker.cookie, "MUSIC_U=test")
        self.assertEqual(worker.timeout, self.session.detect_timeout_sec)
        self.assertTrue(worker.started)
        self.assertIs(self.window.inspect_worker, worker)
        self.assertTrue(self.window._detect_busy)
        self.assertFalse(self.window.detect_button.isEnabled())

    def test_multiple_inputs_route_to_batch_without_starting_worker(self) -> None:
        raw = "123456\n654321"
        self.window.url_input.setPlainText(raw)
        self.window._analyze_input_after_delay()
        with (
            mock.patch.object(self.window, "_open_batch_download") as open_batch,
            mock.patch.object(music_fetch.main, "InspectWorker", _FakeInspectWorker),
        ):
            self.window._on_detect_clicked()

        open_batch.assert_called_once_with(input_text=raw, auto_detect_on_open=True)
        self.assertEqual(_FakeInspectWorker.instances, [])
        self.assertFalse(self.window._detect_busy)

    def test_rejected_settings_dialog_preserves_session(self) -> None:
        original = copy.deepcopy(self.session)

        class FakeSettingsDialog:
            def __init__(self, **_kwargs) -> None:
                pass

            def exec(self) -> int:
                return QDialog.Rejected

        with (
            mock.patch.object(music_fetch.main, "UiSettingsDialog", FakeSettingsDialog),
            mock.patch.object(self.session_store, "save") as save,
            mock.patch.object(music_fetch.main, "apply_session_proxy") as apply_proxy,
        ):
            self.window._open_ui_settings()

        self.assertEqual(self.session, original)
        save.assert_not_called()
        apply_proxy.assert_not_called()

    def test_successful_download_records_history_and_latest_task(self) -> None:
        output_path, notify = self._run_download_result(TASK_STATE_SUCCESS)

        records = self.history_store.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, TASK_STATE_SUCCESS)
        self.assertEqual(records[0].size_bytes, 5)
        self.assertEqual(records[0].output_path, str(output_path))
        self.assertEqual(self.session.last_download_dir, str(output_path.parent))
        self.assertIsNotNone(self.window.latest_download_task)
        self.assertEqual(self.window.latest_download_task.state, TASK_STATE_SUCCESS)
        notify.assert_called_once()

    def test_failed_download_records_error_and_latest_task(self) -> None:
        output_path, notify = self._run_download_result(
            TASK_STATE_FAILED,
            error_code="DOWNLOAD_FAILED",
        )

        records = self.history_store.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, TASK_STATE_FAILED)
        self.assertEqual(records[0].error_code, "DOWNLOAD_FAILED")
        self.assertEqual(records[0].output_path, str(output_path))
        self.assertIsNotNone(self.window.latest_download_task)
        self.assertEqual(self.window.latest_download_task.state, TASK_STATE_FAILED)
        self.assertEqual(self.window.latest_download_task.error_code, "DOWNLOAD_FAILED")
        notify.assert_called_once()

    def test_canceled_download_records_canceled_state_without_notification(self) -> None:
        output_path, notify = self._run_download_result(TASK_STATE_CANCELED)

        records = self.history_store.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].status, TASK_STATE_CANCELED)
        self.assertEqual(records[0].output_path, str(output_path))
        self.assertIsNotNone(self.window.latest_download_task)
        self.assertEqual(self.window.latest_download_task.state, TASK_STATE_CANCELED)
        notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
