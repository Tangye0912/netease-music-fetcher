"""Opt-in checks against the real NetEase API.

Three assumptions drive real code and cannot be verified offline; this module pins
them so a live run answers them in one command:

    MUSIC_FETCH_LIVE_COOKIE="MUSIC_U=..." python -m pytest tests/test_live_api.py -v

Every ordinary test still blocks real connections (see ``conftest.py``); only this
module may bypass the guard, and only when that variable is set.  When a check
fails, the ROADMAP entry referenced in its docstring says what to change.
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
from urllib import parse, request

import pytest

from music_fetch.api import (
    PLAYABLE_REQUEST_PROFILES,
    PLAYER_URL_API,
    PLAYLIST_DETAIL_API,
    SONG_DETAIL_API,
    fetch_account_profile,
    fetch_album_songs,
    fetch_lyric,
    fetch_playable_candidates,
    fetch_playlist_song_ids,
    fetch_song_metadata,
    fetch_songs_metadata,
    perform_json_get,
    perform_json_post,
    search_songs,
)
from music_fetch.network import open_url
from music_fetch.app_settings import APP_VERSION
from music_fetch.version_check import check_for_updates_cached

COOKIE = (os.environ.get("MUSIC_FETCH_LIVE_COOKIE") or "").strip()

pytestmark = pytest.mark.skipif(
    not COOKIE,
    reason="set MUSIC_FETCH_LIVE_COOKIE to run the live checks (they call the real API)",
)

_PAGE_SIZE = 1000


def _headers(cookie: str = COOKIE) -> dict[str, str]:
    return {"User-Agent": "music-fetch", "Referer": "https://music.163.com/", "Cookie": cookie}


def _liked_song_ids() -> list[str]:
    """The account's liked songs, via the assumption under test."""
    profile = fetch_account_profile(COOKIE, timeout=20)
    if profile.user_id is None:
        pytest.fail("账号接口没有返回 user_id——我喜欢的音乐无法定位（见 ROADMAP 真机确认项）")
    return fetch_playlist_song_ids(str(profile.user_id), COOKIE, timeout=30)


class LikedSongsTests(unittest.TestCase):
    def test_liked_songs_are_reachable_under_the_account_id(self):
        """ROADMAP: 「我喜欢的音乐」直达。

        The TUI opens ``playlist?id=<uid>``; if this fails, the liked playlist is
        not addressed by the account id and ``_screen_liked`` needs another route.
        """
        song_ids = _liked_song_ids()
        print(f"\n我喜欢的音乐：{len(song_ids)} 首（账号 ID 作为歌单 ID 可用）")
        self.assertTrue(song_ids, "playlist?id=<uid> 没有返回任何歌曲")

    def test_paging_advances_when_the_playlist_exceeds_one_request(self):
        """ROADMAP: 超过 1000 首是否会被静默截断。

        ``fetch_playlist_song_ids`` asks for 1000 ids per request and advances by
        offset; if the endpoint ignores the offset the flow would silently stop at
        1000.  The playlist's own trackCount tells us whether that matters.
        """
        profile = fetch_account_profile(COOKIE, timeout=20)
        headers = {"User-Agent": "music-fetch", "Referer": "https://music.163.com/", "Cookie": COOKIE}

        def page(offset: int) -> tuple[int, list[int]]:
            query = parse.urlencode({"id": str(profile.user_id), "n": str(_PAGE_SIZE), "s": str(offset)})
            status, body = perform_json_get(f"{PLAYLIST_DETAIL_API}?{query}", headers, timeout=30)
            playlist = (body or {}).get("playlist") or {}
            rows = playlist.get("trackIds") or []
            return int(playlist.get("trackCount") or 0), [
                int(row["id"]) for row in rows if isinstance(row, dict) and isinstance(row.get("id"), int)
            ]

        status_is_stale = None  # placeholder to keep ruff quiet about unused imports
        del status_is_stale
        track_count, first_page = page(0)
        print(f"\n喜欢列表 trackCount={track_count}，首页返回 {len(first_page)} 个 id")
        if track_count <= _PAGE_SIZE:
            self.skipTest(f"只有 {track_count} 首，无法验证分页推进（>1000 首时才需要）")

        _, second_page = page(_PAGE_SIZE)
        overlap = set(first_page) & set(second_page)
        print(f"第二页返回 {len(second_page)} 个 id，与首页重叠 {len(overlap)} 个")
        self.assertTrue(second_page, "第二页没有任何 id：分页偏移被忽略，喜欢列表会被截断在 1000 首")
        self.assertFalse(overlap, "第二页与首页内容相同：分页偏移被忽略，喜欢列表会被截断在 1000 首")


class MetadataShapeTests(unittest.TestCase):
    def test_every_field_is_filled_for_public_songs(self):
        """Guards the bug found 2026-10-10: the legacy detail endpoint answers with
        duration/album/artists and no cover URL, so a parser that only knows
        dt/al/ar silently lost artist, album, duration and every cover art.
        """
        results = search_songs("周杰伦", COOKIE, limit=3)
        if not results:
            self.skipTest("搜索没有返回结果，无法取样")
        ids = [song.song_id for song in results]

        for song_id in ids:
            name, duration, cover, artist, album = fetch_song_metadata(song_id, COOKIE, timeout=15)
            with self.subTest(song_id=song_id, path="single"):
                self.assertTrue(name, "歌名为空")
                self.assertTrue(artist, "艺人为空")
                self.assertTrue(album, "专辑为空")
                self.assertTrue(duration, "时长为空")
                self.assertTrue(cover, "封面 URL 为空")

        batch = fetch_songs_metadata(ids, COOKIE, timeout=20)
        for song_id in ids:
            metadata = batch.get(song_id)
            with self.subTest(song_id=song_id, path="batch"):
                self.assertIsNotNone(metadata, "批量路径没有返回这首歌")
                self.assertTrue(metadata.artist and metadata.album_name and metadata.duration_ms and metadata.cover_url)


