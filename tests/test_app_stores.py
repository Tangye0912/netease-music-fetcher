import tempfile
import unittest
from pathlib import Path

from music_fetch.app_stores import AppSession, DownloadHistoryStore, DownloadRecord, SessionStore
from music_fetch.app_settings import (
    DEFAULT_DETECT_TIMEOUT_SEC,
    DEFAULT_DOWNLOAD_CONCURRENCY,
    DEFAULT_DOWNLOAD_RETRY_COUNT,
    DEFAULT_DOWNLOAD_TIMEOUT_SEC,
    DEFAULT_UI_FONT_SIZE,
    MAX_DETECT_TIMEOUT_SEC,
    MAX_DOWNLOAD_CONCURRENCY,
    MAX_DOWNLOAD_RETRY_COUNT,
    MAX_DOWNLOAD_TIMEOUT_SEC,
    MAX_UI_FONT_SIZE,
    MIN_DETECT_TIMEOUT_SEC,
    MIN_DOWNLOAD_CONCURRENCY,
    MIN_DOWNLOAD_RETRY_COUNT,
    MIN_DOWNLOAD_TIMEOUT_SEC,
    MIN_UI_FONT_SIZE,
)
from music_fetch.download_tasks import TASK_STATE_FAILED, TASK_STATE_SUCCESS


class SessionStoreTests(unittest.TestCase):
    def test_load_default_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            store = SessionStore(path)
            session = store.load()
            self.assertEqual(session.cookie, "")
            self.assertTrue(session.remember_login)
            self.assertTrue(session.last_download_dir)
            self.assertEqual(session.ui_font_size, DEFAULT_UI_FONT_SIZE)
            self.assertEqual(session.detect_timeout_sec, DEFAULT_DETECT_TIMEOUT_SEC)
            self.assertEqual(session.download_timeout_sec, DEFAULT_DOWNLOAD_TIMEOUT_SEC)
            self.assertEqual(session.download_retry_count, DEFAULT_DOWNLOAD_RETRY_COUNT)
            self.assertEqual(session.download_concurrency, DEFAULT_DOWNLOAD_CONCURRENCY)

    def test_save_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            store = SessionStore(path)
            origin = AppSession(
                cookie="MUSIC_U=abc",
                remember_login=True,
                last_download_dir="/tmp/out",
                ui_font_size=18,
                detect_timeout_sec=3,
                download_timeout_sec=10,
                download_retry_count=2,
                download_concurrency=1,
                proxy_type="socks5",
                proxy_host="127.0.0.1",
                proxy_port=1080,
                proxy_username="proxy-user",
                proxy_password="proxy-secret",
            )
            store.save(origin)
            loaded = store.load()
            self.assertEqual(loaded.cookie, "MUSIC_U=abc")
            self.assertEqual(loaded.last_download_dir, "/tmp/out")
            self.assertEqual(loaded.ui_font_size, 18)
            self.assertEqual(loaded.detect_timeout_sec, 3)
            self.assertEqual(loaded.download_timeout_sec, 10)
            self.assertEqual(loaded.download_retry_count, 2)
            self.assertEqual(loaded.download_concurrency, 1)
            self.assertEqual(loaded.proxy_type, "socks5")
            self.assertEqual(loaded.proxy_host, "127.0.0.1")
            self.assertEqual(loaded.proxy_port, 1080)
            self.assertEqual(loaded.proxy_username, "proxy-user")
            self.assertEqual(loaded.proxy_password, "proxy-secret")

    def test_font_size_is_clamped_on_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            path.write_text('{"ui_font_size": 999}', encoding="utf-8")
            store = SessionStore(path)
            loaded = store.load()
            self.assertEqual(loaded.ui_font_size, MAX_UI_FONT_SIZE)

            path.write_text('{"ui_font_size": 1}', encoding="utf-8")
            loaded = store.load()
            self.assertEqual(loaded.ui_font_size, MIN_UI_FONT_SIZE)

    def test_download_settings_are_clamped_on_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            path.write_text(
                '{"detect_timeout_sec": 999, "download_timeout_sec": 1, "download_retry_count": 99, "download_concurrency": 0}',
                encoding="utf-8",
            )
            store = SessionStore(path)
            loaded = store.load()
            self.assertEqual(loaded.detect_timeout_sec, MAX_DETECT_TIMEOUT_SEC)
            self.assertEqual(loaded.download_timeout_sec, MIN_DOWNLOAD_TIMEOUT_SEC)
            self.assertEqual(loaded.download_retry_count, MAX_DOWNLOAD_RETRY_COUNT)
            self.assertEqual(loaded.download_concurrency, MIN_DOWNLOAD_CONCURRENCY)

            path.write_text(
                '{"detect_timeout_sec": 1, "download_timeout_sec": 999, "download_retry_count": -1, "download_concurrency": 99}',
                encoding="utf-8",
            )
            loaded = store.load()
            self.assertEqual(loaded.detect_timeout_sec, MIN_DETECT_TIMEOUT_SEC)
            self.assertEqual(loaded.download_timeout_sec, MAX_DOWNLOAD_TIMEOUT_SEC)
            self.assertEqual(loaded.download_retry_count, MIN_DOWNLOAD_RETRY_COUNT)
            self.assertEqual(loaded.download_concurrency, MAX_DOWNLOAD_CONCURRENCY)

    def test_invalid_proxy_settings_are_sanitized_on_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            path.write_text(
                '{"proxy_type":"ftp","proxy_host":" proxy.local ","proxy_port":70000,"proxy_username":" user "}',
                encoding="utf-8",
            )
            loaded = SessionStore(path).load()
            self.assertEqual(loaded.proxy_type, "")
            self.assertEqual(loaded.proxy_host, "proxy.local")
            self.assertEqual(loaded.proxy_port, 0)
            self.assertEqual(loaded.proxy_username, "user")


