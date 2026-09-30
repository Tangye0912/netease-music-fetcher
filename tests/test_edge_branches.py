"""Edge-branch tests for error paths the main per-module suites never reach.

Each class covers one module; the tests are deliberately narrow (one branch each)
and exist because these lines were uncovered, not as a substitute for the
per-module behaviour tests.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib import parse

from music_fetch.api import (
    ErrorCode,
    MusicFetchError,
    _extract_resource_id,
    fetch_album_songs,
    fetch_lyric,
    fetch_playable_candidates,
    fetch_song_metadata,
    fetch_user_playlists,
    search_songs,
)
from music_fetch.app_settings import DEFAULT_DOWNLOAD_DIR, MAX_DOWNLOAD_HISTORY_RECORDS
from music_fetch.app_stores import DownloadHistoryStore, SessionStore, _quarantine_file
from music_fetch.batch_inspect import run_batch_detect
from music_fetch.batch_inputs import _normalize_url, source_hint_map
from music_fetch.download_queue import (
    DownloadProgressSnapshot,
    DownloadQueue,
    DownloadRequest,
    _request_from_dict,
)
from music_fetch import network as net
from music_fetch import tui_utils


class StoreEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def test_history_rows_that_are_not_objects_are_skipped(self):
        path = self.base / "history.json"
        path.write_text(json.dumps(["junk", 7, {"song_id": "1", "song_name": "A"}]), encoding="utf-8")
        records = DownloadHistoryStore(path).load()
        self.assertEqual([record.song_id for record in records], ["1"])

    def test_history_is_capped_at_the_maximum(self):
        path = self.base / "history.json"
        rows = [{"song_id": str(index), "song_name": "A"} for index in range(MAX_DOWNLOAD_HISTORY_RECORDS + 5)]
        path.write_text(json.dumps(rows), encoding="utf-8")
        self.assertEqual(len(DownloadHistoryStore(path).load()), MAX_DOWNLOAD_HISTORY_RECORDS)

    def test_unparseable_session_falls_back_to_defaults(self):
        path = self.base / "session.json"
        path.write_text("{not json", encoding="utf-8")
        session = SessionStore(path).load()
        self.assertEqual(session.cookie, "")
        self.assertEqual(session.last_download_dir, DEFAULT_DOWNLOAD_DIR)

    def test_quarantine_failure_is_logged_not_raised(self):
        path = self.base / "history.json"
        path.write_text("[]", encoding="utf-8")
        with mock.patch.object(Path, "replace", side_effect=OSError("read-only")), mock.patch(
            "music_fetch.app_stores.logger"
        ) as logger_mock:
            _quarantine_file(path)
        logger_mock.warning.assert_called()

    def test_temp_file_cleanup_failure_does_not_break_saving(self):
        store = SessionStore(self.base / "session.json")
        session = store.load()
        with mock.patch.object(Path, "unlink", side_effect=OSError("locked")):
            store.save(session)  # must not raise
        self.assertTrue((self.base / "session.json").exists())


class NetworkEdgeTests(unittest.TestCase):
    def test_proxy_url_is_empty_when_disabled(self):
        self.assertEqual(net.ProxyConfig().proxy_url, "")

    def test_non_integer_port_is_rejected(self):
        from music_fetch.network import ProxyConfigError, normalize_proxy_config

        with self.assertRaises(ProxyConfigError) as ctx:
            normalize_proxy_config("http", "127.0.0.1", "not-a-port")
        self.assertIn("integer", str(ctx.exception))

    def test_response_adapter_exposes_url_and_code(self):
        response = mock.Mock(url="https://cdn/song.mp3", status_code=206, headers={}, raw=mock.Mock())
        adapter = net._RequestsResponseAdapter(response, mock.Mock())
        self.assertEqual(adapter.geturl(), "https://cdn/song.mp3")
        self.assertEqual(adapter.getcode(), 206)


class BatchInputEdgeTests(unittest.TestCase):
    def test_blank_lines_are_ignored_when_mapping_hints(self):
        mapping = source_hint_map("歌单《测试》\n\nhttps://music.163.com/playlist?id=1")
        self.assertEqual(len(mapping), 1)

    def test_share_lines_without_urls_map_their_plain_segments(self):
        # A share line with no link at all: the hint is attached to the text
        # segments, so a pasted "分享…单曲《…》" still carries its label.
        mapping = source_hint_map("分享张杰的单曲《这就是爱》")
        self.assertTrue(mapping)
        self.assertTrue(all(hint.startswith("歌曲-") for hint in mapping.values()))

    def test_normalize_url_rejects_non_http_values(self):
        self.assertEqual(_normalize_url("music.163.com/song?id=1"), "")
        self.assertEqual(_normalize_url("https://music.163.com/song?id=1"), "https://music.163.com/song?id=1")


class TuiUtilsEdgeTests(unittest.TestCase):
    def test_live_ask_passes_a_redrawing_message(self):
        with mock.patch("music_fetch.tui_utils.prompt", return_value="  42  ") as prompt_mock:
            self.assertEqual(tui_utils.live_ask(lambda: "SCREEN", "prompt> "), "42")
        message = prompt_mock.call_args.args[0]
        self.assertIn("SCREEN", str(message()))
        self.assertEqual(prompt_mock.call_args.kwargs["refresh_interval"], 0.5)

    def test_input_multiline_uses_multiline_mode(self):
        with mock.patch("music_fetch.tui_utils.prompt", return_value="line1\nline2") as prompt_mock:
            self.assertEqual(tui_utils.input_multiline("粘贴内容"), "line1\nline2")
        self.assertTrue(prompt_mock.call_args.kwargs["multiline"])
        self.assertEqual(prompt_mock.call_args.kwargs["bottom_toolbar"], tui_utils._status_toolbar)

    def test_menu_truncates_an_over_long_option(self):
        option = "很长很长的歌名" * 12
        printed: list[str] = []
        with mock.patch("music_fetch.tui_utils.prompt", return_value="1"), mock.patch(
            "music_fetch.tui_utils.print_info", side_effect=lambda message: printed.append(str(message))
        ), mock.patch("music_fetch.tui_utils.print_error"):
            self.assertEqual(tui_utils.menu("选择", [option, "短"], shortcuts={"q": 2}), 1)
        rendered = "\n".join(printed)
        self.assertIn("…", rendered)        # the long option is shortened…
        self.assertNotIn(option, rendered)  # …and never printed in full
        self.assertIn("短", rendered)

    def test_escape_binding_is_installed_when_none_exist(self):
        dialog = mock.Mock()
        dialog.key_bindings = None
        tui_utils._bind_escape_to_cancel(dialog)
        self.assertIsNotNone(dialog.key_bindings)


class QueueEdgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.queue = DownloadQueue(
            history_store=DownloadHistoryStore(self.base / "history.json"),
            cookie="MUSIC_U=test",
            persist_path=self.base / "queue.json",
        )
        self.addCleanup(self.queue.close)

    def test_request_without_a_path_is_rejected(self):
        with self.assertRaises(KeyError):
            _request_from_dict({"song_id": "1", "song_name": "A"})

    def test_clearing_the_cookie_parks_pending_items(self):
        self.queue.enqueue(DownloadRequest("1", "song", self.base / "1.mp3"))
        self.queue.set_cookie("")
        self.assertEqual(self.queue.snapshot()[0].state, "waiting_login")

    def test_retrying_a_running_item_returns_it_unchanged(self):
        item = self.queue.enqueue(DownloadRequest("1", "song", self.base / "1.mp3"))
        copy = self.queue.retry(item.task_id)
        self.assertIsNone(copy.job)
        self.assertEqual(copy.task_id, item.task_id)

    def test_history_staging_is_idempotent(self):
        item = self.queue.enqueue(DownloadRequest("1", "song", self.base / "1.mp3"))
        snapshot = self.queue.item(item.task_id)
        pending: list = []
        self.queue._queue_history(snapshot, pending)
        already = self.queue.item(item.task_id)
        already.recorded = True
        self.queue._queue_history(already, pending)
        self.assertEqual(len(pending), 1)

    def test_restore_skips_malformed_entries(self):
        (self.base / "queue.json").write_text(json.dumps([
            42,
            {"no_request": True},
            {"request": {"song_id": "1"}},
            {"request": {"song_id": "2", "song_name": "OK", "output_path": str(self.base / "ok.mp3")}},
        ]), encoding="utf-8")
        fresh = DownloadQueue(
            history_store=DownloadHistoryStore(self.base / "h2.json"),
            cookie="MUSIC_U=test",
            persist_path=self.base / "queue.json",
        )
        self.addCleanup(fresh.close)
        restored, completed = fresh.restore_saved()
        self.assertEqual((restored, completed), (1, 0))
        self.assertEqual([entry.request.song_id for entry in fresh.snapshot()], ["2"])

    def test_history_write_failure_is_surfaced_on_the_queue(self):
        item = self.queue.enqueue(DownloadRequest("1", "song", self.base / "1.mp3"))
        snapshot = self.queue.item(item.task_id)
        with mock.patch.object(self.queue._history_store, "add", side_effect=OSError("disk full")):
            self.queue._record(snapshot)
        self.assertIn("下载历史保存失败", self.queue._history_error or "")


class BatchInspectEdgeTests(unittest.TestCase):
    def test_a_pre_set_cancel_event_stops_before_any_work(self):
        import threading

        cancel = threading.Event()
        cancel.set()
        with mock.patch("music_fetch.batch_inspect.detect_song") as detect_mock:
            rows = run_batch_detect(
                "https://music.163.com/song?id=100", "MUSIC_U=test", timeout=5, cancel_event=cancel,
            )
        self.assertEqual(rows, [])
        detect_mock.assert_not_called()

    def test_invalid_input_becomes_a_failed_row_during_expansion(self):
        rows = run_batch_detect("https://example.com/not-netease", "MUSIC_U=test", timeout=5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].status, "failed")
        self.assertIn("INVALID_URL", rows[0].message)

    def test_playlist_inputs_are_expanded(self):
        with mock.patch(
            "music_fetch.batch_inspect.fetch_playlist_song_ids", return_value=["100", "200"]
        ) as playlist_mock, mock.patch(
            "music_fetch.batch_inspect.detect_song", side_effect=self._detect_result
        ), mock.patch("music_fetch.batch_inspect.probe_media_size_bytes", return_value=0):
            rows = run_batch_detect(
                "https://music.163.com/playlist?id=5", "MUSIC_U=test", timeout=5, detect_concurrency=1,
            )
        playlist_mock.assert_called_once()
        self.assertEqual([row.song_id for row in rows], ["100", "200"])

    def test_album_inputs_are_expanded_without_a_name(self):
        album = mock.Mock(song_ids=["300"])
        album.name = ""  # Mock(name=…) would set the mock's own name, not this field
        with mock.patch("music_fetch.batch_inspect.fetch_album_songs", return_value=album), mock.patch(
            "music_fetch.batch_inspect.detect_song", side_effect=self._detect_result
        ), mock.patch("music_fetch.batch_inspect.probe_media_size_bytes", return_value=0):
            rows = run_batch_detect(
                "https://music.163.com/album?id=9", "MUSIC_U=test", timeout=5, detect_concurrency=1,
            )
        self.assertEqual([row.song_id for row in rows], ["300"])
        self.assertIn("9", rows[0].source_label)

    def test_song_without_a_name_uses_its_id_in_the_label(self):
        with mock.patch(
            "music_fetch.batch_inspect.detect_song",
            return_value=mock.Mock(song_id="400", song_name="", can_download=True, media_url="", unavailable_reason=""),
        ):
            rows = run_batch_detect("https://music.163.com/song?id=400", "MUSIC_U=test", timeout=5, detect_concurrency=1)
        self.assertIn("400", rows[0].source_label)

    @staticmethod
    def _detect_result(song_id: str, *_args, **_kwargs):
        return mock.Mock(song_id=song_id, song_name=f"歌 {song_id}", can_download=True,
                         media_url="", unavailable_reason="", size_bytes=0)


class ApiEdgeTests(unittest.TestCase):
    def test_short_link_that_resolves_off_netease_is_rejected(self):
        from music_fetch.api import parse_input_resource

        with mock.patch("music_fetch.api.resolve_short_url", return_value="https://example.com/song?id=1"):
            with self.assertRaises(MusicFetchError) as ctx:
                parse_input_resource("https://163cn.tv/abc")
        self.assertEqual(ctx.exception.code, "INVALID_URL")

    def test_ids_are_read_from_paths_and_fragments(self):
        self.assertEqual(_extract_resource_id(parse.urlparse("https://music.163.com/song/123"), ""), "123")
        fragment_url = "https://music.163.com/#/playlist?id=77&x=1"
        self.assertEqual(_extract_resource_id(parse.urlparse(fragment_url), fragment_url), "77")

    def test_song_metadata_error_paths(self):
        with mock.patch("music_fetch.api.perform_json_get", return_value=(500, {})):
            self.assertEqual(fetch_song_metadata("1", "MUSIC_U=test", 5), (None, None, None, None, None))
        with mock.patch("music_fetch.api.perform_json_get", return_value=(200, {"code": 200, "songs": []})):
            self.assertEqual(fetch_song_metadata("1", "MUSIC_U=test", 5), (None, None, None, None, None))

    def test_playable_url_codes_are_distinguished(self):
        with mock.patch("music_fetch.api.perform_json_post", return_value=(200, {"code": 301})):
            with self.assertRaises(MusicFetchError) as ctx:
                fetch_playable_candidates("1", "MUSIC_U=test", timeout=5)
        self.assertEqual(ctx.exception.code, "AUTH_EXPIRED")

        with mock.patch(
            "music_fetch.api.perform_json_post", return_value=(200, {"code": 500, "message": "boom"})
        ):
            with self.assertRaises(MusicFetchError) as ctx:
                fetch_playable_candidates("1", "MUSIC_U=test", timeout=5)
        self.assertEqual(ctx.exception.code, "NETWORK_ERROR")

    def test_album_failure_paths(self):
        with mock.patch(
            "music_fetch.api.perform_json_get", side_effect=MusicFetchError(ErrorCode.NETWORK_ERROR, "x")
        ):
            with self.assertRaises(MusicFetchError):
                fetch_album_songs("1", "MUSIC_U=test", timeout=5)
        with mock.patch("music_fetch.api.perform_json_get", return_value=(403, {})):
            with self.assertRaises(MusicFetchError) as ctx:
                fetch_album_songs("1", "MUSIC_U=test", timeout=5)
        self.assertEqual(ctx.exception.code, "AUTH_EXPIRED")
        with mock.patch("music_fetch.api.perform_json_get", return_value=(500, {"message": "boom"})):
            with self.assertRaises(MusicFetchError) as ctx:
                fetch_album_songs("1", "MUSIC_U=test", timeout=5)
        self.assertEqual(ctx.exception.code, "NETWORK_ERROR")

    def test_album_rows_must_be_objects_with_integer_ids(self):
        body = {"code": 200, "album": {"name": "专辑", "songs": ["junk", {"id": "text"}, {"id": 7}]}}
        with mock.patch("music_fetch.api.perform_json_get", return_value=(200, body)):
            album = fetch_album_songs("1", "MUSIC_U=test", timeout=5)
        self.assertEqual(album.song_ids, ["7"])

    def test_search_skips_malformed_rows(self):
        body = {"code": 200, "result": {"songs": ["junk", {"name": "no id"}, {"id": 9, "name": "OK"}]}}
        with mock.patch("music_fetch.api.perform_json_post", return_value=(200, body)):
            results = search_songs("kw", "MUSIC_U=test")
        self.assertEqual([song.song_id for song in results], ["9"])

    def test_playlist_account_failure_paths(self):
        with mock.patch(
            "music_fetch.api.perform_json_get", return_value=(500, {"message": "boom"})
        ):
            with self.assertRaises(MusicFetchError) as ctx:
                fetch_user_playlists("MUSIC_U=test")
        self.assertEqual(ctx.exception.code, "NETWORK_ERROR")

        with mock.patch("music_fetch.api.perform_json_get", return_value=(200, {"code": 200, "account": {}})):
            with self.assertRaises(MusicFetchError) as ctx:
                fetch_user_playlists("MUSIC_U=test")
        self.assertEqual(ctx.exception.code, "AUTH_EXPIRED")

    def test_lyric_api_failure_returns_an_empty_lyric(self):
        with mock.patch("music_fetch.api.perform_json_get", return_value=(500, {})):
            self.assertEqual(fetch_lyric("1").lyric, "")


class ProgressSnapshotTests(unittest.TestCase):
    def test_snapshot_fields_are_exposed(self):
        snapshot = DownloadProgressSnapshot(10, 20, 30)
        self.assertEqual((snapshot.downloaded, snapshot.total, snapshot.speed), (10, 20, 30))


if __name__ == "__main__":
    unittest.main()
