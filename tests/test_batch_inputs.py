import unittest

from music_fetch.batch_inputs import collect_batch_candidates, dedupe_preserve_order, should_use_batch_mode, split_batch_input
from music_fetch.batch_inputs import contains_playlist_hint, looks_like_playlist_candidate
from music_fetch.batch_inputs import source_hint_map


class BatchInputTests(unittest.TestCase):
    def test_split_batch_input_supports_mixed_lines(self):
        raw = """
        https://music.163.com/song?id=1
        song id: 2
        分享文案 https://music.163.com/#/song?id=3 复制这段话
        """
        rows = split_batch_input(raw)
        self.assertEqual(
            rows,
            [
                "https://music.163.com/song?id=1",
                "song id: 2",
                "https://music.163.com/#/song?id=3",
            ],
        )

    def test_split_batch_input_extracts_multiple_urls_in_one_line(self):
        raw = "a https://music.163.com/song?id=1 b https://163cn.tv/abc"
        rows = split_batch_input(raw)
        self.assertEqual(rows, ["https://music.163.com/song?id=1", "https://163cn.tv/abc"])

    def test_split_batch_input_supports_semicolon_delimiter(self):
        raw = "12345；67890; https://music.163.com/song?id=2468"
        rows = split_batch_input(raw)
        self.assertEqual(rows, ["https://music.163.com/song?id=2468"])

    def test_split_batch_input_supports_semicolon_for_plain_ids(self):
        raw = "12345；67890;2468"
        rows = split_batch_input(raw)
        self.assertEqual(rows, ["12345", "67890", "2468"])

    def test_dedupe_preserve_order(self):
        rows = dedupe_preserve_order(
            [
                "https://music.163.com/song?id=1",
                "https://music.163.com/song?id=2",
                "https://music.163.com/song?id=1",
                "  ",
            ]
        )
        self.assertEqual(rows, ["https://music.163.com/song?id=1", "https://music.163.com/song?id=2"])

    def test_collect_batch_candidates(self):
        raw = """
        https://music.163.com/song?id=1
        https://music.163.com/song?id=1
        分享文案 https://music.163.com/song?id=2
        """
        rows = collect_batch_candidates(raw)
        self.assertEqual(rows, ["https://music.163.com/song?id=1", "https://music.163.com/song?id=2"])

    def test_should_use_batch_mode(self):
        self.assertFalse(should_use_batch_mode("https://music.163.com/song?id=1", min_count=3))
        self.assertTrue(
            should_use_batch_mode(
                "https://music.163.com/song?id=1\nhttps://music.163.com/song?id=2\nhttps://music.163.com/song?id=3",
                min_count=3,
            )
        )

    def test_playlist_hint_detection(self):
        self.assertTrue(looks_like_playlist_candidate("https://music.163.com/playlist?id=1"))
        self.assertTrue(contains_playlist_hint(["https://music.163.com/#/playlist?id=2"]))
        self.assertFalse(contains_playlist_hint(["https://music.163.com/song?id=3"]))

    def test_source_hint_map_playlist_share_text(self):
        raw = "分享唐烨QAQ的歌单《小老弟》https://163cn.tv/3S7kCzr (@网易云音乐)"
        hints = source_hint_map(raw)
        self.assertEqual(hints["https://163cn.tv/3S7kCzr"], "歌单-小老弟")

    def test_source_hint_map_song_share_text(self):
        raw = "分享张杰的单曲《这就是爱》https://163cn.tv/3TauDqq (@网易云音乐)"
        hints = source_hint_map(raw)
        self.assertEqual(hints["https://163cn.tv/3TauDqq"], "歌曲-这就是爱")

    def test_source_hint_map_mixed_share_text_in_single_line(self):
        raw = (
            "分享张杰的单曲《这就是爱》https://163cn.tv/3TauDqq (@网易云音乐)"
            "分享唐烨QAQ的歌单《银河快递永远的神》https://163cn.tv/3S9XUmn (@网易云音乐)"
        )
        hints = source_hint_map(raw)
        self.assertEqual(hints["https://163cn.tv/3TauDqq"], "歌曲-这就是爱")
        self.assertEqual(hints["https://163cn.tv/3S9XUmn"], "歌单-银河快递永远的神")


if __name__ == "__main__":
    unittest.main()
