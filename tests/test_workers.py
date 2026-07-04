import tempfile
import unittest
from pathlib import Path
from unittest import mock

import music_fetch.workers
import music_fetch
from music_fetch import DownloadCanceled, DownloadPaused


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


if __name__ == "__main__":
    unittest.main()
