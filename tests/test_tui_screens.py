"""Screen-level coverage for the TUI: routing, guards and error branches.

Every interactive helper is patched through :func:`offline_ui` so a screen can
never block waiting for input — a forgotten mock used to hang the whole suite
until it was killed.
"""

import contextlib
import json
import shutil
import signal
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from music_fetch.api import MusicFetchError
from music_fetch.app_settings import DEFAULT_DOWNLOAD_DIR, APP_VERSION
from music_fetch.app_stores import DownloadHistoryStore, SessionStore
from music_fetch.batch_models import BatchDetectRow
from music_fetch.download_queue import DownloadProgressSnapshot, DownloadRequest
from music_fetch.tui import (
    MENU_BATCH,
    MENU_DIAGNOSTICS,
    MENU_HISTORY,
    MENU_LIKED,
    MENU_LOGOUT,
    MENU_PLAYLISTS,
    MENU_PLAYLIST_SEARCH,
    MENU_SEARCH,
    MENU_SETTINGS,
    MENU_SINGLE,
    MENU_UPDATE,
    TuiApp,
    _DetectedBatch,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"

_PRINT_HELPERS = (
    "print_info", "print_header", "print_success", "print_warning", "print_error",
    "print_status", "print_table", "print_panel", "clear_screen",
)
_INTERACTIVE = {
    "menu": 1,
    "ask": "",
    "ask_required": "",
    "ask_int": 0,
    "confirm": False,
    "multiselect": [],
    "live_ask": "0",
    "input_multiline": "",
    "spinner": None,
}


@contextlib.contextmanager
def offline_ui(**kwargs):
    """Patch every interactive helper and return the mocks by name.

    ``side_effect_<name>=...`` sets a side effect instead of a return value.
    """
    side_effects = {key[len("side_effect_"):]: value for key, value in kwargs.items()
                    if key.startswith("side_effect_")}
    overrides = {key: value for key, value in kwargs.items() if not key.startswith("side_effect_")}
    specs = dict(_INTERACTIVE)
    specs.update(overrides)
    with contextlib.ExitStack() as stack:
        mocks = {name: stack.enter_context(mock.patch(f"music_fetch.tui.U.{name}")) for name in _PRINT_HELPERS}
        for name, value in specs.items():
            patched = stack.enter_context(mock.patch(f"music_fetch.tui.U.{name}"))
            if value is not None:
                patched.return_value = value
            mocks[name] = patched
        for name, value in side_effects.items():
            mocks[name].side_effect = value
        yield mocks


def pick(label):
    """Menu side effect that always resolves *label* to its current index."""
    def side_effect(title, options, **kwargs):
        return options.index(label) + 1
    return side_effect


class TuiScreenTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.session_store = SessionStore(base / "session.json")
        self.history_store = DownloadHistoryStore(base / "history.json")
        self.app = TuiApp(
            session_store=self.session_store,
            history_store=self.history_store,
            queue_path=base / "queue.json",
        )
        self.app.session.cookie = "MUSIC_U=test"

    def detection(self, **overrides):
        values = dict(
            song_id="42", song_name="歌", artist="a", album_name="b", level="standard",
            encode_type="mp3", duration_ms=1000, media_url="https://cdn/x.mp3",
            can_download=True, cover_url=None, unavailable_reason=None,
        )
        values.update(overrides)
        return mock.Mock(**values)


class RoutingTests(TuiScreenTestCase):
    def test_dispatch_routes_every_menu_label(self):
        routes = {
            MENU_SINGLE: "_screen_single",
            MENU_SEARCH: "_screen_search",
            MENU_LIKED: "_screen_liked",
            MENU_PLAYLISTS: "_screen_playlists",
            MENU_PLAYLIST_SEARCH: "_screen_playlist_search",
            MENU_BATCH: "_screen_batch",
            MENU_HISTORY: "_screen_history",
            MENU_SETTINGS: "_screen_settings",
            MENU_DIAGNOSTICS: "_screen_diagnostics",
            MENU_UPDATE: "_screen_check_update",
        }
        for label, method in routes.items():
            with self.subTest(label=label), mock.patch.object(self.app, method) as screen_mock, offline_ui():
                self.app._dispatch_screen(label)
            screen_mock.assert_called_once()

    def test_logout_requires_confirmation(self):
        with mock.patch.object(self.app, "_clear_login") as clear_mock, offline_ui(confirm=True):
            self.app._dispatch_screen(MENU_LOGOUT)
        clear_mock.assert_called_once()

    def test_logout_can_be_declined(self):
        with mock.patch.object(self.app, "_clear_login") as clear_mock, offline_ui(confirm=False):
            self.app._dispatch_screen(MENU_LOGOUT)
        clear_mock.assert_not_called()


class LoginGuardTests(TuiScreenTestCase):
    def test_require_login_offers_to_log_in(self):
        self.app.session.cookie = ""
        with mock.patch.object(self.app, "_login_and_return", return_value=True) as login_mock, offline_ui(confirm=True):
            self.assertTrue(self.app._require_login())
        login_mock.assert_called_once()

    def test_require_login_declines_without_logging_in(self):
        self.app.session.cookie = ""
        with mock.patch.object(self.app, "_login_and_return") as login_mock, offline_ui(confirm=False):
            self.assertFalse(self.app._require_login())
        login_mock.assert_not_called()

    def test_require_login_reports_the_actual_outcome(self):
        self.app.session.cookie = ""

        def login() -> bool:
            return False  # the user opened the login screen but came back logged out

        with mock.patch.object(self.app, "_login_and_return", side_effect=login), offline_ui(confirm=True):
            self.assertFalse(self.app._require_login())

    def test_browser_login_errors_are_reported(self):
        from music_fetch.browser_login import BrowserLoginError

        for error in (BrowserLoginError("no browser"), MusicFetchError("NETWORK_ERROR", "boom")):
            with self.subTest(error=type(error).__name__), mock.patch(
                "music_fetch.browser_login.run_official_login", side_effect=error
            ), mock.patch.object(self.app, "_accept_cookie") as accept_mock, offline_ui() as ui:
                self.app._login_with_browser()
            ui["print_error"].assert_called()
            accept_mock.assert_not_called()


class StartupNoticeTests(TuiScreenTestCase):
    def test_restored_queue_is_announced(self):
        base = Path(self._tmp.name)
        finished = base / "done.mp3"
        shutil.copy(FIXTURES / "silence.mp3", finished)
        (base / "queue.json").write_text(json.dumps([
            {"request": {"song_id": "1", "song_name": "已有", "output_path": str(finished)}, "state": "pending"},
            {"request": {"song_id": "2", "song_name": "缺失", "output_path": str(base / "missing.mp3")}, "state": "pending"},
        ], ensure_ascii=False), encoding="utf-8")

        app = TuiApp(session_store=self.session_store, history_store=self.history_store,
                     queue_path=base / "queue.json")
        notices = [message for message, _error in app._pending_notices]
        self.assertTrue(any("恢复" in message and "记为完成" in message for message in notices))


class SingleScreenTests(TuiScreenTestCase):
    def test_blank_input_returns_without_prompting(self):
        with offline_ui(ask="") as ui:
            self.app._screen_single()
        ui["menu"].assert_not_called()

    def test_album_link_routes_into_the_batch_flow(self):
        with mock.patch("music_fetch.tui.parse_input_resource", return_value=("album", "7")), mock.patch.object(
            self.app, "_batch_flow"
        ) as batch_mock, offline_ui(ask="album link", confirm=True):
            self.app._screen_single()
        batch_mock.assert_called_once_with("https://music.163.com/album?id=7")

    def test_album_link_import_can_be_declined(self):
        with mock.patch("music_fetch.tui.parse_input_resource", return_value=("album", "7")), mock.patch.object(
            self.app, "_batch_flow"
        ) as batch_mock, offline_ui(ask="album link", confirm=False):
            self.app._screen_single()
        batch_mock.assert_not_called()

    def test_unparsable_input_falls_back_to_single_song_detection(self):
        with mock.patch(
            "music_fetch.tui.parse_input_resource", side_effect=MusicFetchError("INVALID_URL", "bad")
        ), mock.patch("music_fetch.tui.detect_song", return_value=self.detection()) as detect_mock, mock.patch(
            "music_fetch.tui.probe_media_size_bytes", return_value=0
        ), mock.patch.object(self.app, "_download_song") as download_mock, offline_ui(ask="42", menu=1):
            self.app._screen_single()
        detect_mock.assert_called_once()
        download_mock.assert_called_once()

    def test_detection_failure_is_reported(self):
        with mock.patch("music_fetch.tui.parse_input_resource", return_value=("song", "42")), mock.patch(
            "music_fetch.tui.detect_song", side_effect=MusicFetchError("NETWORK_ERROR", "boom")
        ), mock.patch.object(self.app, "_handle_auth_expired") as expired_mock, offline_ui(ask="42") as ui:
            self.app._screen_single()
        ui["print_error"].assert_called()
        expired_mock.assert_not_called()

    def test_expired_login_during_detection_triggers_reauth(self):
        with mock.patch("music_fetch.tui.parse_input_resource", return_value=("song", "42")), mock.patch(
            "music_fetch.tui.detect_song", side_effect=MusicFetchError("AUTH_EXPIRED", "expired")
        ), mock.patch.object(self.app, "_handle_auth_expired") as expired_mock, offline_ui(ask="42"):
            self.app._screen_single()
        expired_mock.assert_called_once()

    def test_unavailable_song_is_reported(self):
        result = self.detection(can_download=False, media_url=None, unavailable_reason="VIP only")
        with mock.patch("music_fetch.tui.parse_input_resource", return_value=("song", "42")), mock.patch(
            "music_fetch.tui.detect_song", return_value=result
        ), mock.patch.object(self.app, "_download_song") as download_mock, offline_ui(ask="42") as ui:
            self.app._screen_single()
        ui["print_error"].assert_called()
        download_mock.assert_not_called()

    def test_preview_action_reopens_the_menu(self):
        picks = iter([2, 3])  # 试听 → 返回
        with mock.patch("music_fetch.tui.parse_input_resource", return_value=("song", "42")), mock.patch(
            "music_fetch.tui.detect_song", return_value=self.detection()
        ), mock.patch("music_fetch.tui.probe_media_size_bytes", return_value=4096), mock.patch.object(
            self.app, "_preview_song"
        ) as preview_mock, mock.patch.object(self.app, "_download_song") as download_mock, offline_ui(
            ask="42", side_effect_menu=lambda *args, **kwargs: next(picks)
        ):
            self.app._screen_single()
        preview_mock.assert_called_once()
        download_mock.assert_not_called()

    def test_preview_song_reports_failure(self):
        with mock.patch(
            "music_fetch.audio.download_preview_to_temp", side_effect=MusicFetchError("SONG_UNAVAILABLE", "no")
        ), offline_ui() as ui:
            self.app._preview_song("42", "歌")
        ui["print_error"].assert_called()

    def test_preview_song_opens_the_downloaded_file(self):
        with mock.patch(
            "music_fetch.audio.download_preview_to_temp", return_value=Path("preview.mp3")
        ), mock.patch.object(self.app, "_open_path") as open_mock, offline_ui():
            self.app._preview_song("42", "歌")
        open_mock.assert_called_once()


class SearchAndPlaylistScreenTests(TuiScreenTestCase):
    def test_search_failure_is_reported(self):
        with mock.patch(
            "music_fetch.tui.search_songs", side_effect=MusicFetchError("NETWORK_ERROR", "boom")
        ), offline_ui(ask="keyword") as ui:
            self.app._screen_search()
        ui["print_error"].assert_called()

    def test_search_without_matches_warns(self):
        with mock.patch("music_fetch.tui.search_songs", return_value=[]), offline_ui(ask="keyword") as ui:
            self.app._screen_search()
        ui["print_warning"].assert_called()

    def test_playlist_screen_failure_and_empty_states(self):
        with mock.patch(
            "music_fetch.tui.fetch_user_playlists", side_effect=MusicFetchError("AUTH_EXPIRED", "x")
        ), mock.patch.object(self.app, "_handle_auth_expired") as expired_mock, offline_ui():
            self.app._screen_playlists()
        expired_mock.assert_called_once()

        with mock.patch("music_fetch.tui.fetch_user_playlists", return_value=[]), offline_ui() as ui:
            self.app._screen_playlists()
        ui["print_warning"].assert_called()

    def test_playlist_search_failure_is_reported(self):
        with mock.patch(
            "music_fetch.tui.search_playlists", side_effect=MusicFetchError("NETWORK_ERROR", "boom")
        ), mock.patch.object(self.app, "_batch_flow") as batch_mock, offline_ui(ask="摇滚") as ui:
            self.app._screen_playlist_search()
        ui["print_error"].assert_called()
        batch_mock.assert_not_called()

    def test_liked_screen_reports_transport_failure(self):
        with mock.patch(
            "music_fetch.tui.fetch_account_profile", side_effect=MusicFetchError("NETWORK_ERROR", "boom")
        ), mock.patch.object(self.app, "_batch_flow") as batch_mock, offline_ui() as ui:
            self.app._screen_liked()
        ui["print_error"].assert_called()
        batch_mock.assert_not_called()


class BatchScreenTests(TuiScreenTestCase):
    def test_batch_screen_guards_and_dispatch(self):
        self.app.session.cookie = ""
        with mock.patch.object(self.app, "_require_login", return_value=False) as login_mock, mock.patch.object(
            self.app, "_batch_flow"
        ) as batch_mock, offline_ui():
            self.app._screen_batch()
        login_mock.assert_called_once()
        batch_mock.assert_not_called()

        self.app.session.cookie = "MUSIC_U=test"
        with mock.patch.object(self.app, "_batch_flow") as batch_mock, offline_ui(input_multiline="   "):
            self.app._screen_batch()
        batch_mock.assert_not_called()

        with mock.patch.object(self.app, "_batch_flow") as batch_mock, offline_ui(
            input_multiline="https://music.163.com/song?id=1"
        ):
            self.app._screen_batch()
        batch_mock.assert_called_once()

    def test_batch_flow_reports_detection_failure(self):
        with mock.patch(
            "music_fetch.tui.run_batch_detect", side_effect=MusicFetchError("NETWORK_ERROR", "boom")
        ), mock.patch.object(self.app, "_handle_auth_expired") as expired_mock, offline_ui() as ui:
            self.app._batch_flow("x")
        ui["print_error"].assert_called()
        expired_mock.assert_not_called()

    def test_batch_flow_handles_empty_detection(self):
        with mock.patch("music_fetch.tui.run_batch_detect", return_value=[]), offline_ui() as ui:
            self.app._batch_flow("x")
        ui["print_warning"].assert_called()

    def test_batch_flow_offers_export_when_nothing_is_downloadable(self):
        rows = [BatchDetectRow("1", song_id="1", song_name="A", status="unavailable")]
        with mock.patch("music_fetch.tui.run_batch_detect", return_value=rows), mock.patch.object(
            self.app, "_offer_batch_export"
        ) as export_mock, offline_ui() as ui:
            self.app._batch_flow("x")
        ui["print_warning"].assert_called()
        export_mock.assert_called_once()


class BatchExportTests(TuiScreenTestCase):
    def _rows(self):
        return [BatchDetectRow("1", song_id="1", song_name="A", status="ready")]

    def test_export_writes_a_csv_and_appends_the_suffix(self):
        target = Path(self._tmp.name) / "batch"
        with offline_ui(confirm=True, ask=str(target)) as ui:
            self.app._offer_batch_export(self._rows())
        written = target.with_suffix(".csv")
        self.assertTrue(written.exists())
        # Content, not just existence: writing an empty file used to pass.
        self.assertIn("A", written.read_text(encoding="utf-8-sig"))
        ui["print_success"].assert_called()

    def test_export_can_be_declined(self):
        with offline_ui(confirm=False) as ui:
            self.app._offer_batch_export(self._rows())
        ui["ask"].assert_not_called()

    def test_export_reports_write_errors(self):
        target = Path(self._tmp.name) / "batch.csv"
        with mock.patch.object(Path, "write_text", side_effect=OSError("disk full")), offline_ui(
            confirm=True, ask=str(target)
        ) as ui:
            self.app._offer_batch_export(self._rows())
        ui["print_error"].assert_called()

    def test_export_without_rows_does_nothing(self):
        with offline_ui() as ui:
            self.app._offer_batch_export([])
        ui["confirm"].assert_not_called()


class QueueStatusTests(TuiScreenTestCase):
    def test_status_is_empty_without_tasks(self):
        self.assertEqual(self.app._queue_status(), "")

    def test_status_reports_counts_progress_and_flags(self):
        self.app.queue.enqueue(DownloadRequest("1", "song", Path(self._tmp.name) / "1.mp3"))
        self.app.queue._items[0].state = "running"
        self.app.queue._items[0].progress = DownloadProgressSnapshot(50, 100, 1234)
        self.app.queue._history_error = "history broken"

        text = self.app._queue_status()

        self.assertIn("任务 |", text)
        self.assertIn("下载中", text)
        self.assertIn("历史保存失败", text)


class TaskPageKeyTests(TuiScreenTestCase):
    def _queued(self):
        return self.app.queue.enqueue(DownloadRequest("1", "song", Path(self._tmp.name) / "1.mp3"))

    def test_login_export_and_paging_keys(self):
        self._queued()
        inputs = iter(["p", "e", "l", "x", "0"])
        with mock.patch.object(self.app, "_screen_login") as login_mock, mock.patch.object(
            self.app, "_export_queue_batch"
        ) as export_mock, mock.patch.object(self.app, "_clear_login") as clear_mock, offline_ui(
            side_effect_live_ask=inputs
        ) as ui:
            self.app.queue._cookie = ""  # auth_required → the login key resets it first
            self.app._screen_tasks()
        login_mock.assert_called_once()
        export_mock.assert_called_once()
        clear_mock.assert_called_once()
        ui["print_warning"].assert_called()

    def test_task_detail_rows_cover_finished_states(self):
        item = self._queued()
        self.app.queue._items[0].state = "success"
        self.app.queue._items[0].size_bytes = 2048
        rows = dict(TuiApp._task_detail_rows(self.app.queue.item(item.task_id)))
        self.assertIn("大小", rows)

    def test_task_detail_returns_on_zero(self):
        item = self._queued()
        with offline_ui(live_ask="0") as ui:
            self.app._task_actions(item)
        ui["menu"].assert_not_called()

    def test_task_detail_can_open_the_folder(self):
        item = self._queued()
        with mock.patch.object(self.app, "_open_path") as open_mock, offline_ui(live_ask="", menu=1):
            self.app._task_actions(item)
        open_mock.assert_called_once()


class TaskActionHelperTests(TuiScreenTestCase):
    def test_retry_reports_submit_failure(self):
        with mock.patch.object(self.app.queue, "retry", side_effect=ValueError("gone")), offline_ui() as ui:
            self.app._retry_task("missing")
        ui["print_error"].assert_called()

    def test_export_queue_batch_without_batches_informs(self):
        with offline_ui() as ui:
            self.app._export_queue_batch()
        ui["print_info"].assert_called()

    def test_export_queue_batch_can_be_cancelled(self):
        item = self.app.queue.enqueue(DownloadRequest("1", "song", Path(self._tmp.name) / "1.mp3"))
        self.app._batches = [_DetectedBatch([BatchDetectRow("1", song_id="1", song_name="A", status="ready")], {0: item.task_id})]
        with mock.patch.object(self.app, "_offer_batch_export") as export_mock, offline_ui(menu=2):
            self.app._export_queue_batch()
        export_mock.assert_not_called()

    def test_export_queue_batch_uses_live_task_state(self):
        item = self.app.queue.enqueue(DownloadRequest("1", "song", Path(self._tmp.name) / "1.mp3"))
        self.app.queue._items[0].state = "success"
        self.app.queue._items[0].size_bytes = 4096
        self.app._batches = [_DetectedBatch([BatchDetectRow("1", song_id="1", song_name="A", status="ready")], {0: item.task_id})]
        with mock.patch.object(self.app, "_offer_batch_export") as export_mock, offline_ui(menu=1):
            self.app._export_queue_batch()
        rows = export_mock.call_args.args[0]
        self.assertEqual(rows[0].media_size_bytes, 4096)
        self.assertEqual(rows[0].status, "download_success")


class DownloadOptionTests(TuiScreenTestCase):
    def test_blank_input_without_default_asks_again(self):
        with offline_ui(side_effect_ask=["", "0"]) as ui:
            self.assertIsNone(self.app._ask_with_cancel("prompt"))
        ui["print_warning"].assert_called()

    def test_pick_format_returns_the_choice_and_supports_cancel(self):
        formats = list(__import__("music_fetch.app_settings", fromlist=["SUPPORTED_AUDIO_FORMATS"]).SUPPORTED_AUDIO_FORMATS)
        with mock.patch("music_fetch.tui.is_ffmpeg_available", return_value=True), offline_ui(menu=2):
            self.assertEqual(self.app._pick_format(), formats[1])
        with offline_ui(menu=len(formats) + 1):
            self.assertIsNone(self.app._pick_format())

    def test_pick_format_warns_when_ffmpeg_is_missing(self):
        with mock.patch("music_fetch.tui.is_ffmpeg_available", return_value=False), offline_ui(menu=1) as ui:
            self.assertEqual(self.app._pick_format(), "mp3")
        ui["print_warning"].assert_called()

    def test_pick_lyric_mode_maps_every_choice(self):
        expected = {1: (False, "original"), 2: (True, "original"), 3: (True, "bilingual"), 4: (True, "translation")}
        for choice, result in expected.items():
            with self.subTest(choice=choice), offline_ui(menu=choice):
                self.assertEqual(TuiApp._pick_lyric_mode(), result)


class DownloadSongBranchTests(TuiScreenTestCase):
    def _wizard(self, **overrides):
        patches = [
            mock.patch.object(self.app, "_ask_with_cancel", side_effect=[self._tmp.name, "song-1"]),
            mock.patch.object(self.app, "_pick_format", return_value="mp3"),
            mock.patch.object(self.app, "_pick_lyric_mode", return_value=(False, "original")),
        ]
        return patches

    def test_cancelling_the_directory_aborts(self):
        with mock.patch.object(self.app, "_ask_with_cancel", return_value=None):
            self.assertFalse(self.app._download_song("1", "song"))

    def test_cancelling_the_filename_aborts(self):
        with mock.patch.object(self.app, "_ask_with_cancel", side_effect=[self._tmp.name, None]):
            self.assertFalse(self.app._download_song("1", "song"))

    def test_cancelling_the_format_aborts(self):
        with mock.patch.object(self.app, "_ask_with_cancel", side_effect=[self._tmp.name, "song-1"]), mock.patch.object(
            self.app, "_pick_format", return_value=None
        ):
            self.assertFalse(self.app._download_song("1", "song"))

    def test_path_resolution_failure_is_reported(self):
        with self._wizard()[0], self._wizard()[1], self._wizard()[2], mock.patch(
            "music_fetch.tui.resolve_output_path", side_effect=MusicFetchError("PATH_TOO_LONG", "long")
        ), offline_ui() as ui:
            self.assertFalse(self.app._download_song("1", "song"))
        ui["print_error"].assert_called()

    def test_enqueue_failure_is_reported(self):
        with self._wizard()[0], self._wizard()[1], self._wizard()[2], mock.patch.object(
            self.app.queue, "enqueue", side_effect=OSError("disk full")
        ), offline_ui() as ui:
            self.assertFalse(self.app._download_song("1", "song"))
        ui["print_error"].assert_called()

    def test_skip_policy_records_a_file_that_vanishes_before_stat(self):
        vanished = mock.MagicMock(spec=Path)
        vanished.stat.side_effect = OSError("gone")
        with self._wizard()[0], self._wizard()[1], self._wizard()[2], mock.patch(
            "music_fetch.tui.should_skip_existing", return_value=True
        ), mock.patch("music_fetch.tui.resolve_output_path", return_value=vanished), mock.patch.object(
            self.app, "_add_record"
        ) as record_mock, offline_ui():
            self.assertTrue(self.app._download_song("1", "song"))
        self.assertEqual(record_mock.call_args.args[3], 0)


class HistoryScreenTests(TuiScreenTestCase):
    def _seed(self):
        for index in (1, 2):
            self.app._add_record(str(index), f"歌 {index}", str(Path(self._tmp.name) / f"{index}.mp3"), 10, "success")

    def test_empty_history_warns(self):
        with offline_ui() as ui:
            self.app._screen_history()
        ui["print_warning"].assert_called()

    def test_paging_boundaries_and_bad_input(self):
        self._seed()
        with offline_ui(side_effect_ask=["p", "n", "99", "zzz", "0"]) as ui:
            self.app._screen_history()
        warnings = [str(call.args[0]) for call in ui["print_warning"].call_args_list]
        self.assertIn("已经是第一页。", warnings)
        self.assertIn("无法识别的输入，请重试。", warnings)

    def test_status_filter_and_export_and_clear(self):
        self._seed()
        with mock.patch.object(self.app, "_pick_status_filter", return_value="success") as filter_mock, mock.patch.object(
            self.app, "_export_history_csv"
        ) as export_mock, mock.patch.object(self.app, "_clear_history") as clear_mock, offline_ui(
            side_effect_ask=["f", "e", "c", "0"]
        ):
            self.app._screen_history()
        filter_mock.assert_called_once()
        export_mock.assert_called_once()
        clear_mock.assert_called_once()

    def test_pick_status_filter_maps_the_choice(self):
        with offline_ui(menu=2) as ui:
            self.assertEqual(self.app._pick_status_filter(), "success")
        # Only states that history can actually hold are offered.
        self.assertEqual(ui["menu"].call_args.args[1], ["全部", "成功", "失败", "已取消"])

    def test_export_history_csv_writes_the_filtered_rows(self):
        self._seed()
        target = Path(self._tmp.name) / "history"
        with offline_ui(confirm=True, ask=str(target)) as ui:
            self.app._export_history_csv(self.history_store.load())
        written = target.with_suffix(".csv")
        self.assertTrue(written.exists())
        self.assertIn("歌 1", written.read_text(encoding="utf-8-sig"))
        ui["print_success"].assert_called()

    def test_export_history_csv_handles_no_rows_and_errors(self):
        with offline_ui() as ui:
            self.app._export_history_csv([])
        ui["print_warning"].assert_called()

        self._seed()
        target = Path(self._tmp.name) / "history.csv"
        with mock.patch.object(Path, "write_text", side_effect=OSError("disk full")), offline_ui(
            confirm=True, ask=str(target)
        ) as ui:
            self.app._export_history_csv(self.history_store.load())
        ui["print_error"].assert_called()


class HistoryActionTests(TuiScreenTestCase):
    def _record(self, **overrides):
        from music_fetch.app_stores import DownloadRecord

        values = dict(
            song_id="1", song_name="歌", output_path=str(Path(self._tmp.name) / "1.mp3"),
            size_bytes=1, downloaded_at="2026-01-01 00:00:00", status="failed",
        )
        values.update(overrides)
        return DownloadRecord(**values)

    def test_open_folder_action(self):
        with mock.patch.object(self.app, "_open_path") as open_mock, offline_ui(menu=1):
            self.app._history_record_actions(self._record())
        open_mock.assert_called_once()

    def test_delete_action_removes_file_and_record(self):
        target = Path(self._tmp.name) / "1.mp3"
        target.write_bytes(b"x")
        with offline_ui(menu=2, confirm=True) as ui:
            self.app._history_record_actions(self._record(output_path=str(target)))
        self.assertFalse(target.exists())
        self.assertEqual(self.app.history_store.load(), [])
        ui["print_success"].assert_called()

    def test_delete_action_can_be_declined(self):
        target = Path(self._tmp.name) / "1.mp3"
        target.write_bytes(b"x")
        with offline_ui(menu=2, confirm=False):
            self.app._history_record_actions(self._record(output_path=str(target)))
        self.assertTrue(target.exists())

    def test_retry_is_only_offered_for_failed_records(self):
        with mock.patch.object(self.app, "_retry_record") as retry_mock, offline_ui(menu=2) as ui:
            self.app._history_record_actions(self._record(status="success"))
        labels = ui["menu"].call_args.args[1]
        self.assertNotIn("重试下载", labels)
        retry_mock.assert_not_called()

    def test_retry_action_calls_the_retry_helper(self):
        record = self._record()
        with mock.patch.object(self.app, "_retry_record") as retry_mock, offline_ui(menu=3):
            self.app._history_record_actions(record)
        retry_mock.assert_called_once_with(record)

    def test_delete_reports_filesystem_failure(self):
        target = Path(self._tmp.name) / "1.mp3"
        target.write_bytes(b"x")
        with mock.patch.object(Path, "unlink", side_effect=OSError("locked")), offline_ui(
            menu=2, confirm=True
        ) as ui:
            self.app._history_record_actions(self._record(output_path=str(target)))
        ui["print_warning"].assert_called()

    def test_retry_record_requires_a_login(self):
        self.app.session.cookie = ""
        with mock.patch.object(self.app, "_login_and_return") as login_mock, offline_ui() as ui:
            self.assertIsNone(self.app._retry_record(self._record()))
        login_mock.assert_called_once()
        ui["print_warning"].assert_called()

    def test_retry_record_reuses_a_matching_failed_task(self):
        item = self.app.queue.enqueue(DownloadRequest("1", "歌", Path(self._tmp.name) / "1.mp3"))
        self.app.queue._items[0].state = "failed"
        record = self._record(output_path=str(item.output_path))
        with mock.patch.object(self.app, "_retry_task") as retry_mock:
            self.assertTrue(self.app._retry_record(record))
        retry_mock.assert_called_once_with(item.task_id)

    def test_retry_record_enqueues_and_reports_submit_failure(self):
        record = self._record()
        with offline_ui() as ui:
            self.assertTrue(self.app._retry_record(record))
        ui["print_info"].assert_called()

        with mock.patch.object(self.app.queue, "enqueue", side_effect=ValueError("bad")), offline_ui() as ui:
            self.assertFalse(self.app._retry_record(self._record()))
        ui["print_error"].assert_called()

    def test_retry_all_failed_guards(self):
        with offline_ui() as ui:
            self.app._retry_all_failed([self._record(status="success")])
        ui["print_warning"].assert_called()

        with offline_ui(confirm=False) as ui:
            self.app._retry_all_failed([self._record()])
        ui["confirm"].assert_called()

    def test_retry_all_failed_requires_a_login(self):
        self.app.session.cookie = ""
        with mock.patch.object(self.app, "_login_and_return") as login_mock, mock.patch.object(
            self.app, "_retry_record"
        ) as retry_mock, offline_ui(confirm=True):
            self.app._retry_all_failed([self._record()])
        login_mock.assert_called_once()
        retry_mock.assert_not_called()

    def test_retry_all_failed_summarises_the_outcome(self):
        with mock.patch.object(self.app, "_retry_record", side_effect=[True, False]), offline_ui(
            confirm=True
        ) as ui:
            self.app._retry_all_failed([self._record(), self._record(song_id="2")])
        self.assertIn("1/2", str(ui["print_info"].call_args))

    def test_clear_history_guards_and_reports_failure(self):
        with offline_ui() as ui:
            self.app._clear_history([])
        ui["print_warning"].assert_called()

        with mock.patch.object(self.app.history_store, "save", side_effect=OSError("disk")), offline_ui(
            confirm=True
        ) as ui:
            self.app._clear_history([self._record()])
        ui["print_error"].assert_called()


class BatchFlowInteractionTests(TuiScreenTestCase):
    def _rows(self, statuses=("ready", "ready")):
        return [
            BatchDetectRow(str(index), song_id=str(index), song_name=f"歌 {index}", status=status)
            for index, status in enumerate(statuses, start=1)
        ]

    def _detect(self, rows):
        return mock.patch("music_fetch.tui.run_batch_detect", return_value=rows)

    def test_next_step_back_returns(self):
        with self._detect(self._rows()), offline_ui(menu=3) as ui:
            self.app._batch_flow("x")
        ui["multiselect"].assert_not_called()

    def test_preview_any_detected_song(self):
        picks = iter([2, 3])  # 试听某首 → 返回
        with self._detect(self._rows()), mock.patch.object(self.app, "_preview_song") as preview_mock, offline_ui(
            side_effect_menu=lambda *args, **kwargs: next(picks), ask="1"
        ):
            self.app._batch_flow("x")
        preview_mock.assert_called_once_with("1", "歌 1")

    def test_preview_rejects_a_non_ready_index_and_a_bad_index(self):
        rows = self._rows(("ready", "unavailable"))
        picks = iter([2, 2, 3])  # 试听 → 试听 → 返回
        with self._detect(rows), mock.patch.object(self.app, "_preview_song") as preview_mock, offline_ui(
            side_effect_menu=lambda *args, **kwargs: next(picks), side_effect_ask=["2", "9"]
        ) as ui:
            self.app._batch_flow("x")
        preview_mock.assert_not_called()
        warnings = [str(call.args[0]) for call in ui["print_warning"].call_args_list]
        self.assertTrue(any("不可下载" in warning for warning in warnings))
        self.assertTrue(any("序号" in warning for warning in warnings))

    def test_empty_selection_offers_export(self):
        with self._detect(self._rows()), mock.patch.object(self.app, "_offer_batch_export") as export_mock, offline_ui(
            menu=1, multiselect=[]
        ):
            self.app._batch_flow("x")
        export_mock.assert_called_once()

    def test_cancelling_the_directory_aborts_the_batch(self):
        with self._detect(self._rows()), mock.patch.object(self.app, "_offer_batch_export") as export_mock, mock.patch.object(
            self.app, "_ask_with_cancel", return_value=None
        ), offline_ui(menu=1, multiselect=[0]):
            self.app._batch_flow("x")
        export_mock.assert_not_called()

    def test_ctrl_c_during_detection_cancels_and_keeps_partial_rows(self):
        captured: dict = {}
        partial = [BatchDetectRow("1", song_id="1", song_name="A", status="ready")]

        def fake_signal(signum, handler):
            captured["handler"] = handler
            return "previous-handler"

        def fake_detect(text, cookie, timeout, detect_concurrency=5, cancel_event=None, on_progress=None):
            captured["cancel_event"] = cancel_event
            captured["handler"](signal.SIGINT, None)  # the user presses Ctrl+C
            self.assertTrue(cancel_event.is_set())
            return partial

        with mock.patch("music_fetch.tui.signal.signal", side_effect=fake_signal) as signal_mock, mock.patch(
            "music_fetch.tui.run_batch_detect", side_effect=fake_detect
        ), mock.patch.object(self.app, "_offer_batch_export"), offline_ui(menu=3) as ui:
            self.app._batch_flow("x")

        # The previous SIGINT handler is restored…
        self.assertEqual(signal_mock.call_args_list[-1].args[1], "previous-handler")
        # …the interruption is reported, and the rows found so far survive.
        warnings = " ".join(str(call.args[0]) for call in ui["print_warning"].call_args_list)
        self.assertIn("识别已中断", warnings)
        self.assertTrue(captured["cancel_event"].is_set())
        self.assertEqual(ui["print_table"].call_count, 1)

    def test_detection_receives_a_cancel_event(self):
        seen: dict = {}

        def fake_detect(text, cookie, timeout, detect_concurrency=5, cancel_event=None, on_progress=None):
            seen["event"] = cancel_event
            return [BatchDetectRow("1", song_id="1", song_name="A", status="ready")]

        with mock.patch("music_fetch.tui.run_batch_detect", side_effect=fake_detect), mock.patch.object(
            self.app, "_offer_batch_export"
        ), offline_ui(menu=3):
            self.app._batch_flow("x")

        self.assertIsNotNone(seen["event"])
        self.assertFalse(seen["event"].is_set())

    def test_detection_survives_an_uninstallable_sigint_handler(self):
        # signal.signal raises off the main thread; detection must still run.
        rows = [BatchDetectRow("1", song_id="1", song_name="A", status="ready")]
        with mock.patch("music_fetch.tui.signal.signal", side_effect=ValueError("not main thread")), mock.patch(
            "music_fetch.tui.run_batch_detect", return_value=rows
        ), mock.patch.object(self.app, "_offer_batch_export"), offline_ui(menu=3) as ui:
            self.app._batch_flow("x")
        self.assertTrue(ui["print_table"].called)

    def test_cancelled_detection_without_rows_says_so(self):
        def fake_detect(text, cookie, timeout, detect_concurrency=5, cancel_event=None, on_progress=None):
            cancel_event.set()
            return []

        with mock.patch("music_fetch.tui.run_batch_detect", side_effect=fake_detect), offline_ui() as ui:
            self.app._batch_flow("x")

        warnings = " ".join(str(call.args[0]) for call in ui["print_warning"].call_args_list)
        self.assertIn("已取消识别", warnings)

    def test_preview_prompt_stays_readable_for_huge_batches(self):
        rows = [
            BatchDetectRow(str(index), song_id=str(index), song_name=f"歌 {index}", status="ready")
            for index in range(1, 101)
        ]
        picks = iter([2, 3])  # 试听某首 → 返回
        with self._detect(rows), mock.patch.object(self.app, "_preview_song"), offline_ui(
            side_effect_menu=lambda *args, **kwargs: next(picks), ask="0"
        ) as ui:
            self.app._batch_flow("x")
        prompts = [str(call.args[0]) for call in ui["ask"].call_args_list if "试听" in str(call.args[0])]
        self.assertEqual(len(prompts), 1)
        # Listing all 100 ready numbers used to build a ~400-character prompt
        # (thousands of tracks made it unreadable).
        self.assertLess(len(prompts[0]), 200)
        self.assertIn("…", prompts[0])

    def test_checklist_numbers_entries_by_table_row(self):
        rows = [
            BatchDetectRow("1", song_id="101", song_name="A", status="ready"),
            BatchDetectRow("2", song_id="102", song_name="B", status="unavailable"),
            BatchDetectRow("3", song_id="103", song_name="C", status="ready"),
        ]
        with self._detect(rows), mock.patch.object(self.app, "_offer_batch_export"), mock.patch.object(
            self.app, "_ask_with_cancel", return_value=None
        ), offline_ui(menu=1, multiselect=[0]) as ui:
            self.app._batch_flow("x")
        entries = ui["multiselect"].call_args.args[1]
        labels = [label for label, _selected in entries]
        # Only ready rows are listed, but they keep the table numbering so a user
        # counting rows on screen cannot queue the wrong song.
        self.assertEqual(labels, ["1. A（未知大小）", "3. C（未知大小）"])


class BatchPersistenceTests(TuiScreenTestCase):
    """Batches survive a restart so their results stay exportable."""

    def _batch_store(self, base: Path):
        from music_fetch.app_stores import BatchStore

        return BatchStore(base / "batches.json")

    def test_store_round_trip_and_malformed_entries(self):
        base = Path(self._tmp.name)
        store = self._batch_store(base)
        from music_fetch.app_stores import SavedBatch

        store.save([
            SavedBatch("2026-09-30 08:00:00", [{"song_id": "1", "status": "ready"}], {"0": "t1"}),
            SavedBatch("", [], {"0": "t2"}),          # no rows → dropped
            SavedBatch("", [{"song_id": "3"}], {}),   # rebuilt but has rows
        ])
        loaded = store.load()
        self.assertEqual([batch.task_ids for batch in loaded], [{"0": "t1"}, {}])

    def test_store_keeps_only_the_newest_batches(self):
        base = Path(self._tmp.name)
        from music_fetch.app_stores import BatchStore, SavedBatch
        import json as json_module

        store = BatchStore(base / "batches.json", max_batches=2)
        store.save([SavedBatch(f"t{index}", [{"song_id": str(index), "status": "ready"}], {}) for index in range(5)])
        loaded = store.load()
        self.assertEqual([batch.created_at for batch in loaded], ["t3", "t4"])
        # The file itself must be trimmed too, otherwise it grows without bound.
        persisted = json_module.loads(store.path.read_text(encoding="utf-8"))
        self.assertEqual([entry["created_at"] for entry in persisted], ["t3", "t4"])

    def test_entries_with_the_wrong_shape_are_dropped(self):
        base = Path(self._tmp.name)
        import json as json_module

        store = self._batch_store(base)
        store.path.write_text(json_module.dumps([
            "not a dict",
            {"rows": "not a list", "task_ids": {}},
            {"rows": [{"song_id": "1", "status": "ready"}]},          # no task_ids
            {"task_ids": {}, "rows": [{"song_id": "2", "status": "ready"}]},
        ]), encoding="utf-8")
        loaded = store.load()
        self.assertEqual([batch.rows[0]["song_id"] for batch in loaded], ["2"])

    def test_unreadable_store_file_is_quarantined(self):
        base = Path(self._tmp.name)
        store = self._batch_store(base)
        store.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(store.load(), [])
        self.assertTrue(store.path.with_name(store.path.name + ".corrupt").exists())

    def test_restored_batch_reports_a_notice(self):
        base = Path(self._tmp.name)
        self.app._batches = [_DetectedBatch(
            [BatchDetectRow("1", song_id="1", song_name="A", status="ready")], {0: "task-1"},
            created_at="2026-09-30 08:00:00",
        )]
        self.app._save_batches()

        restarted = TuiApp(
            session_store=self.session_store,
            history_store=self.history_store,
            queue_path=base / "queue.json",
        )
        self.assertEqual(len(restarted._batches), 1)
        restored = restarted._batches[0]
        self.assertEqual([row.song_id for row in restored.rows], ["1"])
        self.assertEqual(restored.task_ids, {0: "task-1"})
        self.assertEqual(restored.created_at, "2026-09-30 08:00:00")
        notices = [message for message, _error in restarted._pending_notices]
        self.assertTrue(any("历史批次" in message for message in notices))

    def test_restored_batch_exports_the_history_status(self):
        from music_fetch.app_stores import DownloadRecord

        base = Path(self._tmp.name)
        self.app._batches = [_DetectedBatch(
            [BatchDetectRow("1", song_id="1", song_name="A", status="ready")], {0: "task-1"},
            created_at="2026-09-30 08:00:00",
        )]
        self.app._save_batches()
        self.history_store.add(DownloadRecord("1", "A", str(base / "1.mp3"), 4096, "2026-09-30 08:01:00", status="success"))

        restarted = TuiApp(
            session_store=self.session_store,
            history_store=self.history_store,
            queue_path=base / "queue.json",
        )
        with mock.patch.object(restarted, "_offer_batch_export") as export_mock, offline_ui(menu=1):
            restarted._export_queue_batch()

        rows = export_mock.call_args.args[0]
        self.assertEqual(rows[0].status, "download_success")
        self.assertEqual(rows[0].media_size_bytes, 4096)
        self.assertFalse(rows[0].selected)

    def test_batch_without_a_live_task_or_history_keeps_its_recorded_status(self):
        self.app._batches = [_DetectedBatch(
            [BatchDetectRow("1", song_id="1", song_name="A", status="ready")], {0: "gone-task"},
        )]

        with mock.patch.object(self.app, "_offer_batch_export") as export_mock, offline_ui(menu=1):
            self.app._export_queue_batch()  # must not raise on the missing task

        rows = export_mock.call_args.args[0]
        self.assertEqual(rows[0].status, "ready")
        self.assertEqual(rows[0].message, "")

    def test_submitting_a_batch_persists_it(self):
        rows = [BatchDetectRow("1", song_id="1", song_name="A", status="ready")]
        with mock.patch("music_fetch.tui.run_batch_detect", return_value=rows), mock.patch.object(
            self.app, "_save_batches"
        ) as save_mock, mock.patch.object(self.app, "_offer_batch_export"), offline_ui(menu=1, multiselect=[0]):
            self.app._batch_flow("x")
        save_mock.assert_called_once()
        self.assertEqual(len(self.app._batches), 1)
        self.assertTrue(self.app._batches[0].created_at)


class PagerHelperTests(unittest.TestCase):
    """The paging primitives shared by the picker and the batch table."""

    def test_page_count_always_reports_at_least_one_page(self):
        self.assertEqual(TuiApp._page_count(0, 15), 1)
        self.assertEqual(TuiApp._page_count(1, 15), 1)
        self.assertEqual(TuiApp._page_count(15, 15), 1)
        self.assertEqual(TuiApp._page_count(16, 15), 2)
        self.assertEqual(TuiApp._page_count(30, 15), 2)
        self.assertEqual(TuiApp._page_count(31, 15), 3)

    def test_page_turn_moves_within_range(self):
        self.assertEqual(TuiApp._page_turn("n", 0, 3), 1)
        self.assertEqual(TuiApp._page_turn(" N ", 1, 3), 2)
        self.assertEqual(TuiApp._page_turn("p", 2, 3), 1)

    def test_page_turn_warns_at_the_boundaries(self):
        with offline_ui() as ui:
            self.assertIsNone(TuiApp._page_turn("n", 2, 3))
            self.assertIsNone(TuiApp._page_turn("p", 0, 3))
        warnings = [str(call.args[0]) for call in ui["print_warning"].call_args_list]
        self.assertIn("已经是最后一页。", warnings)
        self.assertIn("已经是第一页。", warnings)

    def test_page_turn_ignores_other_input(self):
        with offline_ui() as ui:
            self.assertIsNone(TuiApp._page_turn("2", 0, 3))
            self.assertIsNone(TuiApp._page_turn("", 0, 3))
        ui["print_warning"].assert_not_called()


class SessionNormalizationTests(unittest.TestCase):
    def test_a_blank_download_dir_falls_back_to_the_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            path.write_text('{"last_download_dir": "   "}', encoding="utf-8")
            self.assertEqual(SessionStore(path).load().last_download_dir, DEFAULT_DOWNLOAD_DIR)

    def test_saving_never_persists_a_blank_download_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            store = SessionStore(path)
            session = store.load()
            session.last_download_dir = "  "
            store.save(session)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["last_download_dir"], DEFAULT_DOWNLOAD_DIR
            )


