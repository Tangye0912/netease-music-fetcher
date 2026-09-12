"""Queue regressions: deterministic worker control plus real scheduler threads."""
import threading
from dataclasses import replace
from unittest import mock

import pytest

from music_fetch.app_stores import DownloadHistoryStore
from music_fetch.download_queue import DownloadQueue, DownloadRequest
from music_fetch.download_runner import DownloadJob, DownloadJobResult, DownloadProgressSnapshot


class FakeJob:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)
        self.outcome = None
        self.started = False
        self.paused = False
        self.canceled = False
        self.cleaned = True

    def start(self):
        self.started = True

    def progress(self):
        return DownloadProgressSnapshot(50, 100, 10)

    def result(self):
        return self.outcome

    def wait(self, timeout=None):
        return self.outcome is not None and self.cleaned

    def request_pause(self):
        self.paused = True

    def request_resume(self):
        self.paused = False

    def request_cancel(self):
        self.canceled = True

    def finish(self, state="success", code=""):
        self.outcome = DownloadJobResult(state, self.output_path, 100 if state == "success" else 0, code, "reason")


@pytest.fixture
def setup_queue(tmp_path):
    jobs = []

    def factory(**kwargs):
        job = FakeJob(**kwargs)
        jobs.append(job)
        return job

    history = DownloadHistoryStore(tmp_path / "history.json")
    queue = DownloadQueue(history, "MUSIC_U=old", 2, factory)
    return queue, jobs, history


def request(tmp_path, song="1", **kwargs):
    return DownloadRequest(song, f"Song {song}", tmp_path / f"{song}.mp3", **kwargs)


def test_shared_limit_for_multiple_submissions_and_refill(setup_queue, tmp_path):
    queue, jobs, history = setup_queue
    for song in ("1", "2", "3", "4"):
        queue.enqueue(request(tmp_path, song))
    queue.poll()
    assert len(jobs) == 2
    jobs[0].finish()
    queue.poll()
    assert len(jobs) == 3
    assert len(history.load()) == 1
    queue.poll()
    assert len(history.load()) == 1
    queue.set_concurrency(1)
    jobs[1].finish()
    queue.poll()
    assert len(jobs) == 3  # lowering the limit does not launch another job
    jobs[2].finish()
    queue.poll()
    assert len(jobs) == 4


def test_duplicate_requests_reuse_task_and_stems_are_reserved(setup_queue, tmp_path):
    queue, _, _ = setup_queue
    req = request(tmp_path)
    first = queue.enqueue(req)
    assert queue.enqueue(req).task_id == first.task_id
    other = queue.enqueue(replace(req, song_id="2"))
    fallback = queue.enqueue(replace(req, output_path=req.output_path.with_suffix(".flac"), target_format="flac"))
    assert len({first.output_path.stem, other.output_path.stem, fallback.output_path.stem}) == 3
    assert len(queue.snapshot()) == 3
    first.state = "failed"
    assert queue.snapshot()[0].state == "pending"  # callers cannot change live state


def test_existing_file_is_preserved(setup_queue, tmp_path):
    queue, _, _ = setup_queue
    req = request(tmp_path)
    req.output_path.write_bytes(b"existing")
    item = queue.enqueue(req)
    assert item.output_path != req.output_path
    queue.cancel(item.task_id)
    assert req.output_path.read_bytes() == b"existing"


def test_pause_pending_and_active_resume_and_cancel(setup_queue, tmp_path):
    queue, jobs, history = setup_queue
    first = queue.enqueue(request(tmp_path))
    queue.poll()
    queue.pause_all()
    second = queue.enqueue(request(tmp_path, "2"))
    queue.poll()
    assert jobs[0].paused
    assert [i.state for i in queue.snapshot()] == ["paused", "paused"]
    queue.resume_all()
    queue.poll()
    assert not jobs[0].paused and len(jobs) == 2
    queue.pause(first.task_id)
    queue.cancel(first.task_id)
    assert jobs[0].canceled and not jobs[0].paused
    assert queue.snapshot()[0].state == "canceling"
    jobs[0].finish("canceled")
    queue.poll()
    queue.cancel(second.task_id)
    jobs[1].finish("canceled")
    queue.poll()
    assert {r.status for r in history.load()} == {"canceled"}


