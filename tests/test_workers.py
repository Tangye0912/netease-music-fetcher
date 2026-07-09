import tempfile
import unittest
from pathlib import Path
from unittest import mock

import music_fetch.workers
import music_fetch
from music_fetch import DownloadCanceled
from music_fetch.api import MusicFetchError, SongDetectionResult
from music_fetch.batch_models import BatchDetectRow


class DownloadWorkerCancellationTests(unittest.TestCase):
    def test_cancel_during_pipeline_emits_canceled(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "song.mp3"
            worker = music_fetch.workers.DownloadWorker(
                task_id="task-1",
                song_id="42",
                output_path=output_path,
                cookie="MUSIC_U=abc",
                target_format="mp3",
                timeout=3,
                retry_count=0,
            )
            canceled = []
            succeeded = []
            worker.canceled.connect(lambda: canceled.append(True))
            worker.succeeded.connect(lambda *_args: succeeded.append(True))

            def fake_pipeline(*, song_id, cookie, output_path, target_format, timeout, retry_count, cancel_checker=None, **kwargs):
                # Simulate cancel during pipeline
                if cancel_checker:
                    cancel_checker()  # check once
                raise DownloadCanceled()

            with mock.patch("music_fetch.workers.run_download_pipeline", side_effect=fake_pipeline):
                worker.run()

            self.assertEqual(canceled, [True])
            self.assertEqual(succeeded, [])


    def test_resume_clears_pause_event(self):
        worker = music_fetch.workers.DownloadWorker(
            task_id="task-resume",
            song_id="42",
            output_path=Path("/tmp/test.mp3"),
            cookie="MUSIC_U=abc",
            target_format="mp3",
            timeout=3,
            retry_count=0,
        )
        worker.request_pause()
        self.assertTrue(worker._pause_event.is_set())
        worker.request_resume()
        self.assertFalse(worker._pause_event.is_set())


class DownloadWorkerFailedTests(unittest.TestCase):
    def test_pipeline_failure_emits_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "song.mp3"
            worker = music_fetch.workers.DownloadWorker(
                task_id="task-fail",
                song_id="42",
                output_path=output_path,
                cookie="MUSIC_U=abc",
                target_format="mp3",
                timeout=3,
                retry_count=0,
            )
            failed = []
            worker.failed.connect(lambda code, msg: failed.append((code, msg)))

            err = MusicFetchError("DOWNLOAD_FAILED", "test error")
            with mock.patch("music_fetch.workers.run_download_pipeline", side_effect=err):
                worker.run()

            self.assertEqual(len(failed), 1)
            self.assertEqual(failed[0][0], "DOWNLOAD_FAILED")

    def test_pipeline_success_emits_succeeded(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "song.mp3"
            output_path.write_bytes(b"audio")
            worker = music_fetch.workers.DownloadWorker(
                task_id="task-ok",
                song_id="42",
                output_path=output_path,
                cookie="MUSIC_U=abc",
                target_format="mp3",
                timeout=3,
                retry_count=0,
            )
            succeeded = []
            worker.succeeded.connect(lambda path, size: succeeded.append((path, size)))

            from music_fetch.api import PlayableCandidate
            from music_fetch.pipeline import DownloadPipelineResult
            result = DownloadPipelineResult(
                output_path=output_path,
                file_size=5,
                candidate=PlayableCandidate(
                    media_url="https://example.com/song.mp3",
                    duration_ms=120000,
                    level="standard",
                    encode_type="mp3",
                ),
                source_format="mp3",
            )
            with mock.patch("music_fetch.workers.run_download_pipeline", return_value=result):
                worker.run()

            self.assertEqual(len(succeeded), 1)
            self.assertEqual(succeeded[0][1], 5)

    def test_finally_cleans_temp_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "song.mp3"
            # Create stale temp files
            for suffix in (".source", ".part", ".source.part"):
                output_path.with_name(f"{output_path.name}{suffix}").write_bytes(b"stale")

            worker = music_fetch.workers.DownloadWorker(
                task_id="task-cleanup",
                song_id="42",
                output_path=output_path,
                cookie="MUSIC_U=abc",
                target_format="mp3",
                timeout=3,
                retry_count=0,
            )
            err = MusicFetchError("DOWNLOAD_FAILED", "fail")
            with mock.patch("music_fetch.workers.run_download_pipeline", side_effect=err):
                worker.run()

            # All temp files should be cleaned
            for suffix in (".source", ".part", ".source.part"):
                self.assertFalse(output_path.with_name(f"{output_path.name}{suffix}").exists())


class BatchInspectWorkerDetectRowsTests(unittest.TestCase):
    """Tests for BatchInspectWorker._detect_rows dedup and error handling."""

    def _make_worker(self, raw_text: str) -> music_fetch.workers.BatchInspectWorker:
        return music_fetch.workers.BatchInspectWorker(
            raw_input_text=raw_text,
            cookie="MUSIC_U=test",
            timeout=5,
            detect_concurrency=2,
        )

    @mock.patch("music_fetch.workers.probe_media_size_bytes", return_value=0)
    @mock.patch("music_fetch.workers.detect_song")
    def test_dedup_same_song_id(self, mock_detect, mock_probe):
        mock_detect.return_value = SongDetectionResult(
            song_id="100",
            song_name="Test Song",
            duration_ms=120000,
            media_url="https://example.com/song.mp3",
            can_download=True,
            unavailable_reason="",
            artist="",
            album_name="",
            cover_url=None,
        )
        worker = self._make_worker("https://music.163.com/song?id=100")
        rows = worker._detect_rows()

        # One ready row, no duplicates
        ready = [r for r in rows if r.status == "ready"]
        self.assertEqual(len(ready), 1)
        self.assertEqual(ready[0].song_id, "100")

    @mock.patch("music_fetch.workers.detect_song")
    def test_detect_failure_creates_failed_row(self, mock_detect):
        mock_detect.side_effect = MusicFetchError("SONG_UNAVAILABLE", "not available")
        worker = self._make_worker("https://music.163.com/song?id=200")
        rows = worker._detect_rows()

        failed = [r for r in rows if r.status == "failed"]
        self.assertEqual(len(failed), 1)
        self.assertIn("SONG_UNAVAILABLE", failed[0].message)

    @mock.patch("music_fetch.workers.probe_media_size_bytes", return_value=0)
    @mock.patch("music_fetch.workers.detect_song")
    def test_unavailable_song_marks_unavailable(self, mock_detect, mock_probe):
        mock_detect.return_value = SongDetectionResult(
            song_id="300",
            song_name="",
            duration_ms=None,
            media_url=None,
            can_download=False,
            unavailable_reason="VIP only",
            artist="",
            album_name="",
            cover_url=None,
        )
        worker = self._make_worker("https://music.163.com/song?id=300")
        rows = worker._detect_rows()

        unavailable = [r for r in rows if r.status == "unavailable"]
        self.assertEqual(len(unavailable), 1)
        self.assertFalse(unavailable[0].selected)

    def test_empty_input_returns_empty(self):
        worker = self._make_worker("")
        rows = worker._detect_rows()
        self.assertEqual(rows, [])


if __name__ == "__main__":
    unittest.main()
