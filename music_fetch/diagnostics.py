#!/usr/bin/env python3
"""Safe diagnostics helpers for logs, runtime context, and network probes."""

from __future__ import annotations

import platform
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Sequence
from urllib import error, request

from music_fetch.network import open_url

DEFAULT_PROBE_TARGETS: tuple[tuple[str, str], ...] = (
    ("网易云 API", "https://music.163.com/api/nuser/account/get"),
    ("音乐 CDN", "https://music.163.com/song/media/outer/url?id=33894312.mp3"),
)


@dataclass(frozen=True)
class EndpointProbe:
    name: str
    reachable: bool
    status_code: int = 0
    detail: str = ""


@dataclass(frozen=True)
class DiagnosticContext:
    app_version: str
    log_path: Path
    login_configured: bool
    proxy_type: str = ""
    proxy_host: str = ""
    proxy_port: int = 0
    proxy_authenticated: bool = False
    ffmpeg_available: bool = False
    latest_task_state: str = ""
    latest_error_code: str = ""
    latest_song_id: str = ""


def read_log_tail(log_path: Path, max_lines: int = 200) -> str:
    """Read a bounded UTF-8 log tail; missing or unreadable logs return empty."""
    limit = max(1, int(max_lines))
    try:
        lines = log_path.expanduser().read_text(encoding="utf-8", errors="replace").splitlines()
    except (OSError, UnicodeError):
        return ""
    return "\n".join(lines[-limit:])


def redact_diagnostic_text(text: str, sensitive_values: Iterable[str] = ()) -> str:
    """Remove credentials from diagnostic text before display or export."""
    redacted = str(text or "")
    secrets = sorted({value for value in sensitive_values if value}, key=len, reverse=True)
    for secret in secrets:
        redacted = redacted.replace(secret, "***")
    redacted = re.sub(
        r"(?i)\b(https?|socks5h?)://[^/@\s]+@",
        lambda match: f"{match.group(1)}://***@",
        redacted,
    )
    redacted = re.sub(
        r"(?i)\b(MUSIC_U|__csrf|proxy_password|password)(\s*[=:]\s*)[^;\s,]+",
        lambda match: f"{match.group(1)}{match.group(2)}***",
        redacted,
    )
    return redacted


def _safe_error_detail(err: BaseException) -> str:
    detail = " ".join(str(err).split())[:240]
    return redact_diagnostic_text(detail)


def probe_endpoint(name: str, url: str, timeout: int = 5) -> EndpointProbe:
    """Probe an endpoint through the configured application transport."""
    req = request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://music.163.com/",
            "Accept": "*/*",
            "Range": "bytes=0-0",
        },
        method="GET",
    )
    try:
        with open_url(req, timeout=timeout) as response:
            status = int(getattr(response, "status", response.getcode()) or 0)
            response.read(1)
        return EndpointProbe(name=name, reachable=True, status_code=status, detail=f"HTTP {status}")
    except error.HTTPError as err:
        probe = EndpointProbe(
            name=name,
            reachable=True,
            status_code=int(err.code),
            detail=f"HTTP {err.code}",
        )
        err.close()
        return probe
    except (error.URLError, OSError, TimeoutError, ValueError) as err:
        return EndpointProbe(name=name, reachable=False, detail=_safe_error_detail(err))


def run_network_diagnostics(timeout: int = 5) -> tuple[EndpointProbe, ...]:
    return tuple(probe_endpoint(name, url, timeout=timeout) for name, url in DEFAULT_PROBE_TARGETS)


def _proxy_summary(context: DiagnosticContext) -> str:
    if not context.proxy_type:
        return "直连（跟随系统网络）"
    proxy_type = "SOCKS5" if context.proxy_type == "socks5" else "HTTP"
    auth = "，已配置认证" if context.proxy_authenticated else ""
    return f"{proxy_type} {context.proxy_host}:{context.proxy_port}{auth}"


def _recent_log_issues(log_tail: str) -> str:
    issue_pattern = re.compile(r"\b(WARNING|ERROR|CRITICAL)\b")
    issues = [line for line in log_tail.splitlines() if issue_pattern.search(line)]
    return "\n".join(issues[-100:])


def build_diagnostic_report(
    context: DiagnosticContext,
    probes: Sequence[EndpointProbe] = (),
    log_tail: str = "",
    sensitive_values: Iterable[str] = (),
    generated_at: datetime | None = None,
) -> str:
    """Build a user-exportable report without raw cookies or proxy passwords."""
    generated = generated_at or datetime.now()
    task_state = context.latest_task_state or "无"
    task_error = context.latest_error_code or "无"
    task_song = context.latest_song_id or "无"
    lines = [
        "music-fetch 诊断报告",
        f"生成时间：{generated.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "[运行环境]",
        f"应用版本：{context.app_version}",
        f"Python：{platform.python_version()} ({sys.implementation.name})",
        f"操作系统：{platform.platform()}",
        f"日志路径：{context.log_path.expanduser()}",
        "",
        "[应用状态]",
        f"登录凭证：{'已配置 MUSIC_U' if context.login_configured else '未配置 MUSIC_U'}",
        f"网络代理：{_proxy_summary(context)}",
        f"ffmpeg：{'可用' if context.ffmpeg_available else '不可用'}",
        f"最近任务状态：{task_state}",
        f"最近错误码：{task_error}",
        f"最近歌曲 ID：{task_song}",
        "",
        "[网络检测]",
    ]
    if probes:
        for probe in probes:
            status = "可达" if probe.reachable else "不可达"
            detail = f"（{probe.detail}）" if probe.detail else ""
            lines.append(f"{probe.name}：{status}{detail}")
    else:
        lines.append("尚未运行")

    lines.extend(["", "[最近警告与错误]"])
    issues = _recent_log_issues(log_tail)
    lines.append(issues or "无")
    report = "\n".join(lines).rstrip() + "\n"
    return redact_diagnostic_text(report, sensitive_values)


__all__ = [
    "DEFAULT_PROBE_TARGETS",
    "DiagnosticContext",
    "EndpointProbe",
    "build_diagnostic_report",
    "probe_endpoint",
    "read_log_tail",
    "redact_diagnostic_text",
    "run_network_diagnostics",
]