def test_cancel_pending_never_starts_worker_and_records_once(setup_queue, tmp_path):
    queue, jobs, history = setup_queue
    item = queue.enqueue(request(tmp_path))
    queue.cancel(item.task_id)
    queue.cancel_all()
    queue.poll()
    assert not jobs
    assert len(history.load()) == 1 and history.load()[0].status == "canceled"


def test_auth_expiry_suspends_and_relogin_preserves_request_options(setup_queue, tmp_path):
    queue, jobs, history = setup_queue
    queue.set_concurrency(1)
    item = queue.enqueue(request(tmp_path, download_lyric=True, lyric_mode="translation", artist="artist"))
    queue.enqueue(request(tmp_path, "2"))
    queue.poll()
    jobs[0].finish("failed", "AUTH_EXPIRED")
    queue.poll()
    assert [i.state for i in queue.snapshot()] == ["waiting_login", "waiting_login"]
    assert queue.auth_required and not history.load()
    queue.set_cookie("MUSIC_U=new")
    queue.poll()
    assert jobs[1].cookie == "MUSIC_U=new"
    assert jobs[1].lyric_mode == "translation" and jobs[1].download_lyric
    assert jobs[1].tags["artist"] == "artist"
    assert jobs[1].output_path == item.output_path
    assert not queue.auth_required


def test_old_auth_failure_does_not_clear_new_cookie(setup_queue, tmp_path):
    queue, jobs, _ = setup_queue
    queue.enqueue(request(tmp_path))
    queue.poll()
    queue.set_cookie("MUSIC_U=new")
    jobs[0].finish("failed", "AUTH_EXPIRED")
    queue.poll()
    assert not queue.auth_required
    assert len(jobs) == 2 and jobs[1].cookie == "MUSIC_U=new"


def test_logout_blocks_pending_and_canceling_auth_failure_is_final(setup_queue, tmp_path):
    queue, jobs, _ = setup_queue
    item = queue.enqueue(request(tmp_path))
    queue.poll()
    queue.set_cookie("")
    pending = queue.enqueue(request(tmp_path, "2"))
    assert pending.state == "waiting_login"
    queue.cancel(item.task_id)
    jobs[0].finish("failed", "AUTH_EXPIRED")
    queue.poll()
    assert queue.snapshot()[0].state == "canceled"
    assert len(jobs) == 1
    queue.cancel(pending.task_id)
    assert not queue.auth_required


def test_failure_can_retry_without_changing_lyric_or_tag_options(setup_queue, tmp_path):
    queue, jobs, history = setup_queue
    item = queue.enqueue(request(tmp_path, download_lyric=True, lyric_mode="bilingual", album_name="album"))
    queue.poll()
    jobs[0].finish("failed", "NETWORK_ERROR")
    queue.poll()
    retried = queue.retry(item.task_id)
    assert retried.task_id != item.task_id
    queue.poll()
    assert jobs[1].lyric_mode == "bilingual" and jobs[1].tags["album"] == "album"
    jobs[1].finish()
    queue.poll()
    assert len(history.load()) == 1 and history.load()[0].status == "success"


def test_path_reserved_until_worker_cleanup_finishes(setup_queue, tmp_path):
    queue, jobs, history = setup_queue
    item = queue.enqueue(request(tmp_path))
    queue.poll()
    jobs[0].cleaned = False
    jobs[0].finish("failed", "NETWORK_ERROR")
    queue.poll()
    assert queue.snapshot()[0].state == "running"
    assert not history.load()
    other = queue.enqueue(replace(item.request, song_id="2"))
    assert other.output_path != item.output_path
    jobs[0].cleaned = True
    queue.poll()
    assert queue.snapshot()[0].state == "failed"


