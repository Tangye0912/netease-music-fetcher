#!/usr/bin/env python3
"""
Version check helper — GitHub API polling for latest release/tag.

Split out of the application entry point to keep it small.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Optional
from urllib import error, request

from music_fetch.app_settings import CONFIG_DIR, PROJECT_GITHUB_URL, PROJECT_RELEASE_API, PROJECT_TAGS_API
from music_fetch.network import open_url



__all__ = [
    "version_key",
    "is_newer_version",
    "fetch_latest_project_version",
    "check_for_updates_cached",
]

UPDATE_CHECK_CACHE_FILE = CONFIG_DIR / "update_check.json"
UPDATE_CHECK_TTL_SEC = 24 * 3600


def version_key(version: Optional[str]) -> tuple[int, ...]:
    parts = [int(part) for part in re.findall(r"\d+", version or "")]
    return tuple(parts) if parts else (0,)


def is_newer_version(candidate: Optional[str], current: Optional[str]) -> bool:
    """True when *candidate* is a newer version than *current*.

    Keys are zero-padded to a common width so "3.6" and "3.6.0" compare equal
    instead of "3.6" looking older than "3.6.0".
    """
    left = version_key(candidate)
    right = version_key(current)
    width = max(len(left), len(right))
    return left + (0,) * (width - len(left)) > right + (0,) * (width - len(right))


def _github_headers() -> dict[str, str]:
    """GitHub API headers, optionally authenticated for private repositories."""
    headers = {"User-Agent": "music-fetch", "Accept": "application/vnd.github+json"}
    token = (os.environ.get("MUSIC_FETCH_GITHUB_TOKEN") or os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def fetch_latest_project_version(timeout: int = 6) -> tuple[str, str]:
    headers = _github_headers()
    endpoints = ((PROJECT_RELEASE_API, "release"), (PROJECT_TAGS_API, "tag"))
    saw_auth_error = False
    saw_rate_limit = False
    saw_network_error = False
    for endpoint, mode in endpoints:
        req = request.Request(endpoint, headers=headers, method="GET")
        try:
            with open_url(req, timeout=timeout) as resp:
                body_bytes = resp.read()
        except error.HTTPError as err:
            remaining = ""
            try:
                err_headers = getattr(err, "headers", None)
                remaining = str(err_headers.get("X-RateLimit-Remaining") or "") if err_headers else ""
            except Exception:
                remaining = ""
            if err.code == 403 and remaining == "0":
                saw_rate_limit = True
            elif err.code in (401, 403, 404):
                saw_auth_error = True
            continue
        except (error.URLError, OSError):
            saw_network_error = True
            continue
        try:
            body_raw = body_bytes.decode("utf-8")
        except UnicodeDecodeError:
            # A non-UTF-8 error page is not a usable API answer.
            saw_network_error = True
            continue
        try:
            payload = json.loads(body_raw or "{}")
        except json.JSONDecodeError:
            continue
        if mode == "release" and isinstance(payload, dict):
            tag_name = str(payload.get("tag_name") or "").strip()
            html_url = str(payload.get("html_url") or PROJECT_GITHUB_URL).strip() or PROJECT_GITHUB_URL
            if tag_name:
                return tag_name, html_url
            continue
        if mode == "tag" and isinstance(payload, list) and payload:
            first = payload[0] if isinstance(payload[0], dict) else {}
            tag_name = str(first.get("name") or "").strip()
            if tag_name:
                return tag_name, PROJECT_GITHUB_URL
    if saw_rate_limit:
        raise RuntimeError(
            "GitHub API 请求频率已达上限（匿名 60 次/小时），请稍后再试；"
            "配置 MUSIC_FETCH_GITHUB_TOKEN 环境变量可将上限提高到 5000 次/小时。"
        )
    if saw_auth_error:
        if "Authorization" in headers:
            raise RuntimeError("GitHub 仓库不可访问：请确认 GITHUB_TOKEN 有效且对该仓库有权限。")
        raise RuntimeError(
            "GitHub 仓库不可访问（私有仓库匿名访问会返回 404）。"
            "可设置 MUSIC_FETCH_GITHUB_TOKEN 环境变量后重试。"
        )
    if saw_network_error:
        raise RuntimeError("网络不可用，无法访问 GitHub，请稍后再试。")
    raise RuntimeError("GitHub API 无有效响应。")


def _read_update_cache(cache_file: Path) -> dict[str, object]:
    try:
        raw = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _write_update_cache(cache_file: Path, payload: dict[str, object]) -> None:
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass  # The cache is best-effort; a failed write just means re-checking next time.


def check_for_updates_cached(
    timeout: int = 8,
    ttl_seconds: int = UPDATE_CHECK_TTL_SEC,
    cache_file: Optional[Path] = None,
) -> tuple[str, str]:
    """Fetch the latest version, replaying a cached outcome within the TTL.

    The anonymous GitHub API allows only 60 requests/hour per IP, so the TUI
    caches the last check (success or error) for a day instead of hammering
    the endpoint on every menu visit.  Raises RuntimeError exactly like
    fetch_latest_project_version.
    """
    cache_path = cache_file if cache_file is not None else UPDATE_CHECK_CACHE_FILE
    cache = _read_update_cache(cache_path)
    now = time.time()
    checked_at_raw = cache.get("checked_at")
    checked_at = float(checked_at_raw) if isinstance(checked_at_raw, (int, float)) else 0.0
    if cache and (now - checked_at) < ttl_seconds:
        error_message = str(cache.get("error") or "").strip()
        if error_message:
            raise RuntimeError(error_message)
        latest = str(cache.get("latest") or "").strip()
        if latest:
            return latest, str(cache.get("url") or PROJECT_GITHUB_URL).strip() or PROJECT_GITHUB_URL
    try:
        result = fetch_latest_project_version(timeout=timeout)
    except RuntimeError as err:
        _write_update_cache(cache_path, {"checked_at": now, "error": str(err)})
        raise
    _write_update_cache(cache_path, {"checked_at": now, "latest": result[0], "url": result[1]})
    return result

