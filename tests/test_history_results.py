import csv
import io
import unittest

from music_fetch.app_stores import DownloadRecord
from music_fetch.history_results import (
    HISTORY_CSV_FIELDS,
    build_download_history_csv,
    filter_download_history,
)


def _record(
    song_id: str,
    song_name: str,
    output_path: str,
    status: str = "success",
    error_code: str = "",
) -> DownloadRecord:
    return DownloadRecord(
        song_id=song_id,
        song_name=song_name,
        output_path=output_path,
        size_bytes=123,
        downloaded_at="2026-07-19 16:00:00",
        status=status,
        error_code=error_code,
    )


class HistoryFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.records = [
            _record("1", "Hello World", "/tmp/hello-live.mp3"),
            _record("2", "夜曲", "/tmp/nocturne.flac", "failed", "NETWORK_ERROR"),
            _record("42", "Another Song", "/music/archive/target.m4a", "canceled"),
        ]

    def test_blank_query_preserves_order(self):
        self.assertEqual(filter_download_history(self.records), self.records)

    def test_status_and_query_are_combined(self):
        result = filter_download_history(
            self.records,
            status_filter="failed",
            query="夜曲 network_error",
        )
        self.assertEqual(result, [self.records[1]])

    def test_query_matches_id_filename_path_and_localized_status(self):
        self.assertEqual(filter_download_history(self.records, query="42 target"), [self.records[2]])
        self.assertEqual(filter_download_history(self.records, query="NOCTURNE"), [self.records[1]])
        self.assertEqual(filter_download_history(self.records, query="已取消"), [self.records[2]])


class HistoryCsvTests(unittest.TestCase):
    def test_csv_uses_fixed_fields_and_escapes_newlines_and_commas(self):
        record = _record("1", "测试,歌曲\n现场", "/tmp/test.mp3", "failed", "NETWORK,ERROR")
        csv_text = build_download_history_csv([record])
        parsed = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual(csv_text.splitlines()[0].split(","), list(HISTORY_CSV_FIELDS))
        self.assertEqual(parsed[0]["song_name"], "测试,歌曲\n现场")
        self.assertEqual(parsed[0]["status_text"], "失败")
        self.assertEqual(parsed[0]["error_code"], "NETWORK,ERROR")

    def test_csv_neutralizes_spreadsheet_formulas(self):
        records = [
            _record(" =1+1", "+SUM(A1:A2)", "/tmp/@payload.mp3", error_code="-cmd")
        ]
        parsed = list(csv.DictReader(io.StringIO(build_download_history_csv(records))))[0]
        self.assertEqual(parsed["song_id"], "' =1+1")
        self.assertEqual(parsed["song_name"], "'+SUM(A1:A2)")
        self.assertEqual(parsed["filename"], "'@payload.mp3")
        self.assertEqual(parsed["error_code"], "'-cmd")


if __name__ == "__main__":
    unittest.main()
