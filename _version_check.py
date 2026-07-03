#!/usr/bin/env python3
"""
Version check helper — GitHub API polling for latest release/tag.

Extracted from main.py to reduce module size.
"""

from __future__ import annotations

import json
import re
from urllib import error, request

from app_settings import PROJECT_GITHUB_URL, PROJECT_RELEASE_API, PROJECT_TAGS_API



__all__ = ['version_key', 'fetch_latest_project_version']
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


