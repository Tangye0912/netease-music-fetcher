#!/usr/bin/env python3
"""
Version check helper — GitHub API polling for latest release/tag.

Extracted from main.py to reduce module size.
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional
from urllib import error, request

from music_fetch.app_settings import PROJECT_GITHUB_URL, PROJECT_RELEASE_API, PROJECT_TAGS_API
from music_fetch.network import open_url



__all__ = ['version_key', 'fetch_latest_project_version', 'fetch_release_download_url']


def version_key(version: Optional[str]) -> tuple[int, ...]:
    parts = [int(part) for part in re.findall(r"\d+", version or "")]
    return tuple(parts) if parts else (0,)


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
                body_raw = resp.read().decode("utf-8")
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


def fetch_release_download_url(timeout: int = 10) -> Optional[str]:
    """Fetch the download URL for the latest release asset (exe/dmg/zip)."""
    headers = _github_headers()
    req = request.Request(PROJECT_RELEASE_API, headers=headers, method="GET")
    try:
        with open_url(req, timeout=timeout) as resp:
            body_raw = resp.read().decode("utf-8")
    except (error.URLError, error.HTTPError, OSError):
        return None
    try:
        payload = json.loads(body_raw or "{}")
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    assets = payload.get("assets") or []
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = str(asset.get("name") or "").lower()
        if name.endswith(".exe") or name.endswith(".dmg") or name.endswith(".zip"):
            url = str(asset.get("browser_download_url") or "").strip()
            if url:
                return url
    return None

