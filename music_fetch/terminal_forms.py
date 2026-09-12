"""Full-screen form bodies. Editing never mutates the saved application session."""
from __future__ import annotations

from dataclasses import replace
from typing import Callable

from prompt_toolkit.completion import PathCompleter
from prompt_toolkit.layout import HSplit
from prompt_toolkit.layout.containers import AnyContainer
from prompt_toolkit.widgets import Button, Dialog, Label, TextArea

from music_fetch.app_settings import (
    MAX_DETECT_TIMEOUT_SEC, MAX_DOWNLOAD_CONCURRENCY, MAX_DOWNLOAD_RETRY_COUNT,
    MAX_DOWNLOAD_TIMEOUT_SEC, MIN_DETECT_TIMEOUT_SEC, MIN_DOWNLOAD_TIMEOUT_SEC,
    SUPPORTED_AUDIO_FORMATS,
)
from music_fetch.app_stores import AppSession
from music_fetch.download_queue import DownloadOptions
from music_fetch.network import normalize_proxy_config

LYRIC_CHOICES = [("none", "不下载歌词"), ("original", "原文"), ("bilingual", "双语合并"), ("translation", "仅翻译")]


class CycleField:
    def __init__(self, label: str, choices: list[tuple[str, str]], value: str) -> None:
        self.label = label
        self.choices = choices
        self.index = next((i for i, (key, _) in enumerate(choices) if key == value), 0)
        self.button = Button(self.text, handler=self.cycle, width=36)

    @property
    def value(self) -> str:
        return self.choices[self.index][0]

    @property
    def text(self) -> str:
        return f"{self.label}：{self.choices[self.index][1]} ↻"

    def cycle(self) -> None:
        self.index = (self.index + 1) % len(self.choices)
        self.button.text = self.text


def field(label: str, value: str, *, password: bool = False, directory: bool = False) -> tuple[AnyContainer, TextArea]:
    control = TextArea(text=value, multiline=False, password=password,
                       completer=PathCompleter(only_directories=True, expanduser=True) if directory else None)
    return HSplit([Label(label), control]), control


class DownloadForm:
    def __init__(self, options: DownloadOptions, count: int, save: Callable[[DownloadOptions], None],
                 cancel: Callable[[], None], ffmpeg: bool) -> None:
        directory, self.directory = field("保存目录", options.out_dir, directory=True)
        filename, self.filename = field("文件名（不含后缀）", options.rename)
        self.format = CycleField("格式", [(fmt, fmt.upper()) for fmt in SUPPORTED_AUDIO_FORMATS], options.target_format)
        self.lyric = CycleField("歌词", LYRIC_CHOICES, options.lyric_mode)
        self.error = Label("")
        self.count = count

        def submit() -> None:
            try:
                value = DownloadOptions(self.directory.text, self.format.value, self.lyric.value,
                                        self.filename.text if count == 1 else "")
                save(value)
            except (OSError, ValueError) as err:
                self.error.text = f"请检查：{err}"

        self.submit = Button("加入队列", handler=submit)
        rows: list[AnyContainer] = [Label(f"共 {count} 首 · 已有文件默认跳过"), directory]
        if count == 1:
            rows.append(filename)
        rows += [self.format.button, self.lyric.button,
                 Label("缺少 ffmpeg：无法转换时保存源格式。" if not ffmpeg else "格式转换可用。"), self.error]
        self.dialog = Dialog(title="下载选项", body=HSplit(rows, padding=0),
                             buttons=[self.submit, Button("返回", handler=cancel)], with_background=False)


class SettingsForm:
    def __init__(self, session: AppSession, save: Callable[[AppSession], None], cancel: Callable[[], None],
                 section: str = "general") -> None:
        self.draft = replace(session)
        self.section = section
        self.controls: dict[str, TextArea] = {}
        rows: list[AnyContainer] = []
        definitions = {
            "general": [("last_download_dir", "默认目录", True, False)],
            "network": [("proxy_host", "代理主机", False, False), ("proxy_port", "代理端口", False, False),
                        ("proxy_username", "用户名", False, False), ("proxy_password", "密码（隐藏输入）", False, True)],
            "performance": [("detect_timeout_sec", f"识别超时 {MIN_DETECT_TIMEOUT_SEC}–{MAX_DETECT_TIMEOUT_SEC} 秒", False, False),
                            ("download_timeout_sec", f"下载超时 {MIN_DOWNLOAD_TIMEOUT_SEC}–{MAX_DOWNLOAD_TIMEOUT_SEC} 秒", False, False),
                            ("download_retry_count", f"重试次数 0–{MAX_DOWNLOAD_RETRY_COUNT}", False, False),
                            ("download_concurrency", f"并发上限 1–{MAX_DOWNLOAD_CONCURRENCY}", False, False)],
        }
        for name, label, directory, password in definitions[section]:
            row, control = field(label, str(getattr(session, name)), password=password, directory=directory)
            self.controls[name] = control
            rows.append(row)
        self.format = CycleField("默认格式", [(fmt, fmt.upper()) for fmt in SUPPORTED_AUDIO_FORMATS], session.default_target_format)
        self.lyric = CycleField("默认歌词", LYRIC_CHOICES, session.default_lyric_mode)
        self.theme = CycleField("主题", [("dark", "深色"), ("light", "浅色")], session.ui_theme)
        self.proxy = CycleField("连接", [("", "系统网络"), ("http", "HTTP 代理"), ("socks5", "SOCKS5 代理")], session.proxy_type)
        if section == "general":
            rows += [self.format.button, self.lyric.button, self.theme.button]
        if section == "network":
            rows.insert(0, self.proxy.button)
        self.error = Label("")
        rows.append(self.error)

        def submit() -> None:
            try:
                draft = replace(self.draft)
                for name, control in self.controls.items():
                    setattr(draft, name, int(control.text) if isinstance(getattr(draft, name), int) else control.text)
                if section == "general":
                    options = DownloadOptions(draft.last_download_dir, self.format.value, self.lyric.value)
                    draft.last_download_dir = options.out_dir
                    draft.default_target_format = options.target_format
                    draft.default_lyric_mode = options.lyric_mode
                    draft.ui_theme = self.theme.value
                if section == "network":
                    draft.proxy_type = self.proxy.value
                    config = normalize_proxy_config(draft.proxy_type, draft.proxy_host, draft.proxy_port,
                                                    draft.proxy_username, draft.proxy_password)
                    draft.proxy_host, draft.proxy_port = config.host, config.port
                    draft.proxy_username, draft.proxy_password = config.username, config.password
                if section == "performance":
                    bounds = [(draft.detect_timeout_sec, MIN_DETECT_TIMEOUT_SEC, MAX_DETECT_TIMEOUT_SEC),
                              (draft.download_timeout_sec, MIN_DOWNLOAD_TIMEOUT_SEC, MAX_DOWNLOAD_TIMEOUT_SEC),
                              (draft.download_retry_count, 0, MAX_DOWNLOAD_RETRY_COUNT),
                              (draft.download_concurrency, 1, MAX_DOWNLOAD_CONCURRENCY)]
                    if any(not lo <= value <= hi for value, lo, hi in bounds):
                        raise ValueError("参数超出提示范围。")
                save(draft)
            except (ValueError, OSError) as err:
                self.error.text = f"保存失败：{err}"

        self.submit = Button("保存", handler=submit)
        self.dialog = Dialog(title={"general": "下载与外观", "network": "代理设置", "performance": "下载性能"}[section],
                             body=HSplit(rows), buttons=[self.submit, Button("返回（不保存）", handler=cancel)],
                             with_background=False)
