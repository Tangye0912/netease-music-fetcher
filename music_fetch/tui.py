#!/usr/bin/env python3
"""Interactive terminal UI for music-fetch.

Bare `music-fetch` (no arguments) opens this keyboard-driven interface:
official browser QR login, numbered menus, checkbox multi-select for batch
downloads, and progress bars with pause/resume/cancel keys.  All heavy lifting
stays in the pure modules (api/audio/pipeline/batch_*).
"""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.shortcuts import ProgressBar
from prompt_toolkit.shortcuts.progress_bar.base import ProgressBarCounter

from music_fetch.api import (
    MusicFetchError,
    SUPPORTED_GUI_AUDIO_FORMATS,
    detect_song,
    fetch_account_profile,
    fetch_user_playlists,
    normalize_cookie,
    parse_input_resource,
    search_songs,
)
from music_fetch.app_logging import default_log_path, setup_logging
from music_fetch.app_settings import (
    APP_NAME,
    APP_VERSION,
    CONFIG_DIR,
    DOWNLOAD_HISTORY_FILE,
    MAX_CLI_CONCURRENCY,
    MIN_DOWNLOAD_CONCURRENCY,
    PROJECT_GITHUB_URL,
    SESSION_FILE,
)
from music_fetch.app_stores import AppSession, DownloadHistoryStore, DownloadRecord, SessionStore
from music_fetch.audio import is_ffmpeg_available, resolve_output_path, sanitize_filename
from music_fetch.batch_download import BatchDownloadSession, format_speed
from music_fetch.batch_inspect import run_batch_detect
from music_fetch.batch_models import format_bytes, format_duration, probe_media_size_bytes
from music_fetch.batch_results import build_batch_results_csv, retryable_failed_rows, summarize_batch_rows
from music_fetch.diagnostics import (
    DiagnosticContext,
    build_diagnostic_report,
    read_log_tail,
    run_network_diagnostics,
)
from music_fetch.download_retry import retry_target_format
from music_fetch.download_runner import DownloadJob, DownloadJobResult, JOB_RUNNING_STATES
from music_fetch.download_tasks import (
    TASK_STATE_CANCELED,
    TASK_STATE_FAILED,
    TASK_STATE_SUCCESS,
    build_task_id,
)
from music_fetch.error_texts import user_error_message
from music_fetch.history_results import (
    build_download_history_csv,
    filter_download_history,
    paginate_download_history,
)
from music_fetch.network import ProxyConfigError, configure_proxy, get_proxy_config, normalize_proxy_config
from music_fetch.version_check import check_for_updates_cached, version_key
import music_fetch.tui_utils as U
import music_fetch.ui_texts as T

logger = logging.getLogger("music_fetch.tui")

MENU_SINGLE = "单曲下载"
MENU_SEARCH = "搜索下载"
MENU_PLAYLISTS = "我的歌单"
MENU_BATCH = "批量下载"
MENU_HISTORY = "下载历史"
MENU_SETTINGS = "软件设置"
MENU_DIAGNOSTICS = "诊断中心"
MENU_UPDATE = "检查更新"
MENU_LOGOUT = "退出登录"
MENU_LOGIN = "登录 / 重新登录"
MENU_QUIT = "退出"

_QUALITY_LABELS = {
    "standard": "标准",
    "higher": "较高",
    "exhigh": "极高",
    "lossless": "无损",
    "hires": "Hi-Res",
}


def _quality_label(level: str, encode_type: str = "") -> str:
    label = _QUALITY_LABELS.get((level or "").strip().lower(), level or "未知")
    if encode_type:
        return f"{label}（{encode_type}）"
    return label


