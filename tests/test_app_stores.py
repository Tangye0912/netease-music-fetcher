import tempfile
import unittest
from pathlib import Path

from app_stores import AppSession, DownloadHistoryStore, DownloadRecord, SessionStore


class SessionStoreTests(unittest.TestCase):
    def test_load_default_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            store = SessionStore(path)
            session = store.load()
            self.assertEqual(session.cookie, "")
            self.assertTrue(session.remember_login)
            self.assertTrue(session.last_download_dir)

    def test_save_and_reload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "session.json"
            store = SessionStore(path)
            origin = AppSession(cookie="MUSIC_U=abc", remember_login=True, last_download_dir="/tmp/out")
            store.save(origin)
            loaded = store.load()
            self.assertEqual(loaded.cookie, "MUSIC_U=abc")
            self.assertEqual(loaded.last_download_dir, "/tmp/out")


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


if __name__ == "__main__":
    unittest.main()