class LyricsAndAssetTests(unittest.TestCase):
    def test_lyrics_are_parsed(self):
        song_id = search_songs("周杰伦", COOKIE, limit=1)[0].song_id
        lyric = fetch_lyric(song_id, timeout=15)
        self.assertTrue(lyric.lyric, "歌词为空——接口形状可能又变了")
        self.assertIn("[", lyric.lyric, "歌词看起来不是 LRC（缺时间轴方括号）")

    def test_cover_url_really_downloads_as_an_image(self):
        """Cover art was silently dead until 2026-10-10; check the URL end to end."""
        song_id = search_songs("周杰伦", COOKIE, limit=1)[0].song_id
        _name, _duration, cover_url, _artist, _album = fetch_song_metadata(song_id, COOKIE, timeout=15)
        self.assertTrue(cover_url, "封面 URL 为空")

        with open_url(request.Request(cover_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15) as resp:
            head = resp.read(8)
        is_jpeg = head[:3] == b"\xff\xd8\xff"
        is_png = head[:8] == b"\x89PNG\r\n\x1a\n"
        self.assertTrue(is_jpeg or is_png, f"封面不是 JPEG/PNG：{head.hex()}")

    def test_album_link_expands_into_tracks(self):
        """Guards the second 2026-10-10 bug: album.songs comes back empty and the
        tracks live in the top-level songs list, so every album used to report
        "Album is empty or unavailable"."""
        song_id = search_songs("周杰伦", COOKIE, limit=1)[0].song_id
        include = parse.urlencode({"c": json.dumps([{"id": int(song_id)}], separators=(",", ":"))})
        _status, body = perform_json_get(f"{SONG_DETAIL_API}?{include}", _headers(), timeout=15)
        album = ((body.get("songs") or [{}])[0].get("al") or {})
        self.assertIsNotNone(album.get("id"), "没有从歌曲详情里拿到专辑 ID")

        detail = fetch_album_songs(str(album["id"]), COOKIE, timeout=20)
        self.assertTrue(detail.name, "专辑名为空")
        self.assertTrue(detail.song_ids, "专辑展开没有取到曲目")
        print(f"\n专辑 {album['id']}：{detail.name!r} -> {len(detail.song_ids)} 首")


class UpdateCheckTests(unittest.TestCase):
    def test_the_update_check_reaches_github(self):
        """The TUI's 检查更新 path has only ever run against mocks."""
        cache = pathlib.Path(tempfile.gettempdir()) / "music-fetch-update-check-live.json"
        self.addCleanup(lambda: cache.unlink(missing_ok=True))
        try:
            latest, url = check_for_updates_cached(timeout=10, cache_file=cache)
        except RuntimeError as err:
            # The anonymous GitHub API allows 60 requests/hour; our code turns that
            # into a friendly message, which this skip also verifies.
            if "频率" in str(err):
                self.skipTest(f"GitHub 匿名限流（代码给出了友好提示）：{err}")
            raise
        print(f"\n检查更新：GitHub 报告最新 {latest}（当前 v{APP_VERSION}）")
        self.assertTrue(latest.lower().startswith("v"), f"版本号不像 tag：{latest!r}")
        self.assertTrue(url.startswith("https://"), f"发布页地址异常：{url!r}")


class PlayableResponseTests(unittest.TestCase):
    def test_playable_candidates_and_reported_size(self):
        """ROADMAP: 鉴权下播放地址接口是否返回 size。

        A reported size lets detection skip one CDN HEAD per song; nothing breaks
        when it is absent (the probe is the fallback), so this only *reports* the
        observation instead of failing on it.
        """
        song_ids = _liked_song_ids()
        if not song_ids:
            self.skipTest("喜欢列表为空，无法取样")

        for song_id in song_ids[:3]:
            candidates = fetch_playable_candidates(song_id, COOKIE, timeout=20)
            self.assertTrue(candidates, f"song {song_id} 没有候选地址")
            sizes = [candidate.size_bytes for candidate in candidates]
            print(f"song {song_id}: 候选 {len(candidates)} 个，size={sizes}，level={[c.level for c in candidates]}")
        print("（size 全为 0 时批量识别会回退到 HEAD 探测：不会变慢，但省不掉那次请求）")

    def test_quality_profile_ladder(self):
        """ROADMAP: 音质档案循环能否提前退出。

        Prints which levels the seven request profiles actually return, so the
        "stop once hires is found" idea can be checked against real behaviour
        before it is implemented.
        """
        song_ids = _liked_song_ids()
        if not song_ids:
            self.skipTest("喜欢列表为空，无法取样")
        song_id = song_ids[0]

        headers = {"User-Agent": "music-fetch", "Referer": "https://music.163.com/", "Cookie": COOKIE}
        observed: list[tuple[str, str, str]] = []
        for level, encode_type in PLAYABLE_REQUEST_PROFILES:
            payload = {"ids": f"[{song_id}]", "level": level, "encodeType": encode_type, "csrf_token": ""}
            status, body = perform_json_post(PLAYER_URL_API, payload, headers, timeout=20)
            data = (body or {}).get("data")
            first = data[0] if isinstance(data, list) and data else {}
            observed.append((level, encode_type, str(first.get("level") or "-")))
        print(f"\nsong {song_id} 的档案回包：{observed}")
        print("（若低档案也返回最高 level，说明可以按 level 提前退出；否则维持现状）")
        self.assertTrue(any(entry[2] != "-" for entry in observed), "所有档案都没有返回可播放地址")


if __name__ == "__main__":
    unittest.main()