class TuiApp:
    """Keyboard-driven application shell."""

    def __init__(
        self,
        session_store: Optional[SessionStore] = None,
        history_store: Optional[DownloadHistoryStore] = None,
    ) -> None:
        self.session_store = session_store or SessionStore(SESSION_FILE)
        self.history_store = history_store or DownloadHistoryStore(DOWNLOAD_HISTORY_FILE)
        self.session: AppSession = self.session_store.load()
        U.set_theme(self.session.ui_theme)
        self._nickname = ""
        self._apply_proxy()

    # ── bootstrap ─────────────────────────────────────────────────

    def _apply_proxy(self) -> None:
        try:
            configure_proxy(
                self.session.proxy_type,
                self.session.proxy_host,
                self.session.proxy_port,
                self.session.proxy_username,
                self.session.proxy_password,
            )
        except ProxyConfigError as err:
            logger.warning("Stored proxy invalid, falling back to direct. reason=%s", err)
            configure_proxy()
        self._proxy_label = self._proxy_summary()

    @staticmethod
    def _proxy_summary() -> str:
        config = get_proxy_config()
        if not config.proxy_type:
            return "直连"
        type_label = "SOCKS5" if config.proxy_type == "socks5" else "HTTP"
        return f"{type_label} {config.host}:{config.port}"

    def _login_label(self) -> str:
        if not self.session.cookie:
            return "未登录"
        if self._nickname:
            return self._nickname
        return "已登录"

    def _validate_session_login(self) -> bool:
        """Return True when a usable login exists; clear expired cookies.

        An expired/invalid session cookie must not silently keep the menu
        unlocked — the user has to re-login through the browser flow.
        """
        if not self.session.cookie:
            return False
        try:
            profile = fetch_account_profile(self.session.cookie, timeout=6)
            self._nickname = profile.nickname
            return True
        except MusicFetchError as err:
            self._nickname = ""
            if err.code == "AUTH_EXPIRED":
                return False
            # Transient network failure: keep the session and let individual
            # operations surface the error instead of wrongly logging out.
            return bool(self.session.cookie)

    def run(self) -> int:
        # A missing or expired app-owned credential always starts the isolated
        # official QR flow.  No browser profile is inspected for a login state.
        if self.session.cookie and not self._validate_session_login():
            self._clear_login()
        if not self.session.cookie:
            self._screen_login()
        while True:
            try:
                U.clear_screen()
            except Exception:  # pragma: no cover - clear may fail on exotic terminals
                pass
            U.print_header(f"{APP_NAME} v{APP_VERSION}")
            if self.session.cookie:
                U.print_status(
                    [
                        ("登录", self._login_label()),
                        ("代理", self._proxy_label),
                        ("目录", self.session.last_download_dir),
                        ("ffmpeg", "可用" if is_ffmpeg_available() else "未安装"),
                    ]
                )
                options = [
                    MENU_SINGLE,
                    MENU_SEARCH,
                    MENU_PLAYLISTS,
                    MENU_BATCH,
                    MENU_HISTORY,
                    MENU_SETTINGS,
                    MENU_DIAGNOSTICS,
                    MENU_UPDATE,
                    MENU_LOGOUT,
                    MENU_QUIT,
                ]
            else:
                U.print_info("  尚未登录：请选择 1 登录后使用全部功能。")
                options = [MENU_LOGIN, MENU_QUIT]
            try:
                choice = U.menu("主菜单", options, shortcuts={"q": len(options)})
            except (KeyboardInterrupt, EOFError):
                print()
                return 0
            label = options[choice - 1]
            if label == MENU_QUIT:
                return 0
            if not self.session.cookie:
                if label == MENU_LOGIN:
                    self._screen_login()
                continue
            if label == MENU_SINGLE:
                self._screen_single()
            elif label == MENU_SEARCH:
                self._screen_search()
            elif label == MENU_PLAYLISTS:
                self._screen_playlists()
            elif label == MENU_BATCH:
                self._screen_batch()
            elif label == MENU_HISTORY:
                self._screen_history()
            elif label == MENU_SETTINGS:
                self._screen_settings()
            elif label == MENU_DIAGNOSTICS:
                self._screen_diagnostics()
            elif label == MENU_UPDATE:
                self._screen_check_update()
            elif label == MENU_LOGOUT:
                if U.confirm("确定退出当前账号？", default=True):
                    self._clear_login()
                    U.print_success("已退出登录。")

    # ── login ─────────────────────────────────────────────────────

    def _screen_login(self) -> None:
        U.print_header("登录")
        self._login_with_browser()

    def _login_with_browser(self) -> None:
        from music_fetch.browser_login import BrowserLoginError, run_official_login

        U.print_info("即将打开网易云音乐官网登录页（浏览器）...")
        try:
            cookie = run_official_login(
                timeout=300,
                on_status=lambda message: U.print_info(message),
            )
        except BrowserLoginError as err:
            U.print_error(str(err))
            return
        except MusicFetchError as err:
            U.print_error(user_error_message(err.code, err.message))
            return
        self._accept_cookie(cookie)

    def _accept_cookie(self, cookie: str) -> None:
        cookie = normalize_cookie(cookie)
        if "MUSIC_U=" not in cookie:
            U.print_error("登录返回的数据里没有 MUSIC_U 凭证，请重试。")
            return
        U.print_info("校验登录状态...")
        try:
            profile = fetch_account_profile(cookie, timeout=self.session.detect_timeout_sec)
        except MusicFetchError as err:
            U.print_error(f"登录校验失败：{user_error_message(err.code, err.message)}")
            return
        self.session.cookie = cookie
        self.session.remember_login = True
        self.session_store.save(self.session)
        self._nickname = profile.nickname
        U.print_success(f"登录成功：{self._nickname or '已登录'}")

    def _require_login(self) -> bool:
        if self.session.cookie:
            return True
        U.print_warning(T.MSG_NEED_LOGIN_ANY)
        return U.confirm("现在登录？", default=True) and self._login_and_return()

    def _clear_login(self) -> None:
        self.session.cookie = ""
        self.session.remember_login = False
        self._nickname = ""
        self.session_store.save(self.session)

    def _handle_auth_expired(self) -> bool:
        """Discard an expired app credential before starting a fresh QR login."""
        self._clear_login()
        U.print_warning("登录凭证已失效，需要重新扫码登录。")
        return self._login_and_return()

    def _login_and_return(self) -> bool:
        self._screen_login()
        return bool(self.session.cookie)

    # ── single song ───────────────────────────────────────────────

    def _screen_single(self) -> None:
        U.print_header(MENU_SINGLE)
        value = U.ask("粘贴歌曲链接 / 分享文案 / 歌曲 ID（回车返回）")
        if not value:
            return
        if not self._require_login():
            return
        # Album links route into the batch flow (playlist links keep their
        # dedicated entry under 我的歌单 / 批量下载).
        try:
            resource_type, resource_id = parse_input_resource(value)
        except MusicFetchError:
            resource_type, resource_id = "song", ""
        if resource_type == "album":
            U.print_info("检测到专辑链接，专辑将进入批量下载流程。")
            if U.confirm(f"批量下载专辑（ID {resource_id}）？", default=True):
                self._batch_flow(f"https://music.163.com/album?id={resource_id}")
            return
        with U.spinner("检测中..."):
            try:
                result = detect_song(value, self.session.cookie, timeout=self.session.detect_timeout_sec)
            except MusicFetchError as err:
                U.print_error(user_error_message(err.code, err.message))
                if err.code == "AUTH_EXPIRED":
                    self._handle_auth_expired()
                return
        rows = [
            ("歌名", result.song_name or "未知"),
            ("艺人", result.artist or "-"),
            ("专辑", result.album_name or "-"),
            ("音质", _quality_label(result.level, result.encode_type)),
            ("时长", format_duration(result.duration_ms)),
        ]
        if result.can_download and result.media_url:
            size_bytes = probe_media_size_bytes(result.media_url, timeout=min(8, self.session.detect_timeout_sec))
            if size_bytes:
                rows.append(("大小", format_bytes(size_bytes)))
        U.print_panel("歌曲信息", rows)
        if not result.can_download:
            U.print_error(f"该歌曲不可下载：{result.unavailable_reason or '版权/地区/VIP 限制'}")
            return
        while True:
            action = U.menu("下一步", ["直接下载", "试听（标准音质临时文件播放）", "返回"], shortcuts={"d": 1, "p": 2})
            if action == 3:
                return
            if action == 2:
                self._preview_song(result.song_id, result.song_name or "")
                continue
            break
        self._download_song(
            song_id=result.song_id,
            song_name=result.song_name or "",
            artist=result.artist,
            album_name=result.album_name,
            duration_ms=result.duration_ms,
            cover_url=result.cover_url,
        )

    def _preview_song(self, song_id: str, song_name: str) -> None:
        from music_fetch.audio import download_preview_to_temp

        with U.spinner("准备试听（下载标准音质临时文件）..."):
            try:
                preview_path = download_preview_to_temp(
                    song_id=song_id,
                    song_name=song_name,
                    cookie=self.session.cookie,
                    timeout=self.session.download_timeout_sec,
                )
            except MusicFetchError as err:
                U.print_error(user_error_message(err.code, err.message))
                return
        U.print_info(f"试听文件：{preview_path}")
        self._open_path(preview_path)

    # ── search ────────────────────────────────────────────────────

    def _screen_search(self) -> None:
        U.print_header(MENU_SEARCH)
        keyword = U.ask("输入歌曲名或歌手名（回车返回）")
        if not keyword:
            return
        if not self._require_login():
            return
        with U.spinner("搜索中..."):
            try:
                results = search_songs(keyword, self.session.cookie, timeout=self.session.detect_timeout_sec)
            except MusicFetchError as err:
                U.print_error(user_error_message(err.code, err.message))
                if err.code == "AUTH_EXPIRED":
                    self._handle_auth_expired()
                return
        if not results:
            U.print_warning("未找到相关歌曲。")
            return
        # Paginate so one screen always fits in the terminal window.
        page_size = 10
        total_pages = (len(results) + page_size - 1) // page_size
        page = 0
        while True:
            start = page * page_size
            page_results = results[start:start + page_size]
            rows = [
                (
                    str(index),
                    r.song_name,
                    r.artist or "-",
                    r.album or "-",
                    format_duration(r.duration_ms),
                )
                for index, r in enumerate(page_results, start=start + 1)
            ]
            U.print_table(["#", "歌名", "歌手", "专辑", "时长"], rows)
            U.print_info(f"第 {page + 1}/{total_pages} 页 · 共 {len(results)} 条")
            while True:
                raw = U.ask("输入序号下载（0 返回；n 下一页；p 上一页）").strip()
                if not raw or raw == "0":
                    return
                if raw.lower() == "n":
                    if page + 1 < total_pages:
                        page += 1
                        break
                    U.print_warning("已经是最后一页。")
                    continue
                if raw.lower() == "p":
                    if page > 0:
                        page -= 1
                        break
                    U.print_warning("已经是第一页。")
                    continue
                if raw.isdigit():
                    idx = int(raw) - 1  # 0-based index into results
                    if start <= idx < start + len(page_results):
                        picked = results[idx]
                        while True:
                            action = U.menu(
                                f"《{picked.song_name}》",
                                ["直接下载", "试听（标准音质临时文件播放）", "返回列表"],
                                shortcuts={"d": 1, "p": 2},
                            )
                            if action == 3:
                                break
                            if action == 2:
                                self._preview_song(picked.song_id, picked.song_name)
                                continue
                            self._download_song(
                                song_id=picked.song_id,
                                song_name=picked.song_name,
                                artist=picked.artist or None,
                                album_name=picked.album or None,
                                duration_ms=picked.duration_ms,
                            )
                            return
                        continue
                U.print_warning(f"请输入 {start + 1}-{start + len(page_results)} 的序号，0 返回，n/p 翻页。")

    def _pick_from_rows(self, prompt: str, count: int) -> Optional[int]:
        """Ask the user to pick a numbered row (1..count) or return (0 / empty)."""
        while True:
            raw = U.ask(f"{prompt}（0 返回）")
            if not raw or raw == "0":
                return None
            if raw.isdigit() and 1 <= int(raw) <= count:
                return int(raw)
            U.print_warning(f"请输入 1-{count} 的序号，或 0 返回。")

    # ── user playlists ────────────────────────────────────────────

    def _screen_playlists(self) -> None:
        U.print_header(MENU_PLAYLISTS)
        if not self._require_login():
            return
        with U.spinner("获取歌单列表..."):
            try:
                playlists = fetch_user_playlists(self.session.cookie, timeout=self.session.detect_timeout_sec)
            except MusicFetchError as err:
                U.print_error(user_error_message(err.code, err.message))
                if err.code == "AUTH_EXPIRED":
                    self._handle_auth_expired()
                return
        if not playlists:
            U.print_warning("暂无歌单。")
            return
        page_size = 10
        total_pages = (len(playlists) + page_size - 1) // page_size
        page = 0
        while True:
            start = page * page_size
            page_playlists = playlists[start:start + page_size]
            rows = [
                (
                    str(index),
                    pl.name,
                    str(pl.song_count),
                    pl.creator or "-",
                )
                for index, pl in enumerate(page_playlists, start=start + 1)
            ]
            U.print_table(["#", "歌单", "歌数", "创建者"], rows)
            U.print_info(f"第 {page + 1}/{total_pages} 页 · 共 {len(playlists)} 个歌单")
            while True:
                raw = U.ask("输入序号（0 返回；n 下一页；p 上一页）").strip()
                if not raw or raw == "0":
                    return
                if raw.lower() == "n":
                    if page + 1 < total_pages:
                        page += 1
                        break
                    U.print_warning("已经是最后一页。")
                    continue
                if raw.lower() == "p":
                    if page > 0:
                        page -= 1
                        break
                    U.print_warning("已经是第一页。")
                    continue
                if raw.isdigit():
                    index = int(raw) - 1
                    if start <= index < start + len(page_playlists):
                        picked = playlists[index]
                        self._batch_flow(f"https://music.163.com/playlist?id={picked.playlist_id}")
                        return
                U.print_warning(
                    f"请输入 {start + 1}-{start + len(page_playlists)} 的序号，0 返回，n/p 翻页。"
                )

    # ── batch ─────────────────────────────────────────────────────

    def _screen_batch(self) -> None:
        U.print_header(MENU_BATCH)
        if not self._require_login():
            return
        text = U.input_multiline("粘贴多行链接 / 歌单链接 / 分享文案（留空返回）")
        if not text.strip():
            return
        self._batch_flow(text)

    def _batch_flow(self, raw_input: str) -> None:
        U.print_info("批量识别中...")
        detect_total = [0]
        try:
            rows = run_batch_detect(
                raw_input,
                self.session.cookie,
                timeout=self.session.detect_timeout_sec,
                detect_concurrency=5,
                on_progress=lambda current, total, song_id: self._detect_progress(current, total, detect_total),
            )
        except MusicFetchError as err:
            U.print_error(user_error_message(err.code, err.message))
            if err.code == "AUTH_EXPIRED":
                self._handle_auth_expired()
            return
        if detect_total[0] > 0:
            print()
        if not rows:
            U.print_warning("未识别到任何歌曲，请检查输入内容。")
            return
        summary = summarize_batch_rows(rows)
        U.print_info(
            f"识别完成：共 {summary.total} 条，可下载 {summary.ready} 条，"
            f"重复 {summary.duplicate} 条，失败/不可下载 {summary.bad} 条。"
        )
        table_rows = [
            (
                f"{index}",
                row.song_name or row.song_id,
                format_bytes(row.media_size_bytes) if row.media_size_bytes else "-",
                T.batch_detect_status_text(row.status),
            )
            for index, row in enumerate(rows, start=1)
        ]
        U.print_table(["#", "歌曲", "大小", "状态"], table_rows)
        ready = [row for row in rows if row.status == "ready"]
        if not ready:
            U.print_warning("没有可下载的歌曲。")
            self._offer_batch_export(rows)
            return
        entries = [
            (f"{row.song_name or row.song_id}（{format_bytes(row.media_size_bytes) if row.media_size_bytes else '未知大小'}）", row.selected)
            for row in ready
        ]
        selected = U.multiselect("选择要下载的歌曲（空格勾选，回车确定，Esc 取消）", entries)
        if not selected:
            self._offer_batch_export(rows)
            return
        chosen = [ready[index] for index in selected]
        out_dir_raw = self._ask_with_cancel(
            "保存目录（直接回车用默认；输入 0 取消）", default=self.session.last_download_dir
        )
        if out_dir_raw is None:
            return
        out_dir = Path(out_dir_raw).expanduser()
        target_format = self._pick_format()
        if target_format is None:
            return
        lyric_mode = "bilingual" if U.confirm("同时下载歌词（原文 + 翻译合并）？", default=False) else "original"
        session = BatchDownloadSession(
            rows=chosen,
            out_dir=out_dir,
            cookie=self.session.cookie,
            history_store=self.history_store,
            target_format=target_format,
            timeout=self.session.download_timeout_sec,
            retry_count=self.session.download_retry_count,
            concurrency=self.session.download_concurrency,
            download_lyric=lyric_mode != "original",
            lyric_mode=lyric_mode,
        )
        self._run_batch_session(session)
        self.session.last_download_dir = str(out_dir)
        self.session_store.save(self.session)
        if session.auth_expired:
            self._handle_auth_expired()
            return
        failed_rows = retryable_failed_rows(rows)
        if failed_rows and U.confirm(f"有 {len(failed_rows)} 首下载失败，是否重试？", default=False):
            retry_session = BatchDownloadSession(
                rows=failed_rows,
                out_dir=out_dir,
                cookie=self.session.cookie,
                history_store=self.history_store,
                target_format=target_format,
                timeout=self.session.download_timeout_sec,
                retry_count=self.session.download_retry_count,
                concurrency=self.session.download_concurrency,
                download_lyric=lyric_mode != "original",
                lyric_mode=lyric_mode,
            )
            self._run_batch_session(retry_session)
            if retry_session.auth_expired:
                self._handle_auth_expired()
                return
        self._offer_batch_export(rows)

    @staticmethod
    def _detect_progress(current: int, total: int, state: list[int]) -> None:
        state[0] = total
        sys.stdout.write(f"\r  识别中 {current}/{total} ...    ")
        sys.stdout.flush()

    def _offer_batch_export(self, rows) -> None:
        if not rows:
            return
        if not U.confirm("导出批次结果 CSV？", default=False):
            return
        default_path = Path(self.session.last_download_dir).expanduser() / (
            f"batch_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        )
        target = Path(U.ask("导出路径", default=str(default_path))).expanduser()
        if not target.suffix:
            target = target.with_suffix(".csv")
        try:
            target.write_text(build_batch_results_csv(rows), encoding="utf-8-sig")
            U.print_success(f"批次结果已导出：{target}")
        except OSError as err:
            U.print_error(f"导出失败：{err}")

    # ── download runner / progress UI ─────────────────────────────

    def _run_job(self, job: DownloadJob) -> Optional[DownloadJobResult]:
        kb = KeyBindings()

        @kb.add("p")
        def _toggle_pause(event):  # noqa: ANN001 - prompt_toolkit event
            if job.is_paused:
                job.request_resume()
            else:
                job.request_pause()

        @kb.add("c")
        def _cancel(event):  # noqa: ANN001
            job.request_cancel()

        @kb.add("c-c")
        def _cancel_ctrl_c(event):  # noqa: ANN001
            job.request_cancel()

        job.start()
        with ProgressBar(
            title="下载中 — p 暂停/继续 · c 取消",
            key_bindings=kb,
            style=U.PROGRESS_STYLE,
        ) as pb:
            counter: ProgressBarCounter[object] = pb(total=None, label="准备下载...")
            while job.state() in JOB_RUNNING_STATES:
                snap = job.progress()
                counter.total = snap.total if snap.total > 0 else None
                counter.items_completed = snap.downloaded
                paused = "已暂停 · " if job.is_paused else ""
                size_text = (
                    f"{format_bytes(snap.downloaded)}/{format_bytes(snap.total)}"
                    if snap.total > 0
                    else format_bytes(snap.downloaded)
                )
                counter.label = f"{paused}{size_text} · {format_speed(snap.speed)}"
                pb.invalidate()
                time.sleep(0.1)
        return job.result()

    def _run_batch_session(self, session: BatchDownloadSession) -> None:
        kb = KeyBindings()

        @kb.add("p")
        def _pause_all(event):  # noqa: ANN001
            session.request_pause_all()

        @kb.add("r")
        def _resume_all(event):  # noqa: ANN001
            session.request_resume_all()

        @kb.add("c")
        def _cancel_all(event):  # noqa: ANN001
            session.request_cancel_all()

        @kb.add("c-c")
        def _cancel_ctrl_c(event):  # noqa: ANN001
            session.request_cancel_all()

        total_rows = session.counters().total
        with ProgressBar(
            title="批量下载 — p 暂停全部 · r 恢复全部 · c 取消",
            key_bindings=kb,
            style=U.PROGRESS_STYLE,
        ) as pb:
            counter: ProgressBarCounter[object] = pb(total=total_rows if total_rows else None, label="准备...")
            while not session.done:
                session.poll()
                counts = session.counters()
                partial = 0.0
                active_labels: list[str] = []
                for label, snap in session.active_jobs():
                    if snap.total > 0:
                        partial += min(snap.downloaded / snap.total, 1.0)
                    active_labels.append(f"{label[:16]} {format_bytes(snap.downloaded)}")
                counter.items_completed = int(counts.cursor + partial)
                state = "已暂停" if counts.paused else ("取消中" if counts.cancel_requested else "下载中")
                detail = " · ".join(active_labels[:2]) if active_labels else "等待任务启动"
                counter.label = (
                    f"{state} {counts.cursor}/{counts.total} 成功 {counts.success} "
                    f"失败 {counts.failed} 取消 {counts.canceled} | {detail}"
                )
                pb.invalidate()
                time.sleep(0.1)
        title = "批量下载已停止" if session.stopped else "批量下载完成"
        U.print_panel(title, session.summary_panel_rows())

    # ── download options ──────────────────────────────────────────

    def _ask_with_cancel(self, prompt: str, default: str = "") -> Optional[str]:
        """Ask for input; empty input uses *default*, '0' cancels (None).

        Lets a first-time user bail out of a multi-step wizard instead of
        being stuck guessing how to go back.
        """
        while True:
            raw = U.ask(prompt, default=default)
            if raw == "0":
                return None
            if raw:
                return raw
            if default:
                return default
            U.print_warning("输入不能为空（输入 0 取消）。")

    def _pick_format(self) -> Optional[str]:
        formats = list(SUPPORTED_GUI_AUDIO_FORMATS)
        labels = formats[:] + ["取消"]
        if not is_ffmpeg_available():
            U.print_warning("未安装 ffmpeg：其他格式会自动回退保存为源格式（仅 mp3 一定可用）。")
        choice = U.menu("选择下载格式", labels)
        if choice == len(labels):
            return None
        return formats[choice - 1]

    @staticmethod
    def _pick_lyric_mode() -> tuple[bool, str]:
        """Ask for a lyric mode; returns (download_lyric, lyric_mode)."""
        choice = U.menu(
            "歌词模式",
            ["不下载歌词", "原文歌词", "双语合并（原文 + 翻译）", "仅翻译歌词"],
        )
        modes = ["original", "bilingual", "translation"]
        if choice == 1:
            return False, "original"
        return True, modes[choice - 2]

    def _download_song(
        self,
        song_id: str,
        song_name: str,
        artist: Optional[str] = None,
        album_name: Optional[str] = None,
        duration_ms: Optional[int] = None,
        cover_url: Optional[str] = None,
    ) -> bool:
        out_dir_raw = self._ask_with_cancel(
            "保存目录（直接回车用默认；输入 0 取消）", default=self.session.last_download_dir
        )
        if out_dir_raw is None:
            return False
        out_dir = Path(out_dir_raw).expanduser()
        suggested = sanitize_filename(f"{song_name}-{song_id}" if song_name else f"song-{song_id}")
        rename = self._ask_with_cancel(
            "文件名（不含后缀；直接回车用默认；输入 0 取消）", default=suggested
        )
        if rename is None:
            return False
        target_format = self._pick_format()
        if target_format is None:
            return False
        download_lyric, lyric_mode = self._pick_lyric_mode()
        try:
            output_path = resolve_output_path(
                out_dir=out_dir,
                song_id=song_id,
                song_name=song_name or None,
                rename=rename,
                out_format=target_format,
            )
        except MusicFetchError as err:
            U.print_error(user_error_message(err.code, err.message))
            return False
        U.print_info(f"输出：{output_path}")
        job = DownloadJob(
            task_id=build_task_id(song_id),
            song_id=song_id,
            output_path=output_path,
            cookie=self.session.cookie,
            target_format=target_format,
            timeout=self.session.download_timeout_sec,
            retry_count=self.session.download_retry_count,
            tags={
                "title": song_name or "",
                "artist": artist,
                "album": album_name,
                "cover_url": cover_url,
            },
            download_lyric=download_lyric,
            lyric_mode=lyric_mode,
        )
        result = self._run_job(job)
        self.session.last_download_dir = str(out_dir)
        self.session_store.save(self.session)
        if result is None:
            U.print_error("下载任务异常结束。")
            return False
        if result.state == "success":
            self._add_record(
                song_id=song_id,
                song_name=song_name,
                output_path=str(result.output_path),
                size_bytes=result.file_size,
                status=TASK_STATE_SUCCESS,
            )
            U.print_panel(
                "下载完成",
                [
                    ("文件", str(result.output_path)),
                    ("大小", format_bytes(result.file_size)),
                ],
            )
            if U.confirm("打开所在文件夹？", default=False):
                self._open_path(result.output_path.parent)
            return True
        if result.state == "canceled":
            self._add_record(
                song_id=song_id,
                song_name=song_name,
                output_path=str(result.output_path),
                size_bytes=0,
                status=TASK_STATE_CANCELED,
            )
            U.print_warning("下载已取消。")
        else:
            self._add_record(
                song_id=song_id,
                song_name=song_name,
                output_path=str(result.output_path),
                size_bytes=0,
                status=TASK_STATE_FAILED,
                error_code=result.error_code,
            )
            U.print_error(f"下载失败：{user_error_message(result.error_code, result.error_message)}")
            if result.error_code == "AUTH_EXPIRED":
                self._handle_auth_expired()
        return False

    def _add_record(
        self,
        song_id: str,
        song_name: str,
        output_path: str,
        size_bytes: int,
        status: str,
        error_code: str = "",
    ) -> None:
        self.history_store.add(
            DownloadRecord(
                song_id=song_id,
                song_name=song_name or f"song-{song_id}",
                output_path=output_path,
                size_bytes=size_bytes,
                downloaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                status=status,
                error_code=error_code,
            )
        )

    # ── history ───────────────────────────────────────────────────

    def _screen_history(self) -> None:
        status_filter = "all"
        query = ""
        page = 0
        while True:
            records = self.history_store.load()
            filtered = filter_download_history(records, status_filter=status_filter, query=query)
            page_records, total_pages, page = paginate_download_history(filtered, page)
            U.print_header(MENU_HISTORY)
            if query:
                U.print_info(f"搜索：{query}")
            U.print_info(f"状态：{self._filter_label(status_filter)}")
            if not filtered:
                U.print_warning(T.MSG_DOWNLOADS_EMPTY if not records else T.MSG_DOWNLOADS_FILTER_EMPTY)
            else:
                rows = [
                    (
                        str(index),
                        record.song_name,
                        Path(record.output_path).name,
                        T.manager_status_text(record.status),
                        format_bytes(record.size_bytes) if record.size_bytes else "-",
                        record.downloaded_at,
                    )
                    for index, record in enumerate(page_records, start=1)
                ]
                U.print_table(["#", "歌曲", "文件名", "状态", "大小", "时间"], rows)
                U.print_info(
                    f"第 {page + 1 if total_pages else 0}/{total_pages} 页 · 共 {len(filtered)} 条"
                )
            record_actions = [
                f"操作第 {index} 条（{page_records[index - 1].song_name}）"
                for index in range(1, len(page_records) + 1)
            ]
            actions = record_actions + ["搜索关键词", "状态筛选", "上一页", "下一页", "导出筛选结果 CSV", "返回"]
            choice = U.menu("操作", actions)
            if choice <= len(page_records):
                self._history_record_actions(page_records[choice - 1])
            elif actions[choice - 1] == "搜索关键词":
                query = U.ask("搜索（歌曲名/ID/文件名/路径/错误码，留空清除）")
                page = 0
            elif actions[choice - 1] == "状态筛选":
                status_filter = self._pick_status_filter()
                page = 0
            elif actions[choice - 1] == "上一页" and page > 0:
                page -= 1
            elif actions[choice - 1] == "下一页" and page + 1 < total_pages:
                page += 1
            elif actions[choice - 1] == "导出筛选结果 CSV":
                self._export_history_csv(filtered)
            else:
                return

    @staticmethod
    def _filter_label(status_filter: str) -> str:
        mapping = {
            "all": T.MANAGER_FILTER_ALL,
            "success": T.MANAGER_FILTER_SUCCESS,
            "failed": T.MANAGER_FILTER_FAILED,
            "canceled": T.MANAGER_FILTER_CANCELED,
            "pending": T.MANAGER_FILTER_PENDING,
            "downloading": T.MANAGER_FILTER_DOWNLOADING,
        }
        return mapping.get(status_filter, status_filter)

    def _pick_status_filter(self) -> str:
        options = [
            T.MANAGER_FILTER_ALL,
            T.MANAGER_FILTER_SUCCESS,
            T.MANAGER_FILTER_FAILED,
            T.MANAGER_FILTER_CANCELED,
            T.MANAGER_FILTER_PENDING,
            T.MANAGER_FILTER_DOWNLOADING,
        ]
        keys = ["all", "success", "failed", "canceled", "pending", "downloading"]
        choice = U.menu("状态筛选", options)
        return keys[choice - 1]

    def _export_history_csv(self, filtered) -> None:
        if not filtered:
            U.print_warning(T.MANAGER_EXPORT_EMPTY)
            return
        default_path = Path(self.session.last_download_dir).expanduser() / (
            f"download-history-{datetime.now().strftime('%Y%m%d-%H%M%S')}.csv"
        )
        target = Path(U.ask("导出路径", default=str(default_path))).expanduser()
        if not target.suffix:
            target = target.with_suffix(".csv")
        try:
            target.write_text(build_download_history_csv(filtered), encoding="utf-8-sig")
            U.print_success(f"下载历史已导出：{target}")
        except OSError as err:
            U.print_error(f"导出失败：{err}")

    def _history_record_actions(self, record: DownloadRecord) -> None:
        U.print_header("记录操作")
        U.print_info(
            f"{record.song_name}（{record.song_id}）· {T.manager_status_text(record.status)} · {record.output_path}"
        )
        options = ["打开所在文件夹", "删除文件并移除记录"]
        if record.status == TASK_STATE_FAILED:
            options.append("重试下载")
        options.append("返回")
        choice = U.menu("操作", options)
        action = options[choice - 1]
        if action == "打开所在文件夹":
            self._open_path(Path(record.output_path).expanduser().parent)
        elif action == "删除文件并移除记录":
            path = Path(record.output_path).expanduser()
            if U.confirm(f"确定删除文件并移除记录？\n{path}", default=False):
                try:
                    if path.exists():
                        path.unlink()
                except OSError as err:
                    U.print_warning(f"删除文件失败：{err}")
                self.history_store.remove_by_path(str(path))
                U.print_success("已删除。")
        elif action == "重试下载":
            self._retry_record(record)

    def _retry_record(self, record: DownloadRecord) -> None:
        if not self.session.cookie:
            U.print_warning(T.MSG_NEED_LOGIN_ANY)
            self._login_and_return()
            if not self.session.cookie:
                return
        output_path = Path(record.output_path).expanduser()
        target_format = retry_target_format(output_path)
        job = DownloadJob(
            task_id=build_task_id(record.song_id),
            song_id=record.song_id,
            output_path=output_path,
            cookie=self.session.cookie,
            target_format=target_format,
            timeout=self.session.download_timeout_sec,
            retry_count=self.session.download_retry_count,
            tags={"title": record.song_name, "artist": None, "album": None, "cover_url": None},
        )
        result = self._run_job(job)
        self.history_store.remove_by_path(str(output_path))
        if result is None:
            return
        if result.state == "success":
            size = result.output_path.stat().st_size if result.output_path.exists() else 0
            self._add_record(
                record.song_id, record.song_name, str(result.output_path), size, TASK_STATE_SUCCESS,
            )
            U.print_success(f"重试成功：{result.output_path}")
        elif result.state == "canceled":
            self._add_record(
                record.song_id, record.song_name, str(output_path), 0, TASK_STATE_CANCELED,
            )
        else:
            self._add_record(
                record.song_id, record.song_name, str(output_path), 0, TASK_STATE_FAILED,
                error_code=result.error_code,
            )
            U.print_error(f"重试失败：{user_error_message(result.error_code, result.error_message)}")
            if result.error_code == "AUTH_EXPIRED":
                self._handle_auth_expired()

    @staticmethod
    def _open_path(path: Path) -> None:
        """Open a file or folder with the system default handler."""
        if not path.exists():
            U.print_warning(f"路径不存在：{path}")
            return
        try:
            if sys.platform == "win32":
                os.startfile(str(path))
            elif sys.platform == "darwin":
                subprocess.run(["open", str(path)], check=False)
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except OSError as err:
            U.print_warning(f"打开失败：{err}")

    # ── settings ──────────────────────────────────────────────────

    def _screen_settings(self) -> None:
        while True:
            U.print_header(MENU_SETTINGS)
            proxy_type_label = self.session.proxy_type or "直连"
            theme_label = "浅色" if self.session.ui_theme == "light" else "深色"
            options = [
                f"下载目录：{self.session.last_download_dir}",
                f"检测超时：{self.session.detect_timeout_sec}s",
                f"下载超时：{self.session.download_timeout_sec}s",
                f"下载重试次数：{self.session.download_retry_count}",
                f"并发上限：{self.session.download_concurrency}",
                f"代理：{proxy_type_label}",
                f"界面主题：{theme_label}",
                "保存设置",
                "返回（不保存）",
            ]
            choice = U.menu("设置项", options)
            if choice == 1:
                value = U.ask_required("下载目录", default=self.session.last_download_dir)
                self.session.last_download_dir = value
            elif choice == 2:
                self.session.detect_timeout_sec = U.ask_int("检测超时（秒）", self.session.detect_timeout_sec, 1, 5)
            elif choice == 3:
                self.session.download_timeout_sec = U.ask_int("下载超时（秒）", self.session.download_timeout_sec, 3, 10)
            elif choice == 4:
                self.session.download_retry_count = U.ask_int("下载重试次数", self.session.download_retry_count, 0, 5)
            elif choice == 5:
                self.session.download_concurrency = U.ask_int("并发上限", self.session.download_concurrency, MIN_DOWNLOAD_CONCURRENCY, MAX_CLI_CONCURRENCY)
            elif choice == 6:
                self._edit_proxy()
            elif choice == 7:
                theme_choice = U.menu("界面主题", ["深色", "浅色", "返回"])
                if theme_choice in (1, 2):
                    self.session.ui_theme = "dark" if theme_choice == 1 else "light"
                    U.set_theme(self.session.ui_theme)
            elif choice == 8:
                self.session_store.save(self.session)
                U.print_success("设置已保存。")
                return
            else:
                return

    def _edit_proxy(self) -> None:
        options = ["直连（跟随系统网络）", "HTTP 代理", "SOCKS5 代理", "返回"]
        choice = U.menu("代理类型", options)
        if choice == len(options):
            return
        if choice == 1:
            self.session.proxy_type = ""
            self.session.proxy_host = ""
            self.session.proxy_port = 0
            self.session.proxy_username = ""
            self.session.proxy_password = ""
        else:
            proxy_type = "http" if choice == 2 else "socks5"
            host = U.ask_required("代理主机（hostname 或 IP）")
            port = U.ask_int("代理端口", 0, 1, 65535)
            username = U.ask("用户名（可选）")
            password = U.ask("密码（可选）")
            try:
                normalize_proxy_config(proxy_type, host, port, username, password)
            except ProxyConfigError as err:
                U.print_error(f"代理配置无效：{err}")
                return
            self.session.proxy_type = proxy_type
            self.session.proxy_host = host
            self.session.proxy_port = port
            self.session.proxy_username = username
            self.session.proxy_password = password
        try:
            configure_proxy(
                self.session.proxy_type,
                self.session.proxy_host,
                self.session.proxy_port,
                self.session.proxy_username,
                self.session.proxy_password,
            )
        except ProxyConfigError as err:
            U.print_error(f"代理配置无效：{err}")
            return
        self._proxy_label = self._proxy_summary()
        U.print_success("代理已生效（保存设置后持久化）。")

    # ── diagnostics ───────────────────────────────────────────────

    def _screen_diagnostics(self) -> None:
        U.print_header(MENU_DIAGNOSTICS)
        U.print_info(f"应用版本：{APP_VERSION}")
        U.print_info(f"登录凭证：{'已配置 MUSIC_U' if self.session.cookie else '未配置 MUSIC_U'}")
        U.print_info(f"网络代理：{self._proxy_label}")
        U.print_info(f"ffmpeg：{'可用' if is_ffmpeg_available() else '不可用'}")
        U.print_info(f"日志目录：{CONFIG_DIR / 'logs'}")
        U.print_info("")
        U.print_info("运行网络检测（API / 音乐 CDN）...")
        probes = run_network_diagnostics(timeout=5)
        for probe in probes:
            status = "可达" if probe.reachable else "不可达"
            detail = f"（{probe.detail}）" if probe.detail else ""
            if probe.reachable:
                U.print_success(f"{probe.name}：{status}{detail}")
            else:
                U.print_error(f"{probe.name}：{status}{detail}")
        log_tail = read_log_tail(default_log_path(), max_lines=200)
        issues = [line for line in log_tail.splitlines() if "WARNING" in line or "ERROR" in line or "CRITICAL" in line]
        U.print_info("")
        U.print_info("最近警告与错误：")
        if issues:
            for line in issues[-10:]:
                U.print_warning(line)
        else:
            U.print_info("（无）")
        if U.confirm("导出诊断报告？", default=False):
            default_path = Path(self.session.last_download_dir).expanduser() / (
                f"diagnostics-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
            )
            target = Path(U.ask("导出路径", default=str(default_path))).expanduser()
            try:
                context = DiagnosticContext(
                    app_version=APP_VERSION,
                    log_path=default_log_path(),
                    login_configured=bool(self.session.cookie),
                    proxy_type=self.session.proxy_type,
                    proxy_host=self.session.proxy_host,
                    proxy_port=self.session.proxy_port,
                    proxy_authenticated=bool(self.session.proxy_username),
                    ffmpeg_available=is_ffmpeg_available(),
                )
                report = build_diagnostic_report(
                    context,
                    probes=probes,
                    log_tail=log_tail,
                    sensitive_values=[self.session.cookie, self.session.proxy_password],
                )
                target.write_text(report, encoding="utf-8")
                U.print_success(f"诊断报告已导出：{target}")
            except OSError as err:
                U.print_error(f"导出失败：{err}")

    # ── version check ─────────────────────────────────────────────

    def _screen_check_update(self) -> None:
        U.print_header(MENU_UPDATE)
        U.print_info(f"当前版本：v{APP_VERSION}")
        with U.spinner("检查中..."):
            try:
                latest, url = check_for_updates_cached(timeout=8)
            except RuntimeError as err:
                U.print_warning(f"无法检查更新：{err}")
                return
        if version_key(latest) > version_key(APP_VERSION):
            U.print_success(f"发现新版本：{latest}（当前 {APP_VERSION}）")
            U.print_info(f"下载地址：{url or PROJECT_GITHUB_URL}")
        else:
            U.print_success(f"当前已是最新版本（v{APP_VERSION}）。")


def main() -> int:
    setup_logging(default_log_path(), level=logging.INFO)
    logger.info("TUI started. version=%s", APP_VERSION)
    app = TuiApp()
    try:
        return app.run()
    except KeyboardInterrupt:
        print()
        U.print_info("再见！")
        return 0
    except EOFError:
        return 0


__all__ = ["TuiApp", "main"]