class DiagnosticsAndUpdateTests(TuiScreenTestCase):
    def test_diagnostics_exports_a_report(self):
        target = Path(self._tmp.name) / "report.txt"
        with mock.patch("music_fetch.tui.run_network_diagnostics", return_value=[]), mock.patch(
            "music_fetch.tui.read_log_tail", return_value="2026-01-01 WARNING something broke\n"
        ), offline_ui(confirm=True, ask=str(target)) as ui:
            self.app._screen_diagnostics()
        self.assertTrue(target.exists())
        report = target.read_text(encoding="utf-8")
        self.assertIn(APP_VERSION, report)  # the report really describes this build
        ui["print_warning"].assert_called()  # the warning line from the log tail
        ui["print_success"].assert_called()

    def test_diagnostics_reports_export_failure(self):
        target = Path(self._tmp.name) / "report.txt"
        with mock.patch("music_fetch.tui.run_network_diagnostics", return_value=[]), mock.patch(
            "music_fetch.tui.read_log_tail", return_value=""
        ), mock.patch.object(Path, "write_text", side_effect=OSError("read-only")), offline_ui(
            confirm=True, ask=str(target)
        ) as ui:
            self.app._screen_diagnostics()
        ui["print_error"].assert_called()

    def test_diagnostics_export_can_be_declined(self):
        with mock.patch("music_fetch.tui.run_network_diagnostics", return_value=[]), mock.patch(
            "music_fetch.tui.read_log_tail", return_value=""
        ), offline_ui(confirm=False) as ui:
            self.app._screen_diagnostics()
        ui["ask"].assert_not_called()

    def test_update_check_reports_every_outcome(self):
        with mock.patch("music_fetch.tui.check_for_updates_cached", return_value=("9.9.9", "url")), offline_ui() as ui:
            self.app._screen_check_update()
        self.assertIn("发现新版本", str(ui["print_success"].call_args))

        with mock.patch("music_fetch.tui.check_for_updates_cached", return_value=("0.0.1", "url")), offline_ui() as ui:
            self.app._screen_check_update()
        self.assertIn("最新版本", str(ui["print_success"].call_args))

        with mock.patch(
            "music_fetch.tui.check_for_updates_cached", side_effect=RuntimeError("offline")
        ), offline_ui() as ui:
            self.app._screen_check_update()
        self.assertIn("无法检查更新", str(ui["print_warning"].call_args))


