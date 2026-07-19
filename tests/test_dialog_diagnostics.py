import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

_app = QApplication.instance() or QApplication(["test"])

from music_fetch.diagnostics import EndpointProbe
from music_fetch.dialog_diagnostics import DiagnosticsDialog
from music_fetch.download_tasks import DownloadTaskSnapshot
from music_fetch.dialog_diagnostics import QDesktopServices


class DiagnosticsDialogTests(unittest.TestCase):
    @staticmethod
    def _create_dialog(log_path: Path) -> DiagnosticsDialog:
        return DiagnosticsDialog(
            log_path=log_path,
            cookie="MUSIC_U=secret-cookie; __csrf=secret-csrf",
            proxy_type="socks5",
            proxy_host="127.0.0.1",
            proxy_port=1080,
            proxy_username="proxy-user",
            proxy_password="proxy-secret",
            ffmpeg_available=False,
            latest_task=DownloadTaskSnapshot(
                task_id="42-1",
                song_id="42",
                output_path="/tmp/song.mp3",
                state="failed",
                error_code="DOWNLOAD_FAILED",
            ),
        )

    def test_preview_only_shows_redacted_warning_and_error_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "music-fetch.log"
            log_path.write_text(
                "2026 INFO routine detail\n"
                "2026 WARNING MUSIC_U=secret-cookie proxy-secret\n",
                encoding="utf-8",
            )
            dialog = self._create_dialog(log_path)
            preview = dialog.log_preview.toPlainText()
            self.assertNotIn("INFO routine", preview)
            self.assertNotIn("secret-cookie", preview)
            self.assertNotIn("proxy-secret", preview)
            self.assertIn("WARNING", preview)
            labels = [label.text() for label in dialog.findChildren(QLabel)]
            self.assertTrue(any("DOWNLOAD_FAILED" in text for text in labels))
            dialog.close()

    def test_async_network_check_updates_status_table(self):
        results = (
            EndpointProbe("网易云 API", True, 200, "HTTP 200"),
            EndpointProbe("音乐 CDN", False, 0, "timed out"),
        )

        class FakeSignal:
            def __init__(self) -> None:
                self.callbacks = []

            def connect(self, callback) -> None:
                self.callbacks.append(callback)

            def emit(self, value=None) -> None:
                for callback in self.callbacks:
                    callback() if value is None else callback(value)

        class FakeWorker:
            def __init__(self, **_kwargs) -> None:
                self.completed = FakeSignal()
                self.finished = FakeSignal()

            def start(self) -> None:
                self.completed.emit(results)
                self.finished.emit()

            def isRunning(self) -> bool:
                return False

            def deleteLater(self) -> None:
                return

        with tempfile.TemporaryDirectory() as tmp:
            dialog = self._create_dialog(Path(tmp) / "music-fetch.log")
            with mock.patch("music_fetch.dialog_diagnostics.DiagnosticsWorker", FakeWorker):
                dialog._run_network_check()
            self.assertEqual(dialog.network_table.item(0, 1).text(), "可达")
            self.assertEqual(dialog.network_table.item(1, 1).text(), "不可达")
            self.assertIn("网易云 API：可达", dialog._current_report())
            self.assertTrue(dialog.run_network_button.isEnabled())
            dialog.close()

    def test_export_writes_redacted_diagnostic_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            log_path = base / "music-fetch.log"
            log_path.write_text(
                "2026 ERROR MUSIC_U=secret-cookie proxy-secret\n",
                encoding="utf-8",
            )
            output_path = base / "diagnostics.txt"
            dialog = self._create_dialog(log_path)
            with (
                mock.patch(
                    "music_fetch.dialog_diagnostics.QFileDialog.getSaveFileName",
                    return_value=(str(output_path), "Text"),
                ),
                mock.patch.object(QMessageBox, "information") as information,
            ):
                dialog._export_report()

            report = output_path.read_text(encoding="utf-8")
            self.assertIn("music-fetch 诊断报告", report)
            self.assertIn("最近错误码：DOWNLOAD_FAILED", report)
            self.assertNotIn("secret-cookie", report)
            self.assertNotIn("proxy-secret", report)
            information.assert_called_once()
            dialog.close()

    def test_missing_log_shows_empty_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            dialog = self._create_dialog(Path(tmp) / "missing.log")
            self.assertEqual(dialog.log_preview.toPlainText(), "暂无 WARNING / ERROR 日志。")
            with mock.patch.object(QDesktopServices, "openUrl") as open_url:
                dialog._open_log_folder()
            open_url.assert_called_once()
            dialog.close()

    def test_reject_is_blocked_while_network_check_runs(self):
        worker = mock.MagicMock()
        worker.isRunning.return_value = True
        with tempfile.TemporaryDirectory() as tmp:
            dialog = self._create_dialog(Path(tmp) / "music-fetch.log")
            dialog._network_worker = worker
            with mock.patch.object(QMessageBox, "information") as information:
                dialog.reject()
            self.assertEqual(dialog.result(), 0)
            information.assert_called_once()
            worker.isRunning.return_value = False
            dialog._network_worker = None
            dialog.close()


if __name__ == "__main__":
    unittest.main()
