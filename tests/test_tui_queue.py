import threading
from unittest import mock

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from music_fetch.app_stores import DownloadHistoryStore, SessionStore
from music_fetch.batch_models import BatchDetectRow
from music_fetch.download_queue import DownloadRequest
from music_fetch.tui import MENU_QUIT, MENU_SEARCH, MENU_TASKS, TuiApp
import music_fetch.tui_utils as U


@pytest.fixture
def app(tmp_path):
    app = TuiApp(SessionStore(tmp_path / "session.json"), DownloadHistoryStore(tmp_path / "history.json"))
    app.session.cookie = "MUSIC_U=test"
    app.queue.set_cookie(app.session.cookie)
    with mock.patch("music_fetch.tui.U.print_info"), mock.patch("music_fetch.tui.U.print_header"), mock.patch(
        "music_fetch.tui.U.print_success"
    ), mock.patch("music_fetch.tui.U.clear_screen"), mock.patch("music_fetch.tui.U.print_warning"):
        yield app
    app.queue.close()
    assert app.queue.wait(2)


@pytest.mark.parametrize("lyric", [(False, "original"), (True, "original"), (True, "translation"), (True, "bilingual")])
def test_single_submits_immediately_and_keeps_options(app, tmp_path, lyric):
    with mock.patch.object(app, "_ask_with_cancel", side_effect=[str(tmp_path), "自选文件名"]), mock.patch.object(
        app, "_pick_format", return_value="flac"
    ), mock.patch.object(app, "_pick_lyric_mode", return_value=lyric):
        assert app._download_song("1", "song", artist="artist", album_name="album", cover_url="cover")
    (item,) = app.queue.snapshot()
    assert item.state == "pending"  # no foreground wait, no worker started by this screen
    assert item.output_path.name == "自选文件名.flac"
    assert item.request.target_format == "flac"
    assert (item.request.download_lyric, item.request.lyric_mode) == lyric
    assert item.request.artist == "artist" and item.request.cover_url == "cover"
    assert app.session_store.load().last_download_dir == str(tmp_path)
    assert not app.history_store.load()


def test_single_cancel_does_not_submit(app):
    with mock.patch.object(app, "_ask_with_cancel", return_value=None):
        assert not app._download_song("1", "song")
    assert not app.queue.snapshot()


def test_batch_submits_selected_rows_and_retains_export_context(app, tmp_path):
    rows = [BatchDetectRow("1", song_id="1", song_name="A", status="ready", selected=True),
            BatchDetectRow("2", song_id="2", song_name="B", status="ready", selected=True),
            BatchDetectRow("3", song_id="3", song_name="C", status="unavailable")]
    with mock.patch("music_fetch.tui.run_batch_detect", return_value=rows), mock.patch(
        "music_fetch.tui.U.menu", return_value=1
    ), mock.patch("music_fetch.tui.U.multiselect", return_value=[1]), mock.patch(
        "music_fetch.tui.U.print_table"
    ), mock.patch.object(app, "_ask_with_cancel", return_value=str(tmp_path)), mock.patch.object(
        app, "_pick_format", return_value="flac"
    ), mock.patch.object(app, "_pick_lyric_mode", return_value=(True, "translation")):
        app._batch_flow("album link")
    (item,) = app.queue.snapshot()
    assert item.request.song_id == "2" and item.request.lyric_mode == "translation"
    assert len(app._batches[0][0]) == 3
    assert app._batches[0][1] == {1: item.task_id}
    app.queue.cancel(item.task_id)
    with mock.patch("music_fetch.tui.U.menu", return_value=1), mock.patch.object(app, "_offer_batch_export") as export:
        app._export_queue_batch()
    exported = export.call_args.args[0]
    assert [r.status for r in exported] == ["ready", "download_canceled", "unavailable"]
    assert rows[1].status == "ready"  # export never mutates the original detection rows


def test_task_retry_updates_batch_export_to_latest_attempt(app, tmp_path):
    item = app.queue.enqueue(DownloadRequest("1", "song", tmp_path / "song.mp3", lyric_mode="bilingual"))
    app._batches = [([BatchDetectRow("1", song_id="1")], {0: item.task_id})]
    app.queue.cancel(item.task_id)
    app._retry_task(item.task_id)
    assert app._batches[0][1][0] == app.queue.snapshot()[1].task_id
    assert app.queue.snapshot()[1].request.lyric_mode == "bilingual"


