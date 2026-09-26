import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from music_fetch.app_stores import AppSession, DownloadHistoryStore, DownloadRecord, QueueStore, SessionStore
from music_fetch.app_settings import (
    DEFAULT_DETECT_TIMEOUT_SEC,
    DEFAULT_DOWNLOAD_CONCURRENCY,
    DEFAULT_DOWNLOAD_RETRY_COUNT,
    DEFAULT_DOWNLOAD_TIMEOUT_SEC,
    MAX_DETECT_TIMEOUT_SEC,
    MAX_DOWNLOAD_RETRY_COUNT,
    MAX_DOWNLOAD_TIMEOUT_SEC,
    MAX_UI_CONCURRENCY,
    MIN_DETECT_TIMEOUT_SEC,
    MIN_DOWNLOAD_CONCURRENCY,
    MIN_DOWNLOAD_RETRY_COUNT,
    MIN_DOWNLOAD_TIMEOUT_SEC,
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
            self.assertEqual(session.detect_timeout_sec, DEFAULT_DETECT_TIMEOUT_SEC)
            self.assertEqual(session.download_timeout_sec, DEFAULT_DOWNLOAD_TIMEOUT_SEC)
            self.assertEqual(session.download_retry_count, DEFAULT_DOWNLOAD_RETRY_COUNT)
            self.assertEqual(session.download_concurrency, DEFAULT_DOWNLOAD_CONCURRENCY)
            self.assertEqual(session.ui_theme, "dark")

    def test_save_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            store = SessionStore(path)
            origin = AppSession(
                cookie="MUSIC_U=abc",
                remember_login=True,
                last_download_dir="/tmp/out",
                detect_timeout_sec=3,
                download_timeout_sec=10,
                download_retry_count=2,
                download_concurrency=1,
                ui_theme="light",
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
            self.assertEqual(loaded.detect_timeout_sec, 3)
            self.assertEqual(loaded.download_timeout_sec, 10)
            self.assertEqual(loaded.download_retry_count, 2)
            self.assertEqual(loaded.download_concurrency, 1)
            self.assertEqual(loaded.ui_theme, "light")
            self.assertEqual(loaded.proxy_type, "socks5")
            self.assertEqual(loaded.proxy_host, "127.0.0.1")
            self.assertEqual(loaded.proxy_port, 1080)
            self.assertEqual(loaded.proxy_username, "proxy-user")
            self.assertEqual(loaded.proxy_password, "proxy-secret")

    @unittest.skipIf(os.name == "nt", "POSIX permission bits are not enforced on Windows")
    def test_session_file_is_private_after_each_save(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            path.write_text("{}", encoding="utf-8")
            path.chmod(0o644)

            store = SessionStore(path)
            store.save(AppSession(cookie="MUSIC_U=secret", proxy_password="proxy-secret"))

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_atomic_save_failure_preserves_previous_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            path.write_text('{"cookie":"MUSIC_U=old"}', encoding="utf-8")
            with mock.patch("music_fetch.app_stores.os.replace", side_effect=OSError("replace failed")):
                with self.assertRaises(OSError):
                    SessionStore(path).save(AppSession(cookie="MUSIC_U=new"))

            self.assertEqual(path.read_text(encoding="utf-8"), '{"cookie":"MUSIC_U=old"}')
            self.assertEqual(list(path.parent.glob(f".{path.name}.*.tmp")), [])

    def test_legacy_font_and_geometry_keys_are_ignored(self):
        """Qt-era session keys must not break loading after their removal."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            path.write_text('{"ui_font_size": 999, "window_geometry": "10,10,800,600"}', encoding="utf-8")
            store = SessionStore(path)
            loaded = store.load()
            self.assertEqual(loaded.ui_theme, "dark")
            self.assertFalse(hasattr(loaded, "ui_font_size"))
            self.assertFalse(hasattr(loaded, "window_geometry"))

    def test_existing_file_policy_round_trip_and_clamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            store = SessionStore(path)
            self.assertEqual(store.load().existing_file_policy, "rename")  # default
            store.save(AppSession(existing_file_policy="overwrite"))
            self.assertEqual(store.load().existing_file_policy, "overwrite")
            path.write_text('{"existing_file_policy": "bogus"}', encoding="utf-8")
            self.assertEqual(store.load().existing_file_policy, "rename")

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
            self.assertEqual(loaded.download_concurrency, MAX_UI_CONCURRENCY)

    def test_concurrency_above_the_ui_ceiling_is_clamped_for_persistence(self):
        # The settings screen offers 1..MAX_UI_CONCURRENCY and the queue honours
        # it, so a saved 8 must survive a reload instead of reverting to 3.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            store = SessionStore(path)
            store.save(AppSession(download_concurrency=MAX_UI_CONCURRENCY))
            self.assertEqual(store.load().download_concurrency, MAX_UI_CONCURRENCY)

            store.save(AppSession(download_concurrency=99))
            self.assertEqual(store.load().download_concurrency, MAX_UI_CONCURRENCY)

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

    def test_invalid_theme_falls_back_to_dark(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            path.write_text('{"ui_theme":"neon"}', encoding="utf-8")
            self.assertEqual(SessionStore(path).load().ui_theme, "dark")


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

    def test_invalid_status_falls_back_to_failed(self):
        """An unknown status must never be reported as a successful download."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "downloads.json"
            path.write_text(
                '[{"song_id":"1","song_name":"track","output_path":"/tmp/track.mp3","size_bytes":0,"downloaded_at":"2026-01-01 00:00:00","status":"bad"}]',
                encoding="utf-8",
            )
            store = DownloadHistoryStore(path)
            rows = store.load()
            self.assertEqual(rows[0].status, TASK_STATE_FAILED)

    def test_legacy_status_strings_are_not_treated_as_success(self):
        """Old writers used spellings we no longer emit (error/cancelled/...)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "downloads.json"
            path.write_text(
                '[{"song_id":"1","song_name":"a","output_path":"/tmp/a.mp3","status":"error"},'
                '{"song_id":"2","song_name":"b","output_path":"/tmp/b.mp3","status":"cancelled"},'
                '{"song_id":"3","song_name":"c","output_path":"/tmp/c.mp3","status":"success"}]',
                encoding="utf-8",
            )
            store = DownloadHistoryStore(path)
            rows = store.load()
            self.assertEqual([row.status for row in rows],
                             [TASK_STATE_FAILED, TASK_STATE_FAILED, TASK_STATE_SUCCESS])

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

    def test_appends_from_a_second_instance_are_not_dropped(self):
        # Two running instances share one history file; the second writer used
        # to rewrite from its own stale cache and lose the other's rows.
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "downloads.json"
            first = DownloadHistoryStore(path)
            second = DownloadHistoryStore(path)

            first.add(DownloadRecord("1", "a", "/tmp/a.mp3", 1, "2026-07-19 00:00:00"))
            second.add(DownloadRecord("2", "b", "/tmp/b.mp3", 1, "2026-07-19 00:00:01"))
            first.add(DownloadRecord("3", "c", "/tmp/c.mp3", 1, "2026-07-19 00:00:02"))

            reloaded = DownloadHistoryStore(path).load()
            self.assertEqual({row.song_id for row in reloaded}, {"1", "2", "3"})


class QueueStoreQuarantineTests(unittest.TestCase):
    def test_corrupt_queue_file_is_moved_aside_not_discarded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queue.json"
            path.write_text("{not json", encoding="utf-8")
            store = QueueStore(path)

            self.assertEqual(store.load(), [])
            backup = path.with_name("queue.json.corrupt")
            self.assertTrue(backup.exists())
            self.assertEqual(backup.read_text(encoding="utf-8"), "{not json")

    def test_non_list_payload_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queue.json"
            path.write_text('{"unexpected": "schema"}', encoding="utf-8")
            store = QueueStore(path)

            self.assertEqual(store.load(), [])
            self.assertTrue(path.with_name("queue.json.corrupt").exists())


class DownloadHistoryDurabilityTests(unittest.TestCase):
    """The history file must survive a crash mid-write (torn JSON)."""

    def _store(self, tmp):
        return DownloadHistoryStore(Path(tmp) / "downloads.json")

    def _record(self, song_id: str) -> DownloadRecord:
        return DownloadRecord(
            song_id=song_id, song_name=f"Song {song_id}",
            output_path=f"/tmp/{song_id}.mp3", size_bytes=10,
            downloaded_at="2026-01-01 00:00:00",
        )

    def test_save_replaces_the_file_atomically(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = self._store(tmp)
            with mock.patch("music_fetch.app_stores.os.replace", wraps=os.replace) as replace:
                store.save([self._record("1"), self._record("2")])
            replace.assert_called_once()
            self.assertEqual(len(store.load()), 2)

    def test_torn_file_is_quarantined_and_the_history_keeps_appending(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "downloads.json"
            store = DownloadHistoryStore(path)
            for index in range(3):
                store.add(self._record(str(index)))
            raw = path.read_text(encoding="utf-8")

            path.write_text(raw[: len(raw) // 2], encoding="utf-8")  # crash mid-write
            reopened = DownloadHistoryStore(path)
            self.assertEqual(reopened.load(), [])

            backup = path.with_name("downloads.json.corrupt")
            self.assertTrue(backup.exists(), "torn history must be kept for recovery")
            self.assertEqual(backup.read_text(encoding="utf-8"), raw[: len(raw) // 2])

            reopened.add(self._record("new"))
            self.assertEqual([record.song_id for record in reopened.load()], ["new"])

    def test_non_list_payload_is_quarantined(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "downloads.json"
            path.write_text('{"unexpected": "schema"}', encoding="utf-8")
            store = DownloadHistoryStore(path)
            self.assertEqual(store.load(), [])
            self.assertTrue(path.with_name("downloads.json.corrupt").exists())


class SessionStoreRobustnessTests(unittest.TestCase):
    def test_wrong_json_shape_falls_back_to_defaults(self):
        for payload in ("[]", "null", "123", '"x"'):
            with self.subTest(payload=payload), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "session.json"
                path.write_text(payload, encoding="utf-8")
                session = SessionStore(path).load()
                self.assertEqual(session.cookie, "")
                self.assertEqual(session.download_concurrency, DEFAULT_DOWNLOAD_CONCURRENCY)

    def test_json_infinity_does_not_crash_the_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            path.write_text('{"detect_timeout_sec": 1e999, "download_retry_count": 1e999}', encoding="utf-8")
            session = SessionStore(path).load()
            self.assertEqual(session.detect_timeout_sec, DEFAULT_DETECT_TIMEOUT_SEC)
            self.assertEqual(session.download_retry_count, DEFAULT_DOWNLOAD_RETRY_COUNT)

    def test_json_infinity_in_history_size_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "downloads.json"
            path.write_text('[{"song_id": "1", "song_name": "x", "size_bytes": 1e999}]', encoding="utf-8")
            records = DownloadHistoryStore(path).load()
            self.assertEqual(records[0].size_bytes, 0)


if __name__ == "__main__":
    unittest.main()
