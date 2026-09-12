"""Application-owned queue. All mutations run on the UI/driver thread."""
from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from music_fetch.app_settings import MAX_DOWNLOAD_CONCURRENCY, SUPPORTED_AUDIO_FORMATS
from music_fetch.app_stores import DownloadHistoryStore, DownloadRecord
from music_fetch.audio import sanitize_filename
from music_fetch.download_runner import DownloadJob, DownloadProgressSnapshot
from music_fetch.error_texts import user_error_message

QueueState = Literal["pending", "running", "paused", "canceling", "waiting_login", "success", "failed", "canceled", "skipped"]
FINAL_STATES = {"success", "failed", "canceled", "skipped"}
STATE_LABELS = {
    "pending": "等待中", "running": "下载中", "paused": "已暂停", "canceling": "取消中",
    "waiting_login": "等待登录", "success": "已完成", "failed": "失败", "canceled": "已取消", "skipped": "已跳过",
}
STAGE_LABELS = {
    "resolving": "解析音源", "downloading": "传输音频", "converting": "处理格式",
    "tagging": "写入标签", "lyrics": "处理歌词", "finishing": "保存文件",
}


@dataclass(frozen=True)
class DownloadOptions:
    out_dir: str
    target_format: str = "mp3"
    lyric_mode: str = "none"
    rename: str = ""

    def __post_init__(self) -> None:
        if not self.out_dir.strip():
            raise ValueError("保存目录不能为空。")
        if self.target_format not in SUPPORTED_AUDIO_FORMATS:
            raise ValueError("不支持的音频格式。")
        if self.lyric_mode not in {"none", "original", "translation", "bilingual"}:
            raise ValueError("不支持的歌词模式。")
        object.__setattr__(self, "out_dir", str(Path(self.out_dir).expanduser().resolve()))


@dataclass(frozen=True)
class DownloadRequest:
    song_id: str
    song_name: str
    options: DownloadOptions
    artist: str = ""
    album_name: str = ""
    cover_url: str = ""

    @classmethod
    def from_record(cls, record: DownloadRecord) -> DownloadRequest:
        path = Path(record.output_path).expanduser()
        fmt = record.target_format or path.suffix.lstrip(".")
        return cls(record.song_id, record.song_name,
                   DownloadOptions(str(path.parent), fmt if fmt in SUPPORTED_AUDIO_FORMATS else "mp3",
                                   record.lyric_mode, path.stem),
                   record.artist, record.album_name, record.cover_url)


@dataclass
class QueueItem:
    request: DownloadRequest
    output_path: Path
    task_id: str = field(default_factory=lambda: uuid4().hex)
    state: QueueState = "pending"
    message: str = ""
    error_code: str = ""
    size_bytes: int = 0
    progress: DownloadProgressSnapshot = field(default_factory=lambda: DownloadProgressSnapshot(0, -1, 0))
    job: DownloadJob | None = field(default=None, repr=False)
    recorded: bool = False
    finished_at: str = ""


