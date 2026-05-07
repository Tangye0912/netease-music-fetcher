import tempfile
import unittest
from pathlib import Path
from unittest import mock

import _workers
import music_fetch


class DownloadWorkerCancellationTests(unittest.TestCase):
    def test_cancel_during_conversion_removes_completed_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / "song.mp3"
            worker = _workers.DownloadWorker(
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

            def fake_download(**kwargs):
                Path(kwargs["output_path"]).write_bytes(b"source")
                return music_fetch.PlayableCandidate(
                    media_url="https://m801.music.126.net/source.m4a",
                    duration_ms=None,
                    level="standard",
                    encode_type="aac",
                )

            def fake_convert(_input_path, output, _target_format, timeout):
                self.assertGreaterEqual(timeout, 240)
                output.write_bytes(b"converted")
                worker.request_cancel()

            with (
                mock.patch("_workers.download_song_with_fallback", side_effect=fake_download),
                mock.patch("_workers.infer_audio_format_from_url", return_value="m4a"),
                mock.patch("_workers.is_ffmpeg_available", return_value=True),
                mock.patch("_workers.convert_audio_file", side_effect=fake_convert),
            ):
                worker.run()

            self.assertEqual(canceled, [True])
            self.assertEqual(succeeded, [])
            self.assertFalse(output_path.exists())
            self.assertFalse(output_path.with_name(f"{output_path.name}.source").exists())


if __name__ == "__main__":
    unittest.main()
