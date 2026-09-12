"""One full-screen terminal application with an application-owned download queue."""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Callable, TypeVar

from prompt_toolkit.application import Application
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.input import Input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import Layout, HSplit, VSplit, Window, DynamicContainer, ConditionalContainer
from prompt_toolkit.layout.containers import AnyContainer
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.layout import FocusableElement
from prompt_toolkit.output import Output
from prompt_toolkit.styles import Style, DynamicStyle
from prompt_toolkit.widgets import Button, Dialog, Label, TextArea

from music_fetch.api import (
    DownloadCanceled, MusicFetchError, SearchResult, UserPlaylist, fetch_account_profile,
    fetch_user_playlists, normalize_cookie, search_songs,
)
from music_fetch.app_logging import default_log_path, setup_logging
from music_fetch.app_settings import APP_NAME, APP_VERSION, SESSION_FILE, DOWNLOAD_HISTORY_FILE
from music_fetch.app_stores import AppSession, DownloadHistoryStore, DownloadRecord, SessionStore
from music_fetch.audio import download_preview_to_temp, is_ffmpeg_available, sanitize_filename
from music_fetch.batch_inspect import run_batch_detect
from music_fetch.batch_models import BatchDetectRow, format_bytes, format_duration
from music_fetch.batch_results import build_batch_results_csv
from music_fetch.browser_login import run_official_login
from music_fetch.diagnostics import (
    DiagnosticContext, build_diagnostic_report, read_log_tail, redact_diagnostic_text, run_network_diagnostics,
)
from music_fetch.download_queue import DownloadOptions, DownloadQueue, DownloadRequest, FINAL_STATES, STAGE_LABELS, STATE_LABELS
from music_fetch.error_texts import user_error_message
from music_fetch.history_results import build_download_history_csv, filter_download_history
from music_fetch.network import ProxyConfigError, configure_proxy
from music_fetch.terminal_forms import CycleField, DownloadForm, SettingsForm
from music_fetch.terminal_widgets import Choice, ChoiceList, clean_text, clip
from music_fetch.version_check import check_for_updates_cached, version_key

logger = logging.getLogger("music_fetch.tui")
R = TypeVar("R")
NAVIGATION = [("add", "添加下载"), ("search", "搜索"), ("playlists", "我的歌单"),
              ("tasks", "任务"), ("history", "历史"), ("settings", "设置")]


@dataclass
class Modal:
    container: AnyContainer
    focus: FocusableElement
    previous_focus: FocusableElement


@dataclass
class Operation:
    name: str
    cancel: threading.Event
    task: asyncio.Task[None]


