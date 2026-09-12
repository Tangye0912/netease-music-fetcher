from pathlib import Path
from unittest import mock

import pytest

from music_fetch.app_stores import DownloadHistoryStore, DownloadRecord
from music_fetch.download_queue import DownloadOptions, DownloadQueue, DownloadRequest
from test_batch_download import FakeJob


@pytest.fixture
def queue(tmp_path):
    FakeJob.instances = []
    return DownloadQueue(DownloadHistoryStore(tmp_path / "history.json"), "test-session", 2, job_factory=FakeJob)


def request(tmp_path, song_id="1", **options):
    return DownloadRequest(song_id, "同名歌曲", DownloadOptions(str(tmp_path / "out"), **options))


def finish(queue):
    for item in queue.active:
        item.job.succeed()
    queue.poll()


def test_append_shares_concurrency_and_deduplicates(queue, tmp_path):
    first = queue.enqueue(request(tmp_path))
    assert queue.enqueue(request(tmp_path)) is first
    queue.poll()
    queue.enqueue(request(tmp_path, "2"))
    queue.enqueue(request(tmp_path, "3"))
    queue.poll()
    assert len(queue.active) == 2
    assert len(queue.items) == 3
    queue.concurrency = 1
    finish(queue)
    assert len(queue.active) == 1
    finish(queue)
    assert not queue.unfinished
    assert len(queue.history_store.load()) == 3


def test_cancel_before_start_records_every_row_once(queue, tmp_path):
    for i in range(3):
        queue.enqueue(request(tmp_path, str(i)))
    queue.cancel_all()
    queue.poll()
    queue.cancel_all()
    assert queue.counts()["canceled"] == 3
    assert len(queue.history_store.load()) == 3
    assert not FakeJob.instances


def test_cancel_paused_active_and_pending(queue, tmp_path):
    item = queue.enqueue(request(tmp_path))
    queue.poll()
    queue.pause_all()
    other = queue.enqueue(request(tmp_path, "2"))
    queue.poll()
    assert item.state == "paused" and other.job is None
    queue.close()
    assert item.state == "canceling" and other.state == "canceled"
    item.job.cancel_finish()
    queue.poll()
    assert not queue.unfinished
    with pytest.raises(ValueError):
        queue.enqueue(request(tmp_path, "3"))


def test_auth_expired_waits_for_single_relogin(queue, tmp_path):
    queue.concurrency = 1
    first = queue.enqueue(request(tmp_path))
    second = queue.enqueue(request(tmp_path, "2"))
    queue.poll()
    first.job.fail("AUTH_EXPIRED")
    queue.poll()
    assert queue.auth_required
    assert first.state == second.state == "waiting_login"
    assert not queue.history_store.load()
    queue.set_cookie("renewed-test-session")
    queue.poll()
    finish(queue)
    finish(queue)
    assert first.state == second.state == "success"
    assert len(queue.history_store.load()) == 2


def test_existing_file_is_skipped_and_force_saves_separately(queue, tmp_path):
    req = request(tmp_path)
    target = Path(req.options.out_dir) / "同名歌曲-1.mp3"
    target.parent.mkdir()
    target.write_bytes(b"old")
    skipped = queue.enqueue(req)
    assert skipped.state == "skipped"
    forced = queue.enqueue(req, force=True)
    assert forced.output_path != target
    assert target.read_bytes() == b"old"


def test_reserved_names_and_empty_files_are_not_overwritten(queue, tmp_path):
    one = queue.enqueue(request(tmp_path, "1", rename="custom"))
    two = queue.enqueue(request(tmp_path, "2", rename="custom"))
    assert one.output_path != two.output_path
    target = Path(tmp_path / "out" / "empty.mp3")
    target.parent.mkdir()
    target.touch()
    three = queue.enqueue(request(tmp_path, "3", rename="empty"))
    assert three.state == "pending" and three.output_path != target


def test_pause_resume_individual_and_global(queue, tmp_path):
    one = queue.enqueue(request(tmp_path))
    queue.pause(one.task_id)
    queue.poll()
    assert one.job is None
    queue.resume(one.task_id)
    queue.poll()
    queue.pause_all()
    assert one.job.pause_calls == 1
    queue.resume_all()
    assert one.job.resume_calls == 1
    assert one.state == "running"


def test_history_error_does_not_lose_result(queue, tmp_path):
    item = queue.enqueue(request(tmp_path))
    queue.poll()
    with mock.patch.object(queue.history_store, "add", side_effect=OSError("read only")):
        finish(queue)
    assert item.state == "success" and not item.recorded
    assert queue.history_error
    queue._last_history_retry = 0
    queue.poll()
    assert item.recorded and not queue.history_error


def test_retry_preserves_options_and_metadata(queue, tmp_path):
    req = DownloadRequest("1", "Song", DownloadOptions(str(tmp_path), "flac", "bilingual"), "Artist", "Album", "cover")
    item = queue.enqueue(req)
    queue.poll()
    item.job.fail()
    queue.poll()
    record = queue.history_store.load()[0]
    restored = DownloadRequest.from_record(record)
    assert restored.artist == "Artist" and restored.album_name == "Album"
    assert restored.options.lyric_mode == "bilingual"
    assert queue.retry(item.task_id).request == req


def test_legacy_record_uses_extension(tmp_path):
    req = DownloadRequest.from_record(DownloadRecord("1", "Song", str(tmp_path / "song.flac"), 0, ""))
    assert req.options.target_format == "flac" and req.options.lyric_mode == "none"


@pytest.mark.parametrize("value", [0, 1, 3, 8])
def test_concurrency_is_bounded(queue, value):
    queue.concurrency = value
    assert 1 <= queue.concurrency <= 3


@pytest.mark.parametrize("options", [{"out_dir": ""}, {"out_dir": "/tmp", "target_format": "bad"},
                                    {"out_dir": "/tmp", "lyric_mode": "bad"}])
def test_invalid_options(options):
    with pytest.raises(ValueError):
        DownloadOptions(**options)
