import tempfile
import unittest
from pathlib import Path
from unittest import mock

from music_fetch import DownloadCanceled
from music_fetch.api import MusicFetchError, PlayableCandidate
from music_fetch.download_runner import (
    DownloadJob,
    DownloadJobResult,
    JOB_STATE_CANCELED,
    JOB_STATE_FAILED,
    JOB_STATE_SUCCESS,
)
from music_fetch.pipeline import DownloadPipelineResult


class DownloadJobSuccessTests(unittest.TestCase):
    def test_pipeline_success_produces_success_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "song.mp3"
            output_path.write_bytes(b"audio")
            job = DownloadJob(
                task_id="task-ok",
                song_id="42",
                output_path=output_path,
                cookie="MUSIC_U=abc",
                target_format="mp3",
                timeout=3,
                retry_count=0,
            )
            result = DownloadPipelineResult(
                output_path=output_path,
                file_size=5,
                candidate=PlayableCandidate(
                    media_url="https://example.com/song.mp3",
                    duration_ms=120000, level="standard", encode_type="mp3",
                ),
                source_format="mp3",
            )
            with mock.patch("music_fetch.download_runner.run_download_pipeline", return_value=result):
                job.start()
                self.assertTrue(job.wait(timeout=5))
            self.assertEqual(job.state(), JOB_STATE_SUCCESS)
            self.assertEqual(job.result().file_size, 5)

    def test_progress_callback_updates_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "song.mp3"
            job = DownloadJob(
                task_id="task-progress", song_id="42", output_path=output_path,
                cookie="MUSIC_U=abc", target_format="mp3", timeout=3, retry_count=0,
            )
            captured = {}

            def fake_pipeline(**kwargs):
                captured["progress_callback"] = kwargs["progress_callback"]
                captured["cancel_checker"] = kwargs["cancel_checker"]
                captured["pause_checker"] = kwargs["pause_checker"]
                kwargs["progress_callback"](2048, 4096)
                output_path.write_bytes(b"audio")
                return DownloadPipelineResult(
                    output_path=output_path, file_size=5,
                    candidate=PlayableCandidate(
                        media_url="https://example.com/song.mp3",
                        duration_ms=120000, level="standard", encode_type="mp3",
                    ),
                    source_format="mp3",
                )

            with mock.patch("music_fetch.download_runner.run_download_pipeline", side_effect=fake_pipeline):
                job.start()
                self.assertTrue(job.wait(timeout=5))
            self.assertIsNotNone(captured["cancel_checker"])
            self.assertIsNotNone(captured["pause_checker"])
            snapshot = job.progress()
            self.assertEqual(snapshot.downloaded, 2048)
            self.assertEqual(snapshot.total, 4096)


class DownloadJobControlTests(unittest.TestCase):
    def _job(self, output_path: Path) -> DownloadJob:
        return DownloadJob(
            task_id="task-x", song_id="42", output_path=output_path,
            cookie="MUSIC_U=abc", target_format="mp3", timeout=3, retry_count=0,
        )

    def test_pause_and_resume_toggle_event(self):
        job = self._job(Path("/tmp/x.mp3"))
        job.request_pause()
        self.assertTrue(job.is_paused)
        job.request_resume()
        self.assertFalse(job.is_paused)

    def test_cancel_event_is_exposed_via_cancel_checker(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = self._job(Path(tmp) / "song.mp3")
            captured = {}

            def fake_pipeline(**kwargs):
                captured["cancel_checker"] = kwargs["cancel_checker"]
                return DownloadPipelineResult(
                    output_path=Path(tmp) / "song.mp3", file_size=1,
                    candidate=PlayableCandidate(
                        media_url="https://example.com/song.mp3",
                        duration_ms=0, level="standard", encode_type="mp3",
                    ),
                    source_format="mp3",
                )

            with mock.patch("music_fetch.download_runner.run_download_pipeline", side_effect=fake_pipeline):
                job.start()
                self.assertTrue(job.wait(timeout=5))
            self.assertFalse(captured["cancel_checker"]())
            job.request_cancel()
            self.assertTrue(captured["cancel_checker"]())


class DownloadJobFailureTests(unittest.TestCase):
    def test_pipeline_error_produces_failed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "song.mp3"
            job = DownloadJob(
                task_id="task-fail", song_id="42", output_path=output_path,
                cookie="MUSIC_U=abc", target_format="mp3", timeout=3, retry_count=0,
            )
            err = MusicFetchError("DOWNLOAD_FAILED", "test error")
            with mock.patch("music_fetch.download_runner.run_download_pipeline", side_effect=err):
                job.start()
                self.assertTrue(job.wait(timeout=5))
            self.assertEqual(job.state(), JOB_STATE_FAILED)
            self.assertEqual(job.result().error_code, "DOWNLOAD_FAILED")
            self.assertEqual(job.result().error_message, "test error")

    def test_cancel_produces_canceled_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "song.mp3"
            job = DownloadJob(
                task_id="task-cancel", song_id="42", output_path=output_path,
                cookie="MUSIC_U=abc", target_format="mp3", timeout=3, retry_count=0,
            )
            with mock.patch("music_fetch.download_runner.run_download_pipeline", side_effect=DownloadCanceled()):
                job.start()
                self.assertTrue(job.wait(timeout=5))
            self.assertEqual(job.state(), JOB_STATE_CANCELED)
            self.assertEqual(job.result().output_path, output_path)

    def test_unexpected_error_produces_failed_with_unknown_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "song.mp3"
            job = DownloadJob(
                task_id="task-boom", song_id="42", output_path=output_path,
                cookie="MUSIC_U=abc", target_format="mp3", timeout=3, retry_count=0,
            )
            with mock.patch("music_fetch.download_runner.run_download_pipeline", side_effect=RuntimeError("boom")):
                job.start()
                self.assertTrue(job.wait(timeout=5))
            self.assertEqual(job.state(), JOB_STATE_FAILED)
            self.assertEqual(job.result().error_code, "UNKNOWN_ERROR")

    def test_stale_temp_files_are_cleaned_after_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "song.mp3"
            for suffix in (".source", ".part", ".source.part"):
                output_path.with_name(f"{output_path.name}{suffix}").write_bytes(b"stale")
            job = DownloadJob(
                task_id="task-cleanup", song_id="42", output_path=output_path,
                cookie="MUSIC_U=abc", target_format="mp3", timeout=3, retry_count=0,
            )
            err = MusicFetchError("DOWNLOAD_FAILED", "fail")
            with mock.patch("music_fetch.download_runner.run_download_pipeline", side_effect=err):
                job.start()
                self.assertTrue(job.wait(timeout=5))
            for suffix in (".source", ".part", ".source.part"):
                self.assertFalse(output_path.with_name(f"{output_path.name}{suffix}").exists())

    def test_unstarted_job_is_pending_and_wait_returns_false(self):
        job = DownloadJob(
            task_id="task-none", song_id="42", output_path=Path("/tmp/x.mp3"),
            cookie="MUSIC_U=abc",
        )
        self.assertEqual(job.state(), "pending")
        self.assertFalse(job.wait(timeout=0.1))


if __name__ == "__main__":
    unittest.main()
