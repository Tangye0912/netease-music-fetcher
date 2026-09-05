import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

from music_fetch.api import MusicFetchError
from music_fetch.app_stores import DownloadHistoryStore
from music_fetch.batch_download import BatchDownloadSession
from music_fetch.batch_models import BatchDetectRow
from music_fetch.download_runner import DownloadJobResult, DownloadProgressSnapshot


class FakeJob:
    instances: list["FakeJob"] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.output_path = kwargs["output_path"]
        self._state = "pending"
        self._result: Optional[DownloadJobResult] = None
        self.pause_calls = 0
        self.resume_calls = 0
        self.cancel_calls = 0
        FakeJob.instances.append(self)

    def start(self) -> None:
        self._state = "running"

    def state(self) -> str:
        return self._state

    def result(self):
        return self._result

    def progress(self) -> DownloadProgressSnapshot:
        return DownloadProgressSnapshot(0, -1, 0.0)

    def request_pause(self) -> None:
        self.pause_calls += 1

    def request_resume(self) -> None:
        self.resume_calls += 1

    def request_cancel(self) -> None:
        self.cancel_calls += 1

    def succeed(self) -> None:
        self._result = DownloadJobResult(state="success", output_path=self.output_path, file_size=10)
        self._state = "success"

    def fail(self, code: str = "DOWNLOAD_FAILED", message: str = "boom") -> None:
        self._result = DownloadJobResult(
            state="failed", output_path=self.output_path, error_code=code, error_message=message,
        )
        self._state = "failed"

    def cancel_finish(self) -> None:
        self._result = DownloadJobResult(state="canceled", output_path=self.output_path)
        self._state = "canceled"


def _row(song_id: str, status: str = "ready", selected: bool = True) -> BatchDetectRow:
    return BatchDetectRow(
        raw_input=f"https://music.163.com/song?id={song_id}",
        source_type="song",
        source_label=f"song-{song_id}",
        song_id=song_id,
        song_name=f"Song {song_id}",
        status=status,
        selected=selected,
    )


class BatchDownloadSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeJob.instances = []
        self._tmp = tempfile.TemporaryDirectory()
        self.out_dir = Path(self._tmp.name) / "out"
        self.history = DownloadHistoryStore(Path(self._tmp.name) / "history.json")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _session(self, rows: list[BatchDetectRow], concurrency: int = 2) -> BatchDownloadSession:
        return BatchDownloadSession(
            rows=rows,
            out_dir=self.out_dir,
            cookie="MUSIC_U=abc",
            history_store=self.history,
            target_format="mp3",
            timeout=3,
            retry_count=0,
            concurrency=concurrency,
        )

    def _poll_until_done(self, session: BatchDownloadSession, max_polls: int = 50) -> None:
        for _ in range(max_polls):
            session.poll()
            if session.done:
                return

    def test_success_flow_writes_history_and_row_status(self):
        rows = [_row("1"), _row("2")]
        with mock.patch("music_fetch.batch_download.DownloadJob", new=FakeJob):
            session = self._session(rows)
            session.poll()
            self.assertEqual(len(session._jobs), 2)
            for job in session._jobs.values():
                job.succeed()
            self._poll_until_done(session)
        self.assertTrue(session.done)
        self.assertEqual([r.status for r in rows], ["download_success", "download_success"])
        counters = session.counters()
        self.assertEqual((counters.success, counters.failed, counters.canceled), (2, 0, 0))
        records = self.history.load()
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r.status == "success" for r in records))

    def test_failed_job_marks_row_and_records_error(self):
        rows = [_row("1")]
        with mock.patch("music_fetch.batch_download.DownloadJob", new=FakeJob):
            session = self._session(rows, concurrency=1)
            session.poll()
            for job in session._jobs.values():
                job.fail(code="NETWORK_ERROR", message="timeout")
            self._poll_until_done(session)
        self.assertEqual(rows[0].status, "download_failed")
        records = self.history.load()
        self.assertEqual(records[0].status, "failed")
        self.assertEqual(records[0].error_code, "NETWORK_ERROR")

    def test_summary_panel_rows_include_counts_output_and_failure_reasons(self):
        rows = [_row("1"), _row("2")]
        with mock.patch("music_fetch.batch_download.DownloadJob", new=FakeJob):
            session = self._session(rows)
            session.poll()
            for job in session._jobs.values():
                job.fail(code="NETWORK_ERROR", message="timeout")
            self._poll_until_done(session)

        panel_rows = dict(session.summary_panel_rows())
        self.assertEqual(panel_rows["状态"], "完成")
        self.assertEqual(panel_rows["成功"], "0")
        self.assertEqual(panel_rows["失败"], "2")
        self.assertEqual(panel_rows["取消"], "0")
        self.assertEqual(panel_rows["输出目录"], str(self.out_dir))
        self.assertIn("x2", panel_rows["失败原因"])
        self.assertEqual(panel_rows["提示"], "失败项可在下载历史中重试")

    def test_auth_expired_stops_dispatching_pending_jobs(self):
        rows = [_row("1"), _row("2")]
        with mock.patch("music_fetch.batch_download.DownloadJob", new=FakeJob):
            session = self._session(rows, concurrency=1)
            session.poll()
            first = list(session._jobs.values())[0]
            first.fail(code="AUTH_EXPIRED", message="expired")
            self._poll_until_done(session)
        self.assertTrue(session.auth_expired)
        self.assertTrue(session.stopped)
        self.assertEqual(len(FakeJob.instances), 1)
        self.assertEqual(rows[1].status, "ready")

    def test_cancel_all_stops_dispatch_and_keeps_pending_rows_ready(self):
        rows = [_row("1"), _row("2"), _row("3")]
        with mock.patch("music_fetch.batch_download.DownloadJob", new=FakeJob):
            session = self._session(rows, concurrency=1)
            session.poll()
            active = list(session._jobs.values())
            self.assertEqual(len(active), 1)
            session.request_cancel_all()
            self.assertEqual(active[0].cancel_calls, 1)
            active[0].cancel_finish()
            self._poll_until_done(session)
        self.assertTrue(session.done)
        self.assertTrue(session.stopped)
        self.assertEqual(rows[0].status, "download_canceled")
        self.assertEqual([r.status for r in rows[1:]], ["ready", "ready"])
        counters = session.counters()
        self.assertEqual(counters.pending, 2)
        self.assertIn("未开始 2", session.summary_text())
        self.assertEqual(dict(session.summary_panel_rows())["状态"], "已停止（未开始 2）")

    def test_pause_blocks_new_dispatch_and_resume_continues(self):
        rows = [_row("1"), _row("2"), _row("3")]
        with mock.patch("music_fetch.batch_download.DownloadJob", new=FakeJob):
            session = self._session(rows, concurrency=1)
            session.poll()
            first = list(session._jobs.values())[0]
            session.request_pause_all()
            self.assertEqual(first.pause_calls, 1)
            self.assertEqual(rows[0].status, "download_paused")
            session.poll()
            self.assertEqual(len(session._jobs), 1)  # paused → no new dispatch
            session.request_resume_all()
            self.assertEqual(first.resume_calls, 1)
            self.assertEqual(rows[0].status, "downloading")
            session.poll()
            self.assertEqual(len(session._jobs), 1)  # one active slot still busy
            # Drive to completion: succeed every active job and poll again.
            for _ in range(10):
                for job in list(session._jobs.values()):
                    job.succeed()
                session.poll()
                if session.done:
                    break
        self.assertTrue(session.done)
        self.assertEqual(session.counters().success, 3)

    def test_output_path_failure_marks_row_failed_without_job(self):
        rows = [_row("1")]
        err = MusicFetchError("DOWNLOAD_FAILED", "no filename")
        with mock.patch("music_fetch.batch_download.DownloadJob", new=FakeJob),              mock.patch("music_fetch.batch_download.resolve_output_path", side_effect=err):
            session = self._session(rows, concurrency=1)
            self._poll_until_done(session)
        self.assertTrue(session.done)
        self.assertEqual(rows[0].status, "download_failed")
        self.assertEqual(FakeJob.instances, [])
        self.assertEqual(self.history.load()[0].error_code, "DOWNLOAD_FAILED")

    def test_retry_rows_are_dispatched_like_normal_rows(self):
        rows = [_row("1", status="download_failed", selected=False)]
        with mock.patch("music_fetch.batch_download.DownloadJob", new=FakeJob):
            session = self._session(rows, concurrency=1)
            session.poll()
            self.assertEqual(len(session._jobs), 1)
            self.assertEqual(rows[0].status, "downloading")
            for job in session._jobs.values():
                job.succeed()
            self._poll_until_done(session)
        self.assertEqual(rows[0].status, "download_success")


if __name__ == "__main__":
    unittest.main()
