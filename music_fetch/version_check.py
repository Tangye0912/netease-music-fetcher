#!/usr/bin/env python3
"""
Version check helper — GitHub API polling for latest release/tag.

Extracted from main.py to reduce module size.
"""

from __future__ import annotations

import json
import re
from typing import Optional
from urllib import error, request

from music_fetch.app_settings import PROJECT_GITHUB_URL, PROJECT_RELEASE_API, PROJECT_TAGS_API



__all__ = ['version_key', 'fetch_latest_project_version', 'fetch_release_download_url']


def version_key(version: str) -> tuple[int, ...]:
    parts = [int(part) for part in re.findall(r"\d+", version or "")]
    return tuple(parts) if parts else (0,)


def fetch_latest_project_version(timeout: int = 6) -> tuple[str, str]:
    headers = {"User-Agent": "music-fetch-gui", "Accept": "application/vnd.github+json"}
    endpoints = ((PROJECT_RELEASE_API, "release"), (PROJECT_TAGS_API, "tag"))
    for endpoint, mode in endpoints:
        req = request.Request(endpoint, headers=headers, method="GET")
        try:
            with request.urlopen(req, timeout=timeout) as resp:
                body_raw = resp.read().decode("utf-8")
        except (error.URLError, error.HTTPError, OSError):
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
    raise RuntimeError("GitHub API unavailable")


def fetch_release_download_url(timeout: int = 10) -> Optional[str]:
    """Fetch the download URL for the latest release asset (exe/dmg/zip)."""
    headers = {"User-Agent": "music-fetch-gui", "Accept": "application/vnd.github+json"}
    req = request.Request(PROJECT_RELEASE_API, headers=headers, method="GET")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
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