class DownloadHistoryStoreTests(unittest.TestCase):
    def test_add_and_remove_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "downloads.json"
            store = DownloadHistoryStore(path)
            record = DownloadRecord(
                song_id="1",
                song_name="track",
                output_path="/tmp/track.mp3",
                size_bytes=100,
                downloaded_at="2026-01-01 00:00:00",
            )
            store.add(record)
            loaded = store.load()
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].song_name, "track")

            store.remove_by_path("/tmp/track.mp3")
            self.assertEqual(store.load(), [])

    def test_load_backward_compatible_without_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "downloads.json"
            path.write_text(
                '[{"song_id":"1","song_name":"track","output_path":"/tmp/track.mp3","size_bytes":123,"downloaded_at":"2026-01-01 00:00:00"}]',
                encoding="utf-8",
            )
            store = DownloadHistoryStore(path)
            rows = store.load()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, TASK_STATE_SUCCESS)

    def test_save_and_reload_status_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "downloads.json"
            store = DownloadHistoryStore(path)
            store.add(
                DownloadRecord(
                    song_id="1",
                    song_name="track",
                    output_path="/tmp/track.mp3",
                    size_bytes=0,
                    downloaded_at="2026-01-01 00:00:00",
                    status=TASK_STATE_FAILED,
                    error_code="NETWORK_ERROR",
                )
            )
            rows = store.load()
            self.assertEqual(rows[0].status, TASK_STATE_FAILED)
            self.assertEqual(rows[0].error_code, "NETWORK_ERROR")

    def test_invalid_status_fallback_to_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "downloads.json"
            path.write_text(
                '[{"song_id":"1","song_name":"track","output_path":"/tmp/track.mp3","size_bytes":0,"downloaded_at":"2026-01-01 00:00:00","status":"bad"}]',
                encoding="utf-8",
            )
            store = DownloadHistoryStore(path)
            rows = store.load()
            self.assertEqual(rows[0].status, TASK_STATE_SUCCESS)

    def test_save_caps_cache_and_file_to_latest_thousand_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "downloads.json"
            store = DownloadHistoryStore(path)
            records = [
                DownloadRecord(
                    song_id=str(index),
                    song_name=f"track-{index}",
                    output_path=f"/tmp/track-{index}.mp3",
                    size_bytes=index,
                    downloaded_at="2026-07-19 00:00:00",
                )
                for index in range(1005)
            ]

            store.save(records)

            self.assertEqual(len(store.load()), 1000)
            self.assertEqual(store.load()[0].song_id, "0")
            reloaded = DownloadHistoryStore(path).load()
            self.assertEqual(len(reloaded), 1000)
            self.assertEqual(reloaded[-1].song_id, "999")

            store.add(
                DownloadRecord(
                    song_id="new",
                    song_name="newest-track",
                    output_path="/tmp/newest-track.mp3",
                    size_bytes=1,
                    downloaded_at="2026-07-19 00:01:00",
                )
            )
            self.assertEqual(len(store.load()), 1000)
            self.assertEqual(store.load()[0].song_id, "new")
            self.assertEqual(store.load()[-1].song_id, "998")


if __name__ == "__main__":
    unittest.main()
