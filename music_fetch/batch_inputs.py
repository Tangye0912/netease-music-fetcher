#!/usr/bin/env python3
"""Helpers for batch input parsing and de-duplication."""

from __future__ import annotations

import re

from music_fetch.app_settings import TRAILING_URL_PUNCTUATION, URL_IN_TEXT_PATTERN

PLAYLIST_SHARE_PATTERN = re.compile(r"歌单《([^》]+)》")
SONG_SHARE_PATTERN = re.compile(r"分享(.+?)的单曲《([^》]+)》")
ALBUM_SHARE_PATTERN = re.compile(r"专辑《([^》]+)》")
PLAYLIST_SHARE_WITH_URL_PATTERN = re.compile(r"分享.*?歌单《([^》]+)》\s*(https?://[^\s]+)")
SONG_SHARE_WITH_URL_PATTERN = re.compile(r"分享.*?单曲《([^》]+)》\s*(https?://[^\s]+)")
ALBUM_SHARE_WITH_URL_PATTERN = re.compile(r"分享.*?专辑《([^》]+)》\s*(https?://[^\s]+)")


def split_batch_input(raw_text: str) -> list[str]:
    """Split a mixed batch text into candidate input entries."""
    entries: list[str] = []
    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        urls = _extract_urls(stripped)
        if urls:
            entries.extend(urls)
            continue
        entries.extend(_split_plain_segments(stripped))
    return entries


def collect_batch_candidates(raw_text: str) -> list[str]:
    """Parse and de-duplicate batch candidates from raw text."""
    return dedupe_preserve_order(split_batch_input(raw_text))


def should_use_batch_mode(raw_text: str, min_count: int = 3) -> bool:
    """Whether current input should route to batch flow."""
    return len(collect_batch_candidates(raw_text)) >= max(1, int(min_count))


def looks_like_playlist_candidate(value: str) -> bool:
    lowered = value.strip().lower()
    return "/playlist" in lowered or "#/playlist" in lowered


def contains_playlist_hint(items: list[str]) -> bool:
    return any(looks_like_playlist_candidate(item) for item in items)


def source_hint_map(raw_text: str) -> dict[str, str]:
    """Build candidate -> source hint label map from share-copy text."""
    mapping: dict[str, str] = {}
    # Prefer precise share-snippet parsing so mixed share text in one line maps correctly.
    matched_urls: set[str] = set()
    ordered_hints: list[tuple[int, str, str]] = []
    for match in PLAYLIST_SHARE_WITH_URL_PATTERN.finditer(raw_text):
        title = match.group(1).strip()
        url = _normalize_url(match.group(2))
        if title and url:
            ordered_hints.append((match.start(), url, f"歌单-{title}"))
    for match in SONG_SHARE_WITH_URL_PATTERN.finditer(raw_text):
        title = match.group(1).strip()
        url = _normalize_url(match.group(2))
        if title and url:
            ordered_hints.append((match.start(), url, f"歌曲-{title}"))
    for match in ALBUM_SHARE_WITH_URL_PATTERN.finditer(raw_text):
        title = match.group(1).strip()
        url = _normalize_url(match.group(2))
        if title and url:
            ordered_hints.append((match.start(), url, f"专辑-{title}"))
    for _pos, url, hint in sorted(ordered_hints, key=lambda item: item[0]):
        mapping.setdefault(url, hint)
        matched_urls.add(url)

    for line in raw_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        hint = _parse_share_hint(stripped)
        if not hint:
            continue
        urls = _extract_urls(stripped)
        if urls:
            for url in urls:
                if url in matched_urls:
                    continue
                mapping.setdefault(url, hint)
            continue
        for part in _split_plain_segments(stripped):
            mapping.setdefault(part, hint)
    return mapping


def dedupe_preserve_order(items: list[str]) -> list[str]:
    """De-duplicate items while keeping first-seen order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _extract_urls(text: str) -> list[str]:
    results: list[str] = []
    for matched in URL_IN_TEXT_PATTERN.findall(text):
        cleaned = matched.rstrip(TRAILING_URL_PUNCTUATION).strip()
        if cleaned.startswith(("http://", "https://")):
            results.append(cleaned)
    return results


def _split_plain_segments(text: str) -> list[str]:
    segments: list[str] = []
    for chunk in re.split(r"[;；]+", text):
        cleaned = chunk.strip()
        if cleaned:
            segments.append(cleaned)
    return segments


def _parse_share_hint(text: str) -> str:
    playlist_match = PLAYLIST_SHARE_PATTERN.search(text)
    if playlist_match:
        title = playlist_match.group(1).strip()
        if title:
            return f"歌单-{title}"

    song_match = SONG_SHARE_PATTERN.search(text)
    if song_match:
        title = song_match.group(2).strip()
        if title:
            return f"歌曲-{title}"

    # Kept after the song pattern: "分享x的专辑《y》" has no "单曲" marker, so
    # the album pattern only fires for genuine album share lines.
    album_match = ALBUM_SHARE_PATTERN.search(text)
    if album_match:
        title = album_match.group(1).strip()
        if title:
            return f"专辑-{title}"
    return ""


def _normalize_url(value: str) -> str:
    cleaned = value.strip().rstrip(TRAILING_URL_PUNCTUATION)
    if cleaned.startswith(("http://", "https://")):
        return cleaned
    return ""