def test_history_retry_keeps_record_until_background_result(app, tmp_path):
    app._add_record("1", "song", str(tmp_path / "song.flac"), 0, "failed", "NETWORK_ERROR")
    record = app.history_store.load()[0]
    assert app._retry_record(record)
    assert app.history_store.load()[0].status == "failed"
    assert app.queue.snapshot()[0].request.target_format == "flac"


def test_main_menu_can_search_after_submission_and_quit_can_be_declined(app, tmp_path):
    app.queue.enqueue(DownloadRequest("1", "song", tmp_path / "song.mp3"))
    app.queue.pause_all()
    labels = iter([MENU_SEARCH, MENU_QUIT, MENU_QUIT])

    def pick(title, options, **kwargs):
        assert MENU_TASKS in options
        return options.index(next(labels)) + 1

    with mock.patch("music_fetch.tui.fetch_account_profile", return_value=mock.Mock(nickname="测")), mock.patch(
        "music_fetch.tui.U.menu", side_effect=pick
    ), mock.patch.object(app, "_screen_search") as search, mock.patch(
        "music_fetch.tui.U.confirm", side_effect=[False, True]
    ), mock.patch("music_fetch.tui.U.print_status"):
        assert app.run() == 0
    search.assert_called_once()
    assert app.queue.snapshot()[0].state == "canceled"


def test_task_page_accessible_when_logged_out(app, tmp_path):
    app._clear_login()
    app.queue.enqueue(DownloadRequest("1", "song", tmp_path / "song.mp3"))
    labels = iter([MENU_TASKS, MENU_QUIT])

    def pick(title, options, **kwargs):
        return options.index(next(labels)) + 1

    with mock.patch.object(app, "_screen_login"), mock.patch.object(app, "_screen_tasks") as tasks, mock.patch(
        "music_fetch.tui.U.menu", side_effect=pick
    ), mock.patch("music_fetch.tui.U.confirm", return_value=True):
        assert app.run() == 0
    tasks.assert_called_once()


def test_task_page_paging_pause_resume_cancel(app, tmp_path):
    for i in range(1, 11):
        app.queue.enqueue(DownloadRequest(str(i), "song", tmp_path / f"{i}.mp3"))
    rendered = []
    inputs = iter(["P", "R", "n", "9", "c", "0"])

    def fake_live_ask(render, prompt_text=""):
        rendered.append(render())  # evaluate now, like the real 0.5s refresh
        return next(inputs)

    with mock.patch("music_fetch.tui.U.live_ask", side_effect=fake_live_ask), mock.patch(
        "music_fetch.tui.U.print_warning"
    ), mock.patch.object(app, "_task_actions") as actions, mock.patch(
        "music_fetch.tui.U.confirm", return_value=True
    ):
        app._screen_tasks()
    # First render, before any key: page 1 of 2 with 8 pending rows.
    assert "第 1/2 页" in rendered[0]
    assert rendered[0].count("等待中") == 8
    # After n: page 2 with the remaining 2 rows.
    assert "第 2/2 页" in rendered[3]
    assert rendered[3].count("等待中") == 2
    assert actions.call_args.args[0].request.song_id == "9"
    assert {i.state for i in app.queue.snapshot()} == {"canceled"}


def test_task_page_screen_renders_live_snapshot(app, tmp_path):
    app.queue.enqueue(DownloadRequest("1", "歌一", tmp_path / "1.mp3"))
    text = app._render_task_screen(0, False)
    assert "歌一" in text
    assert "等待中" in text
    assert "第 1/1 页" in text
    # Empty queue renders the placeholder instead of a table.
    app.queue.cancel_all()
    text = app._render_task_screen(0, False)
    assert "已取消" in text


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_interrupted_subscreen_still_shuts_down_queue(app, tmp_path, error):
    app.queue.enqueue(DownloadRequest("1", "song", tmp_path / "song.mp3"))
    app.queue.pause_all()
    with mock.patch("music_fetch.tui.fetch_account_profile", return_value=mock.Mock(nickname="测")), mock.patch(
        "music_fetch.tui.U.menu", side_effect=error
    ), mock.patch("music_fetch.tui.U.print_status"):
        assert app.run() == 0
    assert app.queue.snapshot()[0].state == "canceled"


