"""App-owned downloads, scheduled independently of blocking terminal input."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable
from uuid import uuid4

from music_fetch.app_logging import get_logger
from music_fetch.app_settings import MAX_UI_CONCURRENCY
from music_fetch.app_stores import DownloadHistoryStore, DownloadRecord, QueueStore
from music_fetch.download_runner import DownloadJob, DownloadProgressSnapshot
from music_fetch.error_texts import user_error_message

logger = get_logger("music_fetch.queue")

FINAL_STATES = frozenset({"success", "failed", "canceled"})
STATE_LABELS = {
    "pending": "等待中", "running": "下载中", "paused": "已暂停",
    "canceling": "取消中", "waiting_login": "等待登录",
    "success": "已完成", "failed": "失败", "canceled": "已取消",
}
STAGE_LABELS = {
    "resolving": "解析播放地址", "downloading": "下载中", "retrying": "重试中",
    "converting": "转码中", "tagging": "写入标签", "lyrics": "下载歌词",
}


@dataclass(frozen=True)
class DownloadRequest:
    song_id: str
    song_name: str
    output_path: Path
    target_format: str = "mp3"
    download_lyric: bool = False
    lyric_mode: str = "original"
    artist: str | None = None
    album_name: str | None = None
    cover_url: str | None = None
    timeout: int = 10
    retry_count: int = 1


_REQUEST_FIELDS = (
    "song_id", "song_name", "output_path", "target_format", "download_lyric",
    "lyric_mode", "artist", "album_name", "cover_url", "timeout", "retry_count",
)


def _request_to_dict(request: DownloadRequest) -> dict[str, object]:
    data: dict[str, object] = {}
    for name in _REQUEST_FIELDS:
        value = getattr(request, name)
        data[name] = str(value) if isinstance(value, Path) else value
    return data


def _request_from_dict(data: dict[str, object]) -> DownloadRequest:
    def text(name: str) -> str:
        return str(data.get(name, ""))

    def optional_text(name: str) -> str | None:
        value = data.get(name)
        return str(value) if value not in (None, "") else None

    output = data.get("output_path")
    if not isinstance(output, str) or not output:
        raise KeyError("output_path")
    return DownloadRequest(
        song_id=text("song_id"),
        song_name=text("song_name"),
        output_path=Path(output),
        target_format=text("target_format") or "mp3",
        download_lyric=bool(data.get("download_lyric", False)),
        lyric_mode=text("lyric_mode") or "original",
        artist=optional_text("artist"),
        album_name=optional_text("album_name"),
        cover_url=optional_text("cover_url"),
        timeout=int(data.get("timeout", 10) or 10),
        retry_count=int(data.get("retry_count", 1) or 1),
    )


@dataclass
class QueueItem:
    request: DownloadRequest
    output_path: Path
    task_id: str = field(default_factory=lambda: uuid4().hex)
    state: str = "pending"
    message: str = ""
    error_code: str = ""
    size_bytes: int = 0
    progress: DownloadProgressSnapshot = field(default_factory=lambda: DownloadProgressSnapshot(0, -1, 0))
    job: DownloadJob | None = field(default=None, repr=False)
    recorded: bool = False
    finished_at: str = ""


class DownloadQueue:
    """One scheduler owns job dispatch; callers only receive copied snapshots.

    Start once at app entry and close/join at exit. poll() is also exposed for
    deterministic drivers/tests. No worker accesses UI or session storage.
    """

    def __init__(self, history_store: DownloadHistoryStore, cookie: str = "", concurrency: int = 1,
                 job_factory: Callable[..., DownloadJob] = DownloadJob,
                 persist_path: Path | None = None) -> None:
        self._history_store = history_store
        self._cookie = cookie
        self._concurrency = max(1, min(MAX_UI_CONCURRENCY, concurrency))
        self._job_factory = job_factory
        self._items: list[QueueItem] = []
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._closing = False
        self._paused = False
        self._history_error = ""
        self._last_history_retry = 0.0
        self._queue_store = QueueStore(persist_path) if persist_path is not None else None
        self._persist_sig: object = None

    def start(self) -> None:
        with self._lock:
            if self._thread is None and not self._closing:
                self._thread = threading.Thread(target=self._run, name="download-queue")
                self._thread.start()

    def _run(self) -> None:
        while True:
            self._wake.clear()
            self.poll()
            with self._lock:
                if self._closing and not any(item.job for item in self._items):
                    return
            self._wake.wait(0.1)

    def snapshot(self) -> tuple[QueueItem, ...]:
        with self._lock:
            return tuple(replace(item, job=None) for item in self._items)

    def item(self, task_id: str) -> QueueItem | None:
        """Snapshot copy of one task, or None when the id is unknown."""
        with self._lock:
            for item in self._items:
                if item.task_id == task_id:
                    return replace(item, job=None)
        return None

    @property
    def auth_required(self) -> bool:
        with self._lock:
            return not self._cookie and any(item.state not in FINAL_STATES for item in self._items)

    @property
    def history_error(self) -> str:
        with self._lock:
            return self._history_error

    def set_concurrency(self, value: int) -> None:
        with self._lock:
            self._concurrency = max(1, min(MAX_UI_CONCURRENCY, value))
        self._wake.set()

    def set_cookie(self, cookie: str) -> None:
        with self._lock:
            self._cookie = cookie
            for item in self._items:
                if item.state == "waiting_login" and cookie:
                    item.state = "paused" if self._paused else "pending"
                    item.message = item.error_code = ""
                elif item.state == "pending" and not cookie:
                    item.state = "waiting_login"
        self._wake.set()

    def enqueue(self, request: DownloadRequest) -> QueueItem:
        request = replace(request, output_path=request.output_path.expanduser().resolve())
        with self._lock:
            if self._closing:
                raise ValueError("正在退出，不能追加任务。")
            for item in self._items:
                if item.request == request and item.state not in FINAL_STATES:
                    return replace(item, job=None)
            # Reserve the whole stem: source-format fallback and .lrc files
            # must not collide with another queued request in a different format.
            reserved = {str(item.output_path.with_suffix("")).casefold() for item in self._items
                        if item.state not in FINAL_STATES or item.job is not None}
            target = request.output_path
            index = 0
            while str(target.with_suffix("")).casefold() in reserved or target.exists():
                index += 1
                target = request.output_path.with_name(
                    f"{request.output_path.stem}_{index}{request.output_path.suffix}")
            item = QueueItem(request, target)
            if not self._cookie:
                item.state = "waiting_login"
            elif self._paused:
                item.state = "paused"
            self._items.append(item)
            self._wake.set()
            return replace(item, job=None)

    def _get(self, task_id: str) -> QueueItem:
        return next(item for item in self._items if item.task_id == task_id)

    def pause(self, task_id: str) -> None:
        with self._lock:
            item = self._get(task_id)
            if item.state in {"pending", "running", "waiting_login"}:
                item.state = "paused"
                if item.job:
                    item.job.request_pause()

    def resume(self, task_id: str) -> None:
        with self._lock:
            item = self._get(task_id)
            if item.state == "paused":
                item.state = "running" if item.job else ("pending" if self._cookie else "waiting_login")
                if item.job:
                    item.job.request_resume()
        self._wake.set()

    def cancel(self, task_id: str) -> None:
        with self._lock:
            item = self._get(task_id)
            if item.state in FINAL_STATES or item.state == "canceling":
                return
            if item.job:
                item.state = "canceling"
                item.job.request_cancel()
                item.job.request_resume()
            else:
                item.state = "canceled"
                item.message = "下载已取消。"
                self._record(item)
        self._wake.set()

    def pause_all(self) -> None:
        with self._lock:
            self._paused = True
            for item in self._items:
                self.pause(item.task_id)

    def resume_all(self) -> None:
        with self._lock:
            self._paused = False
            for item in self._items:
                self.resume(item.task_id)

    def cancel_all(self) -> None:
        with self._lock:
            for item in self._items:
                self.cancel(item.task_id)

    def retry(self, task_id: str) -> QueueItem:
        with self._lock:
            item = self._get(task_id)
            if item.state not in {"failed", "canceled"}:
                return replace(item, job=None)
            return self.enqueue(item.request)

    def close(self) -> None:
        with self._lock:
            self._closing = True
            if self._queue_store is None:
                self.cancel_all()
            else:
                # Interrupt live workers only; jobless unfinished tasks stay
                # in the queue and are persisted for the next run instead of
                # being recorded as canceled.
                for item in self._items:
                    if item.job:
                        item.state = "canceling"
                        item.job.request_cancel()
                        item.job.request_resume()
            self._last_history_retry = 0
            self.poll()
        self._wake.set()

    def wait(self, timeout: float | None = None) -> bool:
        if self._thread is not None:
            self._thread.join(timeout)
            return not self._thread.is_alive()
        return not any(item.job for item in self._items)

    def poll(self) -> None:
        with self._lock:
            for item in self._items:
                job = item.job
                if job is None:
                    continue
                item.progress = job.progress()
                result = job.result()
                # A result is published before the runner's finally cleanup.
                # Wait for thread completion before releasing its file reservation.
                if result is None or not job.wait(0):
                    continue
                item.job = None
                item.output_path = result.output_path
                item.size_bytes = result.file_size
                item.error_code = result.error_code
                if result.error_code == "AUTH_EXPIRED" and item.state != "canceling":
                    # A late failure from an old login must not invalidate a new one.
                    if job.cookie == self._cookie:
                        self._cookie = ""
                    if item.state == "paused" or self._paused:
                        item.state = "paused"
                    else:
                        item.state = "pending" if self._cookie else "waiting_login"
                    item.message = "登录已失效，请从任务页重新登录后继续。"
                else:
                    item.state = "canceled" if item.state == "canceling" and result.state != "success" else result.state
                    item.message = user_error_message(result.error_code, result.error_message) if item.state == "failed" else ""
                    self._record(item)
            active = sum(item.job is not None for item in self._items)
            for item in self._items:
                if item.state == "pending" and not self._cookie:
                    item.state = "waiting_login"
                if (self._closing or item.state != "pending" or not self._cookie
                        or active >= self._concurrency):
                    continue
                req = item.request
                try:
                    item.job = self._job_factory(
                        task_id=item.task_id, song_id=req.song_id, output_path=item.output_path,
                        cookie=self._cookie, target_format=req.target_format,
                        timeout=req.timeout, retry_count=req.retry_count,
                        tags={"title": req.song_name, "artist": req.artist, "album": req.album_name, "cover_url": req.cover_url},
                        download_lyric=req.download_lyric, lyric_mode=req.lyric_mode,
                    )
                    item.state = "running"
                    item.job.start()
                    active += 1
                except Exception as err:
                    item.job = None
                    item.state = "failed"
                    item.error_code = "DOWNLOAD_FAILED"
                    item.message = str(err)
                    self._record(item)
            if self._history_error and time.monotonic() - self._last_history_retry >= 5:
                self._last_history_retry = time.monotonic()
                self._history_error = ""
                for item in self._items:
                    if item.state in FINAL_STATES:
                        self._record(item)
            self._persist_if_changed()

    # ── cross-restart persistence ─────────────────────────────────

    def _persist_if_changed(self) -> None:
        """Save unfinished tasks when the pending set changed since last write."""
        if self._queue_store is None:
            return
        signature = tuple(sorted(
            (item.task_id, item.state) for item in self._items if item.state not in FINAL_STATES
        ))
        if signature == self._persist_sig:
            return
        self._persist_sig = signature
        entries: list[dict[str, object]] = [
            {"request": _request_to_dict(item.request), "state": item.state}
            for item in self._items if item.state not in FINAL_STATES
        ]
        try:
            self._queue_store.save(entries)
        except OSError as err:
            logger.warning("Failed to persist queue. path=%s reason=%s",
                           self._queue_store.path, err)

    def restore_saved(self) -> tuple[int, int]:
        """Re-enqueue tasks persisted by a previous run.

        Tasks whose target file already exists are treated as completed and
        recorded to history instead of being downloaded again.  Returns
        (restored, completed_on_disk).
        """
        if self._queue_store is None:
            return (0, 0)
        restored = completed = 0
        for entry in self._queue_store.load():
            if not isinstance(entry, dict):
                continue
            try:
                payload = entry.get("request")
                if not isinstance(payload, dict):
                    continue
                request = _request_from_dict(payload)
            except (KeyError, TypeError, ValueError, OSError):
                logger.warning("Skipping malformed persisted task. entry=%r", entry)
                continue
            if request.output_path.exists():
                done = QueueItem(
                    request=request, output_path=request.output_path, state="success",
                    size_bytes=request.output_path.stat().st_size,
                )
                self._record(done)
                completed += 1
                continue
            self.enqueue(request)
            restored += 1
        self._persist_sig = None  # force the next poll to rewrite the store
        with self._lock:
            self._persist_if_changed()
        return (restored, completed)

    def _record(self, item: QueueItem) -> None:
        if item.recorded:
            return
        item.finished_at = item.finished_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self._history_store.add(DownloadRecord(
                item.request.song_id, item.request.song_name or f"song-{item.request.song_id}",
                str(item.output_path), item.size_bytes, item.finished_at,
                status=item.state, error_code=item.error_code,
            ))
            item.recorded = True
        except OSError as err:
            self._history_error = f"下载历史保存失败：{err}"