class OpenPathTests(TuiScreenTestCase):
    def test_missing_path_warns(self):
        with offline_ui() as ui:
            TuiApp._open_path(Path(self._tmp.name) / "nope")
        ui["print_warning"].assert_called()

    def test_posix_branches(self):
        target = Path(self._tmp.name) / "song.mp3"
        target.write_bytes(b"x")
        with mock.patch("music_fetch.tui.sys.platform", "linux"), mock.patch(
            "music_fetch.tui.subprocess.run"
        ) as run_mock:
            TuiApp._open_path(target)
        self.assertEqual(run_mock.call_args.args[0][0], "xdg-open")

        with mock.patch("music_fetch.tui.sys.platform", "darwin"), mock.patch(
            "music_fetch.tui.subprocess.run"
        ) as run_mock:
            TuiApp._open_path(target)
        self.assertEqual(run_mock.call_args.args[0][0], "open")

    def test_windows_branch_uses_startfile(self):
        # os.startfile only exists on Windows, hence create=True (this is the one
        # branch the rest of the suite never executes).
        target = Path(self._tmp.name) / "song.mp3"
        target.write_bytes(b"x")
        with mock.patch("music_fetch.tui.sys.platform", "win32"), mock.patch(
            "music_fetch.tui.os.startfile", create=True
        ) as startfile_mock:
            TuiApp._open_path(target)
        startfile_mock.assert_called_once_with(str(target))

    def test_failures_are_reported(self):
        target = Path(self._tmp.name) / "song.mp3"
        target.write_bytes(b"x")
        with mock.patch("music_fetch.tui.sys.platform", "linux"), mock.patch(
            "music_fetch.tui.subprocess.run", side_effect=OSError("no handler")
        ), offline_ui() as ui:
            TuiApp._open_path(target)
        ui["print_warning"].assert_called()


class SettingsScreenTests(TuiScreenTestCase):
    def test_each_editable_row_updates_the_session(self):
        def run(picks):
            with offline_ui(side_effect_menu=picks, ask="", ask_required="/tmp/out", ask_int=7):
                self.app._screen_settings()

        picks = iter([1, 2, 3, 4, 5, 6, 10])  # directory, timeouts, retries, concurrency, proxy, return
        with mock.patch.object(self.app, "_edit_proxy") as proxy_mock:
            run(lambda *args, **kwargs: next(picks))
            proxy_mock.assert_called_once()
        self.assertEqual(self.app.session.last_download_dir, "/tmp/out")
        self.assertEqual(self.app.session.detect_timeout_sec, 7)

    def test_saving_persists_the_settings(self):
        # Pick the *non-default* theme: choosing 深色 would equal DEFAULT_UI_THEME
        # and a dead theme branch would stay invisible.
        picks = iter([7, 2, 9])  # 界面主题 → 浅色, then 保存设置
        with offline_ui(side_effect_menu=lambda *args, **kwargs: next(picks)) as ui:
            self.app._screen_settings()
        self.assertEqual(self.session_store.load().ui_theme, "light")
        ui["print_success"].assert_called()
