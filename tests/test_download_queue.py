"""Queue regressions: deterministic worker control plus real scheduler threads."""
import threading
from dataclasses import replace
from unittest import mock

import pytest

from music_fetch.app_stores import DownloadHistoryStore, QueueStore
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


def fake_factory(**kwargs):
    """Job factory for tests that build a queue directly.

    Without it DownloadQueue falls back to the real DownloadJob, which performs
    live network requests in a background thread and can leak into other tests.
    """
    return FakeJob(**kwargs)


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


def test_item_returns_snapshot_or_none(setup_queue, tmp_path):
    queue, _jobs, _history = setup_queue
    item = queue.enqueue(DownloadRequest("1", "song", tmp_path / "1.mp3"))
    found = queue.item(item.task_id)
    assert found is not None
    assert found.task_id == item.task_id
    assert found.job is None  # snapshots never expose the live worker
    assert queue.item("missing-task") is None


def test_persist_writes_pending_tasks_only(setup_queue, tmp_path):
    import json
    queue, jobs, _history = setup_queue
    queue._queue_store = QueueStore(tmp_path / "queue.json")
    a = queue.enqueue(DownloadRequest("1", "song", tmp_path / "a.mp3"))
    queue.enqueue(DownloadRequest("2", "song", tmp_path / "b.mp3"))
    queue.poll()
    queue.enqueue(DownloadRequest("3", "song", tmp_path / "c.mp3"))
    queue.cancel(a.task_id)  # user-cancel of a dispatched task
    next(j for j in jobs if j.output_path.name == "a.mp3").finish(state="canceled")
    queue.poll()
    entries = json.loads((tmp_path / "queue.json").read_text(encoding="utf-8"))
    ids = {entry["request"]["song_id"] for entry in entries}
    assert "1" not in ids  # canceled by the user, recorded, not persisted
    assert ids == {"2", "3"}


def test_close_with_persist_keeps_jobless_and_cancels_running(setup_queue, tmp_path):
    import json
    queue, jobs, history = setup_queue
    queue._queue_store = QueueStore(tmp_path / "queue.json")
    queue.enqueue(DownloadRequest("1", "jobless", tmp_path / "a.mp3"))
    queue.enqueue(DownloadRequest("2", "running", tmp_path / "b.mp3"))
    queue.poll()
    assert len(jobs) == 2
    running = next(j for j in jobs if j.output_path.name == "b.mp3")
    running.start()
    queue.close()
    running.finish(state="canceled")
    queue.poll()
    # The live worker was canceled and recorded…
    record = {r.song_id: r for r in history.load()}
    assert record["2"].status == "canceled"
    assert record.get("1") is None  # jobless task NOT recorded as canceled
    # …while the jobless task is persisted for the next run.
    entries = json.loads((tmp_path / "queue.json").read_text(encoding="utf-8"))
    assert [entry["request"]["song_id"] for entry in entries] == ["1"]
def test_restore_reenqueues_missing_and_records_existing(tmp_path):
    import json
    store_path = tmp_path / "queue.json"
    existing_target = tmp_path / "done.mp3"
    existing_target.write_bytes(b"finished")
    store_path.write_text(json.dumps([
        {"request": {"song_id": "1", "song_name": "已有", "output_path": str(existing_target)},
         "state": "paused"},
        {"request": {"song_id": "2", "song_name": "缺失", "output_path": str(tmp_path / "missing.mp3")},
         "state": "pending"},
    ], ensure_ascii=False), encoding="utf-8")
    history = DownloadHistoryStore(tmp_path / "history.json")
    queue = DownloadQueue(history, "MUSIC_U=x", 2, fake_factory, persist_path=store_path)
    restored, completed = queue.restore_saved()
    assert (restored, completed) == (1, 1)
    # The existing file was recorded as a completed download, not re-downloaded.
    record = {r.song_id: r for r in history.load()}
    assert record["1"].status == "success"
    assert record["1"].size_bytes == len(b"finished")
    # The missing file was re-enqueued.
    assert [i.request.song_id for i in queue.snapshot()] == ["2"]
    # And the store no longer lists the completed one.
    entries = json.loads(store_path.read_text(encoding="utf-8"))
    assert [entry["request"]["song_id"] for entry in entries] == ["2"]


def test_restore_tolerates_malformed_store(tmp_path):
    store_path = tmp_path / "queue.json"
    store_path.write_text("not-json-at-all", encoding="utf-8")
    history = DownloadHistoryStore(tmp_path / "history.json")
    queue = DownloadQueue(history, "MUSIC_U=x", 1, fake_factory, persist_path=store_path)
    assert queue.restore_saved() == (0, 0)
    assert queue.snapshot() == ()


def test_restore_without_store_is_noop(setup_queue):
    queue, _jobs, _history = setup_queue
    assert queue.restore_saved() == (0, 0)