def test_history_write_failure_does_not_stop_queue_and_can_recover(setup_queue, tmp_path):
    queue, jobs, history = setup_queue
    queue.enqueue(request(tmp_path))
    queue.poll()
    jobs[0].finish()
    with mock.patch.object(history, "add", side_effect=OSError("disk full")), mock.patch(
        "music_fetch.download_queue.time.monotonic", return_value=10
    ):
        queue.poll()
    assert "disk full" in queue.history_error
    assert not queue.snapshot()[0].recorded
    with mock.patch("music_fetch.download_queue.time.monotonic", return_value=16):
        queue.poll()
    assert not queue.history_error and queue.snapshot()[0].recorded
    assert len(history.load()) == 1


def test_start_failure_is_recorded_and_next_request_starts(tmp_path):
    job = FakeJob(output_path=tmp_path / "2.mp3", cookie="cookie")
    factory = mock.Mock(side_effect=[RuntimeError("cannot start"), job])
    queue = DownloadQueue(DownloadHistoryStore(tmp_path / "history.json"), "cookie", job_factory=factory)
    queue.enqueue(request(tmp_path))
    queue.enqueue(request(tmp_path, "2"))
    queue.poll()
    assert [i.state for i in queue.snapshot()] == ["failed", "running"]
    assert job.started


def test_close_cancels_pending_and_active_and_prevents_submission(setup_queue, tmp_path):
    queue, jobs, _ = setup_queue
    queue.set_concurrency(1)
    queue.enqueue(request(tmp_path))
    queue.enqueue(request(tmp_path, "2"))
    queue.poll()
    queue.close()
    assert jobs[0].canceled
    assert [i.state for i in queue.snapshot()] == ["canceling", "canceled"]
    with pytest.raises(ValueError):
        queue.enqueue(request(tmp_path, "3"))
    jobs[0].finish("canceled")
    queue.poll()
    assert len(jobs) == 1 and queue.wait(0)


def test_scheduler_refills_while_ui_is_blocked_without_poll(tmp_path):
    jobs = []
    second_started = threading.Event()
    first_started = threading.Event()

    class SignalJob(FakeJob):
        def start(self):
            super().start()
            (first_started if self.song_id == "1" else second_started).set()

        def request_cancel(self):
            super().request_cancel()
            self.finish("canceled")

    def factory(**kwargs):
        job = SignalJob(**kwargs)
        jobs.append(job)
        return job

    queue = DownloadQueue(DownloadHistoryStore(tmp_path / "history.json"), "cookie", 1, factory)
    queue.enqueue(request(tmp_path))
    queue.enqueue(request(tmp_path, "2"))
    queue.start()
    try:
        assert first_started.wait(2)
        jobs[0].finish()
        # No UI calls to poll or snapshot: the scheduler must dispatch by itself.
        assert second_started.wait(2)
    finally:
        queue.close()
        assert queue.wait(2)


def test_real_job_shutdown_waits_for_cleanup(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    req = request(tmp_path)
    history = DownloadHistoryStore(tmp_path / "history.json")
    queue = DownloadQueue(history, "cookie", job_factory=DownloadJob)

    def pipeline(**kwargs):
        from music_fetch.api import DownloadCanceled
        req.output_path.with_name(req.output_path.name + ".source").write_bytes(b"partial")
        entered.set()
        assert release.wait(2)
        raise DownloadCanceled()

    with mock.patch("music_fetch.download_runner.run_download_pipeline", side_effect=pipeline):
        queue.enqueue(req)
        queue.start()
        try:
            assert entered.wait(2)
            queue.close()
            assert not queue.wait(0)
        finally:
            release.set()
            assert queue.wait(2)
    assert not list(tmp_path.glob("*.source"))
    assert history.load()[0].status == "canceled"


def test_individually_paused_task_stays_paused_after_auth_expiry(setup_queue, tmp_path):
    queue, jobs, _ = setup_queue
    item = queue.enqueue(request(tmp_path))
    queue.poll()
    queue.pause(item.task_id)
    jobs[0].finish("failed", "AUTH_EXPIRED")
    queue.poll()
    assert queue.auth_required and queue.snapshot()[0].state == "paused"
    queue.set_cookie("new")
    queue.poll()
    assert len(jobs) == 1
    queue.resume(item.task_id)
    queue.poll()
    assert len(jobs) == 2 and jobs[1].cookie == "new"