class TuiApp:
    def __init__(self, session_store: SessionStore | None = None,
                 history_store: DownloadHistoryStore | None = None,
                 *, input: Input | None = None, output: Output | None = None) -> None:
        self.session_store = session_store or SessionStore(SESSION_FILE)
        self.history_store = history_store or DownloadHistoryStore(DOWNLOAD_HISTORY_FILE)
        self.session = self.session_store.load()
        self.nickname = ""
        self.validated_login = False
        self.notice = "粘贴链接开始下载，或选择搜索。设置与历史可离线使用。"
        self.notice_error = False
        try:
            self._apply_proxy()
        except ProxyConfigError:
            configure_proxy()
            self.notice = "已保存的代理配置无效，请在设置中修正。"
        self.queue = DownloadQueue(self.history_store, self.session.cookie, self.session.download_concurrency,
                                   self.session.download_timeout_sec, self.session.download_retry_count)
        self.page = "home"
        self.generation = 0
        self.modals: list[Modal] = []
        self.operations: list[Operation] = []
        self._closing = False
        self._auth_notified = False
        self._queue_signature: object = None
        self._worker_slots = asyncio.Semaphore(3)
        self.batch_rows: dict[str, BatchDetectRow] = {}
        self.search_results: dict[str, SearchResult] = {}
        self.playlists: dict[str, UserPlaylist] = {}
        self.records: dict[str, DownloadRecord] = {}
        self.search_loaded = False
        self.playlists_loaded = False
        self._playlist_return = False
        self._ffmpeg = is_ffmpeg_available()
        self._build_controls()
        self.application: Application[None] = Application(
            layout=Layout(self._root(), focused_element=self.home_list),
            key_bindings=self._key_bindings(), full_screen=True,
            style=DynamicStyle(self._style), input=input, output=output,
            mouse_support=False, min_redraw_interval=0.03,
        )

    def _build_controls(self) -> None:
        self.home_list = ChoiceList([Choice(key, label, {
            "add": "单曲、歌单、专辑与多行分享文案", "search": "按歌名或歌手搜索",
            "playlists": "浏览账号歌单并选择曲目", "tasks": "后台进度、暂停、取消与重试",
            "history": "下载记录、文件操作与导出", "settings": "下载偏好、代理、账号与工具",
        }[key]) for key, label in NAVIGATION], activate=self.navigate)
        self.nav = ChoiceList([Choice(key, label) for key, label in NAVIGATION], activate=self.navigate)
        self.add_input = TextArea(multiline=True, scrollbar=True, wrap_lines=True, prompt="› ")
        self.add_submit = Button("识别内容", handler=self.detect_input)
        self.search_input = TextArea(multiline=False, prompt="搜索：", accept_handler=lambda _b: self._accept_search())
        self.batch_filter = TextArea(multiline=False, prompt="筛选：")
        self.history_filter = TextArea(multiline=False, prompt="筛选：")
        self.task_filter = TextArea(multiline=False, prompt="筛选：")
        self.batch_list = ChoiceList(multiple=True, activate=lambda _key: self.download_selection())
        self.search_list = ChoiceList(activate=self.search_detail)
        self.playlist_list = ChoiceList(activate=self.playlist_detail)
        self.task_list = ChoiceList(activate=self.task_detail)
        self.history_list = ChoiceList(activate=self.history_detail)
        self.history_status = CycleField("状态", [("all", "全部"), ("success", "成功"), ("failed", "失败"), ("canceled", "取消")], "all")
        self.history_status.button.handler = self._cycle_history_status
        self.settings_list = ChoiceList([
            Choice("general", "下载与外观", "默认目录、格式、歌词、深浅主题"),
            Choice("network", "代理设置", "系统网络 / HTTP / SOCKS5"),
            Choice("performance", "下载性能", "超时、重试和并发上限"),
            Choice("login", "登录 / 重新登录", "官网扫码，使用独立临时浏览器窗口"),
            Choice("logout", "退出账号", "本地历史仍可使用"),
            Choice("diagnostics", "诊断与报告", "检查网络并导出脱敏报告"),
            Choice("update", "检查更新", "手动检查新版本"),
        ], activate=self.settings_action)
        self.batch_filter.buffer.on_text_changed += lambda _b: self.batch_list.set_query(self.batch_filter.text)
        self.task_filter.buffer.on_text_changed += lambda _b: self.task_list.set_query(self.task_filter.text)
        self.history_filter.buffer.on_text_changed += lambda _b: self.refresh_history()
        self._pages: dict[str, AnyContainer] = {
            "home": HSplit([Label("  音乐下载，从这里开始"), self.home_list.window]),
            "add": HSplit([Label("歌曲 / 歌单 / 专辑链接、ID、分享文案均可，多行一起粘贴。"),
                           self.add_input, self.add_submit, Label("Enter 换行 · Alt+Enter 提交 · Esc 返回")]),
            "search": HSplit([self.search_input, self.search_list.window]),
            "playlists": HSplit([Button("刷新歌单", handler=self.load_playlists), self.playlist_list.window]),
            "batch": HSplit([self.batch_filter, Window(FormattedTextControl(self._batch_summary), height=1),
                             self.batch_list.window,
                             VSplit([Button("下载所选", handler=self.download_selection),
                                     Button("歌曲详情", handler=self.batch_detail),
                                     Button("导出结果", handler=self.export_batch)], padding=1)]),
            "tasks": HSplit([self.task_filter, self.task_list.window,
                             VSplit([Button("暂停全部", handler=self.queue.pause_all),
                                     Button("继续全部", handler=self.queue.resume_all),
                                     Button("取消全部", handler=self.confirm_cancel_all)], padding=1)]),
            "history": HSplit([self.history_filter, self.history_status.button, self.history_list.window,
                               Button("导出筛选结果", handler=self.export_history)]),
            "settings": self.settings_list.window,
        }

    def _root(self) -> AnyContainer:
        self._small = HSplit([Label("窗口较小，请放大到至少 60 列 × 18 行。"), Label("任务仍在后台运行 · Ctrl+C 退出")])
        detail = Window(FormattedTextControl(self._detail_text), wrap_lines=True, style="class:detail")
        content = VSplit([
            ConditionalContainer(HSplit([Label(" 导航"), self.nav.window], width=18), filter=Condition(lambda: self.width >= 80 and self.page != "home")),
            DynamicContainer(lambda: self._pages[self.page]),
            ConditionalContainer(HSplit([Label(" 当前条目"), detail], width=Dimension(preferred=34, max=42)),
                                 filter=Condition(lambda: self.width >= 110 and self.page in {"search", "batch", "tasks", "history", "playlists"})),
        ], padding=1)
        body = DynamicContainer(lambda: self._small if self.too_small else (self.modals[-1].container if self.modals else content))
        return HSplit([
            Window(FormattedTextControl(self._header), height=1, style="class:header"),
            ConditionalContainer(Window(FormattedTextControl(lambda: clip(" F1 首页 · F2 添加 · F3 搜索 · F4 歌单 · F5 任务 · F6 历史 · F7 设置", self.width)), height=1),
                                 filter=Condition(lambda: self.width < 80)),
            body,
            Window(FormattedTextControl(self._notification), height=1),
            Window(FormattedTextControl(self._status), height=1, style="class:status"),
            Window(FormattedTextControl(self._footer), height=1, style="class:muted"),
        ], style="class:root")

    @property
    def width(self) -> int:
        return self.application.output.get_size().columns if hasattr(self, "application") else 80

    @property
    def too_small(self) -> bool:
        if not hasattr(self, "application"):
            return False
        size = self.application.output.get_size()
        return size.columns < 60 or size.rows < 18

    def _style(self) -> Style:
        light = self.session.ui_theme == "light"
        return Style.from_dict({
            "root": "bg:#f6f8fa #20242b" if light else "bg:#161b22 #e6edf3",
            "header": "bg:#087f8c #ffffff bold", "status": "bg:#263d46 #ffffff",
            "focused": "bg:#087f8c #ffffff bold", "text": "#20242b" if light else "#e6edf3",
            "secondary": "#52616b" if light else "#96a4b4", "muted": "#52616b" if light else "#96a4b4",
            "error": "#b42318" if light else "#ff9393", "notice": "#006f58" if light else "#7dd3b0",
            "button": "bg:#dce5ea #20242b" if light else "bg:#273441 #e6edf3",
            "button.focused": "bg:#087f8c #ffffff bold",
            "dialog": "bg:#eef2f5 #20242b" if light else "bg:#202b36 #e6edf3",
            "dialog.body": "bg:#eef2f5 #20242b" if light else "bg:#202b36 #e6edf3",
            "text-area": "bg:#ffffff #20242b" if light else "bg:#0e151d #e6edf3",
            "frame.label": "#087f8c bold" if light else "#63d6e3 bold",
            "scrollbar.background": "bg:#34424e", "scrollbar.button": "bg:#087f8c",
        })

    def _header(self) -> str:
        title = dict(NAVIGATION).get(self.page, "识别结果" if self.page == "batch" else "首页")
        account = self.nickname or ("已保存登录" if self.session.cookie else "未登录")
        return clip(f" {APP_NAME} {APP_VERSION}  /  {title}    {account}", self.width)

    def _notification(self) -> StyleAndTextTuples:
        return [("class:error" if self.notice_error else "class:notice", clip(" " + self.notice, self.width))]

    def _status(self) -> str:
        counts = self.queue.counts()
        busy = next((op.name for op in reversed(self.operations) if not op.cancel.is_set()), "")
        text = f" 任务 {len(self.queue.unfinished)} · 完成 {counts['success']} · 失败 {counts['failed']} · 跳过 {counts['skipped']}"
        if self.queue.auth_required:
            text += " · 等待重新登录"
        elif self.queue.paused:
            text += " · 全部暂停"
        if self.queue.active:
            item = self.queue.active[0]
            text += f" · {STAGE_LABELS.get(item.progress.stage, '下载中')} {format_bytes(item.progress.downloaded)}"
        if busy:
            text += f" · {busy}…"
        if self._closing:
            text = " 正在取消任务并清理临时文件，请稍候…"
        return clip(text, self.width)

    def _footer(self) -> str:
        if self.modals:
            text = " Tab 切换 · Enter 确认 · Esc 返回"
        elif self.page == "batch":
            text = " ↑↓ 移动 · Space 勾选 · Enter 下载 · Ctrl+A 全选 · Ctrl+U 清空 · Esc 返回"
        elif self.page == "tasks":
            text = " ↑↓ 选择 · Enter 详情 · p 暂停/继续 · c 取消 · r 重试 · Esc 首页"
        else:
            text = " ↑↓ 选择 · Enter 进入 · Tab 切换 · Esc 返回 · F1 首页 · q 退出"
        return clip(text, self.width)

    def _detail_text(self) -> str:
        control = self.current_list()
        if not control or not control.current:
            return "\n选择条目查看信息。"
        row = control.current
        if self.page == "tasks":
            item = self.queue.get(row.key)
            return f"\n{clean_text(item.request.song_name)}\n\n{STATE_LABELS[item.state]}\n{STAGE_LABELS.get(item.progress.stage, '')}\n\n{clean_text(str(item.output_path))}\n\n{clean_text(item.message)}"
        return f"\n{clean_text(row.title)}\n\n{clean_text(row.subtitle)}\n\nEnter 打开详情或继续。"

    def _batch_summary(self) -> str:
        return clip(f" 共 {len(self.batch_list.all_rows)} 首 · 筛选 {len(self.batch_list.rows)} 首 · 已选 {len(self.batch_list.selected)} 首", self.width)

    def current_list(self) -> ChoiceList | None:
        return {"home": self.home_list, "search": self.search_list, "playlists": self.playlist_list,
                "batch": self.batch_list, "tasks": self.task_list, "history": self.history_list,
                "settings": self.settings_list}.get(self.page)

    def _key_bindings(self) -> KeyBindings:
        keys = KeyBindings()
        editing = Condition(lambda: isinstance(self.application.layout.current_control, BufferControl))
        unobstructed = Condition(lambda: not self.modals and not self._closing)
        keys.add("escape", eager=False)(lambda event: self.back())
        keys.add("c-c")(lambda event: self.back())
        keys.add("q", filter=~editing)(lambda event: self.request_exit())
        keys.add("tab")(lambda event: event.app.layout.focus_next())
        keys.add("s-tab")(lambda event: event.app.layout.focus_previous())
        keys.add("escape", "enter", filter=Condition(lambda: self.page == "add" and not self.modals))(lambda event: self.detect_input())
        for index, page in enumerate(["home"] + [key for key, _ in NAVIGATION], 1):
            keys.add(f"f{index}", filter=unobstructed)(lambda event, page=page: self.navigate(page))
        for key, action in (("p", self.toggle_task), ("c", self.cancel_task), ("r", self.retry_task)):
            keys.add(key, filter=~editing & unobstructed & Condition(lambda: self.page == "tasks"))(lambda event, action=action: action())
        keys.add("/", filter=~editing & unobstructed)(lambda event: self.focus_filter())
        return keys

    def notify(self, message: str, error: bool = False) -> None:
        self.notice = redact_diagnostic_text(message, [self.session.cookie, self.session.proxy_password])
        self.notice_error = error
        self.application.invalidate()

    def _apply_proxy(self) -> None:
        s = self.session
        configure_proxy(s.proxy_type, s.proxy_host, s.proxy_port, s.proxy_username, s.proxy_password)

    def _focus_page(self) -> None:
        target: FocusableElement = self.current_list() or self.add_input
        if self.page == "search" and not self.search_results:
            target = self.search_input
        self.application.layout.focus(target)

    def navigate(self, page: str) -> None:
        if self._closing:
            return
        self.cancel_operations()
        self.modals.clear()
        self.generation += 1
        self.page = page
        self._focus_page()
        if page == "history":
            self.refresh_history()
        if page == "playlists" and not self.playlists_loaded:
            self.load_playlists()
        self.application.invalidate()

    def back(self) -> None:
        if self._closing:
            return
        if self.too_small:
            self.request_exit()
        elif self.modals:
            self.close_modal()
        elif self.page == "batch":
            self.navigate("playlists" if self._playlist_return else "add")
        elif self.page == "home":
            self.request_exit()
        else:
            self.navigate("home")

    def focus_filter(self) -> None:
        field = {"search": self.search_input, "batch": self.batch_filter,
                 "history": self.history_filter, "tasks": self.task_filter}.get(self.page)
        if field:
            self.application.layout.focus(field)

    def show_modal(self, container: AnyContainer, focus: FocusableElement) -> None:
        self.modals.append(Modal(container, focus, self.application.layout.current_control))
        self.application.layout.focus(focus)
        self.application.invalidate()

    def close_modal(self, *, cancel_operations: bool = True) -> None:
        if cancel_operations:
            self.cancel_operations()
            self.generation += 1
        if not self.modals:
            return
        modal = self.modals.pop()
        try:
            self.application.layout.focus(modal.previous_focus)
        except ValueError:
            self._focus_page()
        self.application.invalidate()

    def show_text(self, title: str, text: str, actions: list[tuple[str, Callable[[], None]]] | None = None) -> None:
        body = TextArea(text=redact_diagnostic_text(text, [self.session.cookie, self.session.proxy_password]),
                        read_only=True, scrollbar=True, wrap_lines=True)
        buttons = [Button(label, handler=callback) for label, callback in (actions or [])]
        back = Button("返回", handler=self.close_modal)
        buttons.append(back)
        dialog = Dialog(title=clean_text(title), body=body, buttons=buttons, with_background=False)
        self.show_modal(dialog, buttons[0])

    def confirm(self, title: str, message: str, action: Callable[[], None]) -> None:
        def yes() -> None:
            self.close_modal(cancel_operations=False)
            action()
        no = Button("返回", handler=self.close_modal)
        dialog = Dialog(title=title, body=Label(message), buttons=[Button("确认", handler=yes), no], with_background=False)
        self.show_modal(dialog, no)

    def cancel_operations(self) -> None:
        for op in self.operations:
            op.cancel.set()

    def start_operation(self, name: str, worker: Callable[[threading.Event], R], done: Callable[[R], None],
                        retry: Callable[[], None] | None = None) -> None:
        if self._closing:
            return
        for op in self.operations:
            if op.name == name:
                op.cancel.set()
        cancel = threading.Event()
        generation = self.generation

        async def run() -> None:
            try:
                async with self._worker_slots:
                    if cancel.is_set():
                        return
                    result = await asyncio.to_thread(worker, cancel)
                if not cancel.is_set() and generation == self.generation and not self._closing:
                    done(result)
            except DownloadCanceled:
                pass
            except MusicFetchError as err:
                if cancel.is_set() or generation != self.generation:
                    return
                if err.code == "AUTH_EXPIRED":
                    self.clear_login()
                    self.notify("登录已过期，请重新登录。", True)
                    self.login(retry)
                else:
                    self.notify(user_error_message(err.code, err.message), True)
            except Exception as err:
                if not cancel.is_set() and generation == self.generation:
                    self.notify(str(err), True)
                    logger.exception("Terminal operation failed. operation=%s", name)
            finally:
                self.operations[:] = [op for op in self.operations if op.cancel is not cancel]
                self.application.invalidate()

        task = asyncio.create_task(run())
        self.operations.append(Operation(name, cancel, task))
        self.application.invalidate()

    def ensure_login(self, action: Callable[[], None]) -> None:
        if not self.session.cookie:
            self.login(action)
        elif self.validated_login:
            action()
        else:
            cookie = self.session.cookie
            def ready(profile) -> None:
                self.nickname = profile.nickname
                self.validated_login = True
                action()
            self.start_operation("校验登录", lambda cancel: fetch_account_profile(cookie, timeout=5), ready, retry=action)

    def clear_login(self) -> None:
        self.session.cookie = ""
        self.session.remember_login = False
        self.nickname = ""
        self.validated_login = False
        self.queue.set_cookie("")
        try:
            self.session_store.save(self.session)
        except OSError as err:
            self.notify(f"登录状态保存失败：{err}", True)

    def login(self, after: Callable[[], None] | None = None) -> None:
        if any(op.name == "扫码登录" and not op.cancel.is_set() for op in self.operations):
            return
        status = Label("正在打开隔离的官网扫码窗口…")
        cancel_button = Button("取消登录", handler=self.close_modal)
        self.show_modal(Dialog(title="网易云官网扫码", body=status, buttons=[cancel_button], with_background=False), cancel_button)
        loop = asyncio.get_running_loop()

        def worker(cancel: threading.Event):
            def update(message: str) -> None:
                def apply() -> None:
                    if not cancel.is_set():
                        status.text = clean_text(message)
                        self.application.invalidate()
                loop.call_soon_threadsafe(apply)
            cookie = normalize_cookie(run_official_login(on_status=update, cancel_event=cancel))
            if cancel.is_set():
                raise DownloadCanceled()
            if "MUSIC_U=" not in cookie:
                raise ValueError("扫码未返回有效登录凭据，请重试。")
            profile = fetch_account_profile(cookie, timeout=self.session.detect_timeout_sec)
            return cookie, profile

        def ready(result) -> None:
            cookie, profile = result
            draft = replace(self.session, cookie=cookie, remember_login=True)
            self.session_store.save(draft)
            self.session = draft
            self.nickname = profile.nickname
            self.validated_login = True
            self.queue.set_cookie(cookie)
            self._auth_notified = False
            self.close_modal(cancel_operations=False)
            self.notify(f"登录成功：{self.nickname or '已登录'}")
            if after:
                after()
        self.start_operation("扫码登录", worker, ready)

    def detect_input(self) -> None:
        raw = self.add_input.text.strip()
        if not raw:
            self.notify("请粘贴链接、歌曲 ID 或分享文案。")
            return
        self._playlist_return = False
        self.ensure_login(lambda: self.detect(raw))

    def detect(self, raw: str) -> None:
        cookie = self.session.cookie
        self.start_operation("识别歌曲", lambda cancel: run_batch_detect(
            raw, cookie, self.session.detect_timeout_sec, cancel_event=cancel), self.show_batch,
            retry=lambda: self.detect(raw))

    def show_batch(self, rows: list[BatchDetectRow]) -> None:
        auth = next((row for row in rows if "AUTH_EXPIRED" in row.message), None)
        if auth:
            self.clear_login()
            self.notify("识别中登录过期，可重新登录后再次提交。", True)
        self.batch_rows = {f"{i}:{row.song_id}": row for i, row in enumerate(rows)}
        choices = [Choice(key, row.song_name or row.song_id or row.raw_input,
                          f"{row.artist} · {row.album_name} · {format_bytes(row.media_size_bytes) if row.media_size_bytes else '大小未知'} · {row.message or row.status}",
                          row.status == "ready") for key, row in self.batch_rows.items()]
        self.batch_list.selected.clear()
        self.batch_list.set_rows(choices)
        self.batch_list.select_all()
        self.page = "batch"
        self.modals.clear()
        self._focus_page()
        self.notify(f"识别完成：{len(rows)} 条，可下载 {sum(row.status == 'ready' for row in rows)} 条。")

    def download_selection(self) -> None:
        selected = [row for key, row in self.batch_rows.items() if key in self.batch_list.selected and row.status == "ready"]
        if not selected:
            self.notify("请用空格勾选可下载歌曲。")
            return
        self.open_download([self.request_for_row(row) for row in selected])

    def request_for_row(self, row: BatchDetectRow) -> DownloadRequest:
        return DownloadRequest(row.song_id, row.song_name, self.default_options(), row.artist, row.album_name, row.cover_url)

    def default_options(self) -> DownloadOptions:
        return DownloadOptions(self.session.last_download_dir, self.session.default_target_format, self.session.default_lyric_mode)

    def open_download(self, requests: list[DownloadRequest], *, force: bool = False) -> None:
        if not self.session.cookie:
            self.login(lambda: self.open_download(requests, force=force))
            return
        options = requests[0].options
        if len(requests) == 1 and not options.rename:
            options = replace(options, rename=sanitize_filename(f"{requests[0].song_name or 'song'}-{requests[0].song_id}"))

        def save(chosen: DownloadOptions) -> None:
            # Save first so a persistence failure cannot silently enqueue a second copy on retry.
            draft = replace(self.session, last_download_dir=chosen.out_dir)
            self.session_store.save(draft)
            self.session = draft
            before = len(self.queue.items)
            for request in requests:
                self.queue.enqueue(replace(request, options=chosen), force=force)
            self.modals.clear()
            self._focus_page()
            self.refresh_tasks()
            self.notify(f"已处理 {len(requests)} 首，新增 {len(self.queue.items) - before} 个任务；F5 查看进度。")
        form = DownloadForm(options, len(requests), save, self.close_modal, self._ffmpeg)
        self.show_modal(form.dialog, form.submit)

    def batch_detail(self) -> None:
        current = self.batch_list.current
        if not current:
            return
        row = self.batch_rows[current.key]
        actions: list[tuple[str, Callable[[], None]]] = []
        if row.status == "ready":
            actions = [("下载", lambda: self.open_download([self.request_for_row(row)])),
                       ("试听", lambda: self.preview(row.song_id, row.song_name))]
        self.show_text(row.song_name or "识别结果", f"歌曲：{row.song_name}\n歌手：{row.artist}\n专辑：{row.album_name}\n"
                       f"时长：{format_duration(row.duration_ms)}\n大小：{format_bytes(row.media_size_bytes)}\n"
                       f"状态：{row.status}\n{row.message}", actions)

    def _accept_search(self) -> bool:
        self.search()
        return True

    def search(self) -> None:
        keyword = self.search_input.text.strip()
        if not keyword:
            self.notify("请输入歌曲名或歌手名。")
            return
        def action() -> None:
            self.start_operation("搜索", lambda cancel: search_songs(keyword, self.session.cookie, timeout=self.session.detect_timeout_sec),
                                 self.show_search, retry=self.search)
        self.ensure_login(action)

    def show_search(self, results: list[SearchResult]) -> None:
        self.search_loaded = True
        self.search_results = {row.song_id: row for row in results}
        self.search_list.set_rows([Choice(row.song_id, row.song_name,
                                         f"{row.artist} · {row.album} · {format_duration(row.duration_ms)}") for row in results])
        self.application.layout.focus(self.search_list)
        self.notify(f"找到 {len(results)} 首歌曲。" if results else "未找到相关歌曲，可修改关键词重试。")

    def search_detail(self, key: str) -> None:
        row = self.search_results[key]
        request = DownloadRequest(row.song_id, row.song_name, self.default_options(), row.artist or "", row.album or "")
        self.show_text(row.song_name, f"歌名：{row.song_name}\n歌手：{row.artist}\n专辑：{row.album}\n时长：{format_duration(row.duration_ms)}",
                       [("下载", lambda: self.open_download([request])), ("试听", lambda: self.preview(row.song_id, row.song_name))])

    def preview(self, song_id: str, song_name: str) -> None:
        self.ensure_login(lambda: self.start_operation("准备试听", lambda cancel: download_preview_to_temp(
            song_id, song_name, self.session.cookie, self.session.download_timeout_sec, cancel_checker=cancel.is_set),
            self.open_path, retry=lambda: self.preview(song_id, song_name)))

    def load_playlists(self) -> None:
        self.ensure_login(lambda: self.start_operation("获取歌单", lambda cancel: fetch_user_playlists(
            self.session.cookie, timeout=self.session.detect_timeout_sec), self.show_playlists, retry=self.load_playlists))

    def show_playlists(self, playlists: list[UserPlaylist]) -> None:
        self.playlists_loaded = True
        self.playlists = {row.playlist_id: row for row in playlists}
        self.playlist_list.set_rows([Choice(row.playlist_id, row.name, f"{row.song_count} 首 · {row.creator}") for row in playlists])
        self.application.layout.focus(self.playlist_list)
        self.notify(f"共 {len(playlists)} 个歌单。" if playlists else "账号暂无歌单。")

    def playlist_detail(self, key: str) -> None:
        self._playlist_return = True
        self.ensure_login(lambda: self.detect(f"https://music.163.com/playlist?id={key}"))

    def refresh_tasks(self) -> None:
        self.task_list.set_rows([Choice(item.task_id, item.request.song_name,
            f"{STATE_LABELS[item.state]} · {STAGE_LABELS.get(item.progress.stage, '') if item.state in {'running', 'paused'} else item.message} · "
            f"{format_bytes(item.progress.downloaded) if item.state not in FINAL_STATES else format_bytes(item.size_bytes)}") for item in self.queue.items])

    def task_detail(self, key: str) -> None:
        item = self.queue.get(key)
        actions: list[tuple[str, Callable[[], None]]] = []
        if item.state in {"failed", "canceled"}:
            actions.append(("重试", lambda: self.retry_task(key)))
        elif item.state in {"success", "skipped"}:
            actions += [("打开目录", lambda: self.open_path(item.output_path.parent)),
                        ("重新下载", lambda: self.open_download([item.request], force=True))]
        elif item.state == "waiting_login":
            actions.append(("登录继续", lambda: self.login()))
        else:
            actions += [("暂停/继续", lambda: self.toggle_task(key)), ("取消任务", lambda: self.cancel_task(key))]
        self.show_text(item.request.song_name, f"状态：{STATE_LABELS[item.state]}\n文件：{item.output_path}\n"
                       f"格式：{item.request.options.target_format}\n歌词：{item.request.options.lyric_mode}\n{item.message}", actions)

    def _task_key(self, key: str | None) -> str | None:
        return key or (self.task_list.current.key if self.task_list.current else None)

    def toggle_task(self, key: str | None = None) -> None:
        key = self._task_key(key)
        if key:
            item = self.queue.get(key)
            if item.state == "paused":
                self.queue.resume(key)
            else:
                self.queue.pause(key)
            self.refresh_tasks()
            self.notify(f"{item.request.song_name}：{STATE_LABELS[item.state]}")

    def cancel_task(self, key: str | None = None) -> None:
        key = self._task_key(key)
        if key:
            self.queue.cancel(key)
            self.refresh_tasks()
            self.notify("已取消任务；运行中的任务正在清理。")

    def retry_task(self, key: str | None = None) -> None:
        key = self._task_key(key)
        if key:
            item = self.queue.get(key)
            if item.state in {"failed", "canceled"}:
                self.open_download([item.request])
            else:
                self.notify("只有失败或取消的任务需要重试。")

    def confirm_cancel_all(self) -> None:
        if self.queue.unfinished:
            self.confirm("取消所有任务", f"取消 {len(self.queue.unfinished)} 个未完成任务？", self.queue.cancel_all)

    def refresh_history(self) -> None:
        try:
            rows = filter_download_history(self.history_store.load(), query=self.history_filter.text,
                                           status_filter=self.history_status.value)
            self.records = {record.output_path: record for record in rows}
            self.history_list.set_rows([Choice(record.output_path, record.song_name,
                f"{STATE_LABELS.get(record.status, record.status)} · {record.downloaded_at} · {Path(record.output_path).name}") for record in rows])
        except OSError as err:
            self.notify(f"历史读取失败：{err}", True)

    def _cycle_history_status(self) -> None:
        self.history_status.cycle()
        self.refresh_history()

    def history_detail(self, key: str) -> None:
        record = self.records[key]
        actions = [("打开目录", lambda: self.open_path(Path(record.output_path).expanduser().parent)),
                   ("重试" if record.status in {"failed", "canceled"} else "重新下载",
                    lambda: self.open_download([DownloadRequest.from_record(record)], force=record.status == "success")),
                   ("删除", lambda: self.confirm("删除文件与记录", f"确认删除？\n{record.output_path}", lambda: self.delete_record(record)))]
        self.show_text(record.song_name, f"歌曲：{record.song_name}\n状态：{STATE_LABELS.get(record.status, record.status)}\n"
                       f"文件：{record.output_path}\n大小：{format_bytes(record.size_bytes)}\n时间：{record.downloaded_at}\n"
                       f"{user_error_message(record.error_code, '') if record.error_code else ''}", actions)

    def delete_record(self, record: DownloadRecord) -> None:
        path = Path(record.output_path).expanduser()
        if any(item.output_path == path for item in self.queue.unfinished):
            self.notify("该文件有未完成任务，请先取消任务。", True)
            return
        try:
            path.unlink(missing_ok=True)
            self.history_store.remove_by_path(record.output_path)
        except OSError as err:
            self.notify(f"删除失败，记录已保留：{err}", True)
            return
        self.modals.clear()
        self._focus_page()
        self.refresh_history()
        self.notify("文件和记录已删除。")

    def export_text(self, title: str, content: str, filename: str) -> None:
        target = TextArea(text=str(Path(self.session.last_download_dir).expanduser() / filename), multiline=False)
        error = Label("")
        def save() -> None:
            path = Path(target.text).expanduser()
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("x", encoding="utf-8-sig") as handle:
                    handle.write(content)
                self.close_modal(cancel_operations=False)
                self.notify(f"已导出：{path}")
            except FileExistsError:
                error.text = "文件已存在，请更换文件名。"
            except OSError as err:
                error.text = f"导出失败：{err}"
        submit = Button("导出", handler=save)
        dialog = Dialog(title=title, body=HSplit([Label("导出路径"), target, error]),
                        buttons=[submit, Button("返回", handler=self.close_modal)], with_background=False)
        self.show_modal(dialog, submit)

    def export_batch(self) -> None:
        self.export_text("导出识别结果", build_batch_results_csv(list(self.batch_rows.values())), self.export_name("batch", "csv"))

    def export_history(self) -> None:
        self.export_text("导出筛选历史", build_download_history_csv(list(self.records.values())), self.export_name("history", "csv"))

    @staticmethod
    def export_name(prefix: str, suffix: str) -> str:
        return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.{suffix}"

    def settings_action(self, key: str) -> None:
        if key in {"general", "network", "performance"}:
            form = SettingsForm(self.session, lambda draft: self.save_settings(draft, key), self.close_modal, key)
            self.show_modal(form.dialog, form.submit)
        elif key == "login":
            self.login()
        elif key == "logout":
            self.confirm("退出账号", "退出账号会取消未完成任务，历史记录保留。", self.logout)
        elif key == "diagnostics":
            self.diagnostics()
        elif key == "update":
            self.check_update()

    def save_settings(self, draft: AppSession, section: str) -> None:
        names = {"general": ["last_download_dir", "default_target_format", "default_lyric_mode", "ui_theme"],
                 "network": ["proxy_type", "proxy_host", "proxy_port", "proxy_username", "proxy_password"],
                 "performance": ["detect_timeout_sec", "download_timeout_sec", "download_retry_count", "download_concurrency"]}[section]
        # Merge only edited preferences; a background login expiry may have changed credentials.
        saved = replace(self.session, **{name: getattr(draft, name) for name in names})
        self.session_store.save(saved)
        self.session = saved
        self._apply_proxy()
        self.queue.concurrency = saved.download_concurrency
        self.queue.timeout = saved.download_timeout_sec
        self.queue.retry_count = saved.download_retry_count
        self.close_modal(cancel_operations=False)
        self.notify("设置已保存。")

    def logout(self) -> None:
        self.queue.cancel_all()
        self.clear_login()
        self.playlists_loaded = False
        self.playlists.clear()
        self.playlist_list.set_rows([])
        self.notify("已退出账号，设置和历史仍可使用。")

    def diagnostics(self) -> None:
        session = replace(self.session)
        def worker(cancel: threading.Event) -> str:
            probes = run_network_diagnostics(timeout=5)
            context = DiagnosticContext(APP_VERSION, default_log_path(), bool(session.cookie), session.proxy_type,
                                        session.proxy_host, session.proxy_port, bool(session.proxy_username), is_ffmpeg_available())
            return build_diagnostic_report(context, probes=probes, log_tail=read_log_tail(default_log_path()),
                                           sensitive_values=[session.cookie, session.proxy_password])
        def done(report: str) -> None:
            self.show_text("诊断结果", report, [("导出报告", lambda: self.export_text("导出诊断报告", report, self.export_name("diagnostics", "txt")))])
        self.start_operation("网络诊断", worker, done)

    def check_update(self) -> None:
        def done(result: tuple[str, str]) -> None:
            latest, url = result
            text = f"当前版本：{APP_VERSION}\n最新版本：{latest}\n{url}"
            if version_key(latest) <= version_key(APP_VERSION):
                text = f"当前已是最新版本：{APP_VERSION}"
            self.show_text("检查更新", text)
        self.start_operation("检查更新", lambda cancel: check_for_updates_cached(timeout=8), done)

    def open_path(self, path: Path) -> None:
        if not path.exists():
            self.notify(f"路径不存在：{path}", True)
            return
        def worker(cancel: threading.Event) -> None:
            if sys.platform == "win32":
                os.startfile(str(path))
            else:
                subprocess.run(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        self.start_operation("打开文件", worker, lambda result: self.notify("已交给系统打开。"))

    def request_exit(self) -> None:
        if self._closing:
            return
        if self.queue.unfinished:
            self.confirm("退出程序", f"还有 {len(self.queue.unfinished)} 个任务。确认取消并退出？", self.begin_shutdown)
        else:
            self.begin_shutdown()

    def begin_shutdown(self) -> None:
        self._closing = True
        self.cancel_operations()
        self.queue.close()
        self.modals.clear()
        self._focus_page()

    async def _drive(self) -> None:
        while True:
            self.queue.poll()
            signature = [(item.task_id, item.state, item.progress, item.message) for item in self.queue.items]
            if signature != self._queue_signature:
                self._queue_signature = signature
                self.refresh_tasks()
                if self.page == "history":
                    self.refresh_history()
            if self.queue.auth_required and not self._auth_notified:
                self._auth_notified = True
                self.clear_login()
                self.notify("登录已过期，任务已保留。设置 → 登录后继续。", True)
            if self.queue.history_error:
                self.notify(self.queue.history_error, True)
            if self._closing and not self.queue.unfinished and not self.operations:
                self.application.exit()
                return
            self.application.invalidate()
            await asyncio.sleep(0.1)

    async def run_async(self) -> int:
        driver: asyncio.Task[None] | None = None
        def started() -> None:
            nonlocal driver
            driver = asyncio.create_task(self._drive())
        try:
            await self.application.run_async(pre_run=started)
        finally:
            self.begin_shutdown()
            if driver:
                driver.cancel()
                try:
                    await driver
                except asyncio.CancelledError:
                    pass
            # On EOF or terminal disconnect, wait for workers before returning.
            if self.operations:
                await asyncio.gather(*(op.task for op in self.operations), return_exceptions=True)
            while self.queue.unfinished:
                self.queue.poll()
                await asyncio.sleep(0.05)
        return 0

    def run(self) -> int:
        return asyncio.run(self.run_async())


def main() -> int:
    setup_logging(default_log_path(), level=logging.INFO)
    try:
        return TuiApp().run()
    except (KeyboardInterrupt, EOFError):
        return 0
    except Exception as err:
        logger.exception("Terminal application stopped unexpectedly.")
        print(f"启动失败：{redact_diagnostic_text(str(err))}", file=sys.stderr)
        return 1


__all__ = ["TuiApp", "main"]