class DownloadQueue:
    def __init__(self, history_store: DownloadHistoryStore, cookie: str = "", concurrency: int = 1,
                 timeout: int = 10, retry_count: int = 1,
                 job_factory: Callable[..., DownloadJob] = DownloadJob) -> None:
        self.history_store = history_store
        self.cookie = cookie
        self.concurrency = concurrency
        self.timeout = timeout
        self.retry_count = retry_count
        self.job_factory = job_factory
        self.items: list[QueueItem] = []
        self.paused = False
        self.auth_required = False
        self.history_error = ""
        self._last_history_retry = 0.0
        self._closing = False

    @property
    def concurrency(self) -> int:
        return self._concurrency

    @concurrency.setter
    def concurrency(self, value: int) -> None:
        self._concurrency = min(MAX_DOWNLOAD_CONCURRENCY, max(1, int(value)))

    @property
    def unfinished(self) -> list[QueueItem]:
        return [item for item in self.items if item.state not in FINAL_STATES]

    @property
    def active(self) -> list[QueueItem]:
        return [item for item in self.items if item.job is not None]

    def enqueue(self, request: DownloadRequest, *, force: bool = False) -> QueueItem:
        if self._closing:
            raise ValueError("正在退出，不能追加任务。")
        for item in self.unfinished:
            if item.request == request:
                return item
        options = request.options
        stem = sanitize_filename(options.rename or f"{request.song_name or 'song'}-{request.song_id}")
        target = Path(options.out_dir) / f"{stem}.{options.target_format}"
        item = QueueItem(request, target)
        try:
            # The history can locate an earlier source-format fallback as well.
            existing = target if target.is_file() and target.stat().st_size > 0 else None
            if existing is None and not force:
                for record in self.history_store.load():
                    path = Path(record.output_path)
                    if (record.song_id == request.song_id and record.status == "success"
                            and path.parent == target.parent and path.stem == target.stem
                            and record.target_format == options.target_format
                            and path.is_file() and path.stat().st_size > 0):
                        existing = path
                        break
            if not force and existing is not None:
                item.output_path = existing
                item.state = "skipped"
                item.size_bytes = existing.stat().st_size
                item.message = "已有文件；可在详情中重新下载并另存。"
                item.recorded = True  # Preserve the successful history record.
            else:
                reserved = {other.output_path for other in self.unfinished}
                index = 0
                while item.output_path.exists() or item.output_path in reserved:
                    index += 1
                    if index >= 10000:
                        raise ValueError("无法分配输出文件名。")
                    item.output_path = target.with_name(f"{target.stem}_{index}{target.suffix}")
                if not self.cookie:
                    item.state = "waiting_login"
                    self.auth_required = True
        except (OSError, ValueError) as err:
            item.state = "failed"
            item.error_code = "DOWNLOAD_FAILED"
            item.message = str(err)
        self.items.append(item)
        if item.state in FINAL_STATES:
            self._record(item)
        return item

    def set_cookie(self, cookie: str) -> None:
        self.cookie = cookie
        self.auth_required = not bool(cookie) and bool(self.unfinished)
        for item in self.unfinished:
            if cookie and item.state == "waiting_login":
                item.state = "pending"
                item.error_code = ""
                item.message = ""

    def pause(self, task_id: str) -> None:
        item = self.get(task_id)
        if item.state in {"pending", "running"}:
            item.state = "paused"
            if item.job:
                item.job.request_pause()

    def resume(self, task_id: str) -> None:
        item = self.get(task_id)
        if item.state == "paused":
            item.state = "running" if item.job else ("pending" if self.cookie else "waiting_login")
            if item.job:
                item.job.request_resume()

    def cancel(self, task_id: str) -> None:
        item = self.get(task_id)
        if item.state in FINAL_STATES or item.state == "canceling":
            return
        if item.job:
            item.state = "canceling"
            item.job.request_cancel()
        else:
            item.state = "canceled"
            item.message = "下载已取消。"
            self._record(item)

    def pause_all(self) -> None:
        self.paused = True
        for item in self.unfinished:
            self.pause(item.task_id)

    def resume_all(self) -> None:
        self.paused = False
        for item in self.unfinished:
            self.resume(item.task_id)

    def cancel_all(self) -> None:
        for item in self.unfinished:
            self.cancel(item.task_id)
        self.auth_required = False

    def close(self) -> None:
        self._closing = True
        self.cancel_all()

    def get(self, task_id: str) -> QueueItem:
        return next(item for item in self.items if item.task_id == task_id)

    def retry(self, task_id: str, *, force: bool = False) -> QueueItem:
        item = self.get(task_id)
        if item.state not in FINAL_STATES:
            return item
        return self.enqueue(item.request, force=force)

    def poll(self) -> None:
        for item in self.active:
            job = item.job
            assert job is not None
            item.progress = job.progress()
            result = job.result()
            if result is None:
                continue
            item.job = None
            item.output_path = result.output_path
            item.size_bytes = result.file_size
            item.error_code = result.error_code
            if result.error_code == "AUTH_EXPIRED" and item.state != "canceling":
                item.state = "waiting_login"
                item.message = "登录已过期，请重新登录后继续。"
                self.cookie = ""
                self.auth_required = True
            else:
                item.state = "success" if result.state == "success" else (
                    "canceled" if result.state == "canceled" else "failed")
                item.message = user_error_message(result.error_code, result.error_message) if item.state == "failed" else ""
                self._record(item)
        if self.auth_required:
            for item in self.unfinished:
                if item.job is None and item.state == "pending":
                    item.state = "waiting_login"
        if not self.paused and not self._closing and self.cookie:
            for item in self.items:
                if len(self.active) >= self.concurrency:
                    break
                if item.state != "pending":
                    continue
                req, opts = item.request, item.request.options
                try:
                    item.job = self.job_factory(
                        task_id=item.task_id, song_id=req.song_id, output_path=item.output_path,
                        cookie=self.cookie, target_format=opts.target_format,
                        timeout=self.timeout, retry_count=self.retry_count,
                        tags={"title": req.song_name, "artist": req.artist, "album": req.album_name, "cover_url": req.cover_url},
                        download_lyric=opts.lyric_mode != "none", lyric_mode=opts.lyric_mode,
                    )
                    item.state = "running"
                    item.job.start()
                except Exception as err:
                    item.job = None
                    item.state = "failed"
                    item.error_code = "DOWNLOAD_FAILED"
                    item.message = str(err)
                    self._record(item)
        if self.history_error and time.monotonic() - self._last_history_retry > 5:
            self._last_history_retry = time.monotonic()
            self.history_error = ""
            for item in self.items:
                if item.state in FINAL_STATES:
                    self._record(item)

    def _record(self, item: QueueItem) -> None:
        if item.recorded:
            return
        req, opts = item.request, item.request.options
        item.finished_at = item.finished_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.history_store.add(DownloadRecord(
                req.song_id, req.song_name, str(item.output_path), item.size_bytes, item.finished_at,
                status=item.state, error_code=item.error_code, target_format=opts.target_format,
                lyric_mode=opts.lyric_mode, artist=req.artist, album_name=req.album_name, cover_url=req.cover_url,
            ))
            item.recorded = True
        except OSError as err:
            self.history_error = f"历史保存失败：{err}"

    def counts(self) -> dict[str, int]:
        return {state: sum(item.state == state for item in self.items) for state in STATE_LABELS}

    def snapshot(self) -> tuple[QueueItem, ...]:
        return tuple(replace(item, job=None) for item in self.items)