def test_status_provider_refreshes_during_real_input_and_preserves_typed_text():
    # A real prompt_toolkit event loop, not a mocked prompt. The status must
    # refresh before Enter while the input buffer contains a half-typed query.
    refreshed = threading.Event()
    completed = threading.Event()
    calls = []
    failures = []

    def provider():
        calls.append(1)
        if completed.is_set():
            refreshed.set()
        return "已完成 1" if completed.is_set() else "下载中 1"

    # CI shells use TERM=dumb, which intentionally disables toolbar rendering.
    with mock.patch.dict("os.environ", {"TERM": "xterm-256color"}), create_pipe_input() as pipe, create_app_session(
        input=pipe, output=DummyOutput()
    ):
        def type_input():
            pipe.send_text("下一")
            completed.wait(0.7)
            completed.set()
            if not refreshed.wait(3):
                failures.append("toolbar did not refresh while waiting for input")
            pipe.send_text("首\n")

        worker = threading.Thread(target=type_input)
        worker.start()
        try:
            with U.background_status(provider):
                result = U.ask("搜索")
        finally:
            pipe.send_text("\x04")
            worker.join(4)
    assert not failures
    assert result == "下一首"
    assert len(calls) >= 2
    assert U._status_toolbar()[0][1] == ""


def test_batch_summary_keeps_failures_and_reason_counts(app, tmp_path):
    app._batches = [([
        BatchDetectRow("1", song_id="1", status="download_failed", message="网络中断"),
        BatchDetectRow("2", song_id="2", status="download_failed", message="网络中断"),
        BatchDetectRow("3", song_id="3", status="download_success"),
    ], {})]
    with mock.patch("music_fetch.tui.U.menu", return_value=1), mock.patch.object(
        app, "_offer_batch_export"
    ), mock.patch("music_fetch.tui.U.print_panel") as panel:
        app._export_queue_batch()
    assert ("成功", "1") in panel.call_args.args[1]
    assert ("失败", "2") in panel.call_args.args[1]
    assert ("失败原因", "2 首：网络中断") in panel.call_args.args[1]


@pytest.mark.parametrize("action, state", [("暂停", "paused"), ("取消任务", "canceled")])
def test_task_details_apply_controls(app, tmp_path, action, state):
    item = app.queue.enqueue(DownloadRequest("1", "song", tmp_path / "song.mp3"))
    with mock.patch("music_fetch.tui.U.print_panel"), mock.patch(
        "music_fetch.tui.U.menu", side_effect=lambda title, options: options.index(action) + 1
    ):
        app._task_actions(item)
    assert app.queue.snapshot()[0].state == state


def test_task_page_retry_failed_requires_confirmation(app, tmp_path):
    for i, state in enumerate(("failed", "failed", "canceled", "success")):
        app.queue.enqueue(DownloadRequest(str(i), "song", tmp_path / f"{i}.mp3"))
        app.queue._items[-1].state = state  # white-box: skip real job runs
    with mock.patch("music_fetch.tui.U.live_ask", side_effect=["f", "0"]), mock.patch(
        "music_fetch.tui.U.confirm", return_value=False
    ) as confirm_mock, mock.patch.object(app, "_retry_task") as retry_mock:
        app._screen_tasks()
    # Declined confirmation: nothing is retried, prompt loop continues.
    confirm_mock.assert_called_once()
    assert "2 个失败任务" in confirm_mock.call_args.args[0]
    assert retry_mock.call_count == 0

    with mock.patch("music_fetch.tui.U.live_ask", side_effect=["f", "0"]), mock.patch(
        "music_fetch.tui.U.confirm", return_value=True
    ), mock.patch.object(app, "_retry_task") as retry_mock:
        app._screen_tasks()
    assert retry_mock.call_count == 2
    retried_ids = {call.args[0] for call in retry_mock.call_args_list}
    assert len(retried_ids) == 2  # only the two failed tasks, not canceled/success


def test_task_page_retry_failed_without_failures_warns(app, tmp_path):
    app.queue.enqueue(DownloadRequest("1", "song", tmp_path / "1.mp3"))
    with mock.patch("music_fetch.tui.U.live_ask", side_effect=["f", "0"]), mock.patch(
        "music_fetch.tui.U.print_warning"
    ) as warning_mock, mock.patch.object(app, "_retry_task") as retry_mock:
        app._screen_tasks()
    warning_mock.assert_called_once_with("没有失败的任务。")
    assert retry_mock.call_count == 0
