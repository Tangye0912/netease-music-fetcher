import unittest

import music_fetch.ui_texts as T


class UiTextsTests(unittest.TestCase):
    def test_batch_source_text_song(self):
        self.assertEqual(T.batch_source_text("song"), T.BATCH_SOURCE_SONG)

    def test_batch_source_text_playlist_case_insensitive(self):
        self.assertEqual(T.batch_source_text("PLAYLIST"), T.BATCH_SOURCE_PLAYLIST)

    def test_batch_source_text_unknown_fallback(self):
        self.assertEqual(T.batch_source_text("other"), T.BATCH_SOURCE_UNKNOWN)


if __name__ == "__main__":
    unittest.main()