def test_persist_retries_after_a_transient_write_failure(tmp_path):
    """One OSError must not permanently drop the pending state."""
    store_path = tmp_path / "queue.json"
    history = DownloadHistoryStore(tmp_path / "history.json")
    queue = DownloadQueue(history, "MUSIC_U=x", 1, fake_factory, persist_path=store_path)
    queue.enqueue(request(tmp_path, "1"))
    with mock.patch.object(QueueStore, "save", side_effect=OSError("disk full")):
        queue.poll()
    assert not store_path.exists()
    queue.poll()  # the next poll retries the write
    assert [entry["request"]["song_id"] for entry in QueueStore(store_path).load()] == ["1"]


def test_unknown_task_ids_are_ignored(setup_queue):
    """Public task controls must not leak StopIteration for unknown ids."""
    queue, _jobs, _history = setup_queue
    queue.pause("missing")
    queue.resume("missing")
    queue.cancel("missing")
    with pytest.raises(ValueError):
        queue.retry("missing")


def test_restore_reenqueues_empty_target_file(tmp_path):
    """A zero-byte leftover is an interrupted write, not a finished download."""
    import json
    store_path = tmp_path / "queue.json"
    target = tmp_path / "empty.mp3"
    target.write_bytes(b"")
    store_path.write_text(json.dumps([
        {"request": {"song_id": "1", "song_name": "半截", "output_path": str(target)},
         "state": "pending"},
    ], ensure_ascii=False), encoding="utf-8")
    history = DownloadHistoryStore(tmp_path / "history.json")
    queue = DownloadQueue(history, "MUSIC_U=x", 1, fake_factory, persist_path=store_path)
    restored, completed = queue.restore_saved()
    assert (restored, completed) == (1, 0)
    assert history.load() == []
    assert [item.request.song_id for item in queue.snapshot()] == ["1"]


def _assert_ui_reads_do_not_block(queue, message):
    """The TUI re-reads the queue on a 0.5s timer; reads must never stall."""
    done = threading.Event()

    def read():
        queue.snapshot()
        queue.active_jobs
        queue.auth_required
        done.set()

    threading.Thread(target=read, daemon=True).start()
    assert done.wait(2), message


def test_poll_does_not_hold_the_lock_during_history_write(setup_queue, tmp_path):
    queue, jobs, history = setup_queue
    queue.enqueue(request(tmp_path, "1"))
    queue.poll()          # dispatch the worker
    jobs[0].finish()      # worker completed, result is waiting to be collected
    real_add = history.add
    writing, release = threading.Event(), threading.Event()

    def slow_add(record):
        writing.set()
        assert release.wait(5)
        return real_add(record)

    with mock.patch.object(history, "add", side_effect=slow_add):
        poller = threading.Thread(target=queue.poll)
        poller.start()
        assert writing.wait(5), "history write never started"
        _assert_ui_reads_do_not_block(queue, "snapshot() blocked behind the history write")
        release.set()
        poller.join(5)
    assert not poller.is_alive()
    assert [record.song_id for record in history.load()] == ["1"]


def test_poll_does_not_hold_the_lock_during_queue_persist(tmp_path):
    store_path = tmp_path / "queue.json"
    history = DownloadHistoryStore(tmp_path / "history.json")
    queue = DownloadQueue(history, "MUSIC_U=x", 1, fake_factory, persist_path=store_path)
    queue.enqueue(request(tmp_path, "1"))  # changes the pending set → persist needed
    real_save = QueueStore.save
    writing, release = threading.Event(), threading.Event()

    def slow_save(store_self, entries):
        writing.set()
        assert release.wait(5)
        return real_save(store_self, entries)

    with mock.patch.object(QueueStore, "save", slow_save):
        poller = threading.Thread(target=queue.poll)
        poller.start()
        assert writing.wait(5), "queue persist never started"
        _assert_ui_reads_do_not_block(queue, "snapshot() blocked behind the queue write")
        release.set()
        poller.join(5)
    assert not poller.is_alive()
    assert [entry["request"]["song_id"] for entry in QueueStore(store_path).load()] == ["1"]


def test_history_write_failure_is_retried_on_a_later_poll(setup_queue, tmp_path):
    """A failed history write must leave the item eligible for a retry."""
    queue, jobs, history = setup_queue
    queue.enqueue(request(tmp_path, "1"))
    queue.poll()
    jobs[0].finish()
    with mock.patch.object(history, "add", side_effect=OSError("disk full")):
        queue.poll()
    assert queue.history_error
    queue.poll()  # the retry branch re-stages every finished-but-unrecorded item
    assert [record.song_id for record in history.load()] == ["1"]


def test_active_jobs_counts_live_workers(setup_queue, tmp_path):
    queue, jobs, _history = setup_queue
    assert queue.active_jobs == 0
    queue.enqueue(request(tmp_path, "1"))
    queue.poll()
    assert queue.active_jobs == 1
    jobs[0].finish()
    queue.poll()
    assert queue.active_jobs == 0


def test_scheduler_survives_a_poll_exception(tmp_path):
    """An unexpected poll error must not silently kill the scheduler thread."""
    history = DownloadHistoryStore(tmp_path / "history.json")
    queue = DownloadQueue(history, "MUSIC_U=x", 1, fake_factory)
    calls = []

    def flaky_poll():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("boom")
        queue._closing = True  # let the loop exit after the second poll

    queue.poll = flaky_poll
    queue.start()
    assert queue.wait(2)
    assert len(calls) >= 2
