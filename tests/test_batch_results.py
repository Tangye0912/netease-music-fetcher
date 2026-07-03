import csv
import io
import unittest

from _batch_results import (
    BATCH_CSV_FIELDS,
    UNKNOWN_FAILURE_REASON,
    build_batch_results_csv,
    retryable_failed_rows,
    summarize_batch_rows,
)
from _batch_models import BatchDetectRow


class BatchResultsTests(unittest.TestCase):
    def _row(self, status: str, message: str = "", selected: bool = False) -> BatchDetectRow:
        return BatchDetectRow(
            raw_input="https://music.163.com/song?id=1",
            source_type="song",
            source_label="歌曲-测试",
            song_id="1",
            song_name="测试,歌曲",
            status=status,
            message=message,
            media_size_bytes=123,
            selected=selected,
        )

    def test_retryable_failed_rows_only_returns_download_failed(self):
        rows = [
            self._row("download_failed"),
            self._row("failed"),
            self._row("unavailable"),
            self._row("duplicate"),
            self._row("download_canceled"),
            self._row("download_success"),
        ]
        self.assertEqual(retryable_failed_rows(rows), [rows[0]])

    def test_summarize_batch_rows_counts_statuses_and_reasons(self):
        rows = [
            self._row("ready"),
            self._row("duplicate"),
            self._row("failed"),
            self._row("unavailable"),
            self._row("download_success"),
            self._row("download_failed", "NETWORK_ERROR: timeout"),
            self._row("download_failed", "NETWORK_ERROR: timeout"),
            self._row("download_failed"),
            self._row("download_canceled"),
        ]
        summary = summarize_batch_rows(rows)
        self.assertEqual(summary.total, 9)
        self.assertEqual(summary.ready, 1)
        self.assertEqual(summary.duplicate, 1)
        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.unavailable, 1)
        self.assertEqual(summary.download_success, 1)
        self.assertEqual(summary.download_failed, 3)
        self.assertEqual(summary.download_canceled, 1)
        self.assertEqual(summary.failure_reasons["NETWORK_ERROR: timeout"], 2)
        self.assertEqual(summary.failure_reasons[UNKNOWN_FAILURE_REASON], 1)

    def test_build_batch_results_csv_uses_fixed_header_and_escapes_fields(self):
        rows = [self._row("download_failed", "错误,换行\n详情", selected=True)]
        csv_text = build_batch_results_csv(rows)
        parsed = list(csv.DictReader(io.StringIO(csv_text)))
        self.assertEqual(csv_text.splitlines()[0].split(","), list(BATCH_CSV_FIELDS))
        self.assertEqual(parsed[0]["song_name"], "测试,歌曲")
        self.assertEqual(parsed[0]["status_text"], "下载失败")
        self.assertEqual(parsed[0]["message"], "错误,换行\n详情")
        self.assertEqual(parsed[0]["selected"], "true")


if __name__ == "__main__":
    unittest.main()
