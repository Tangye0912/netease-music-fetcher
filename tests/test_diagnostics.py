import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from urllib import error
from unittest import mock

from music_fetch.diagnostics import (
    DiagnosticContext,
    EndpointProbe,
    build_diagnostic_report,
    probe_endpoint,
    read_log_tail,
    redact_diagnostic_text,
    run_network_diagnostics,
)


class LogDiagnosticsTests(unittest.TestCase):
    def test_read_log_tail_handles_missing_and_limits_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "music-fetch.log"
            self.assertEqual(read_log_tail(path), "")
            path.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
            self.assertEqual(read_log_tail(path, max_lines=2), "three\nfour")

    def test_redaction_removes_cookie_and_proxy_credentials(self):
        text = (
            "MUSIC_U=secret-token password:plain-secret "
            "proxy=http://user:pass@proxy.local:8080"
        )
        redacted = redact_diagnostic_text(text, ("plain-secret",))
        self.assertNotIn("secret-token", redacted)
        self.assertNotIn("plain-secret", redacted)
        self.assertNotIn("user:pass", redacted)
        self.assertIn("MUSIC_U=***", redacted)


class NetworkProbeTests(unittest.TestCase):
    def test_successful_response_is_reachable(self):
        response = mock.MagicMock()
        response.status = 204
        response.getcode.return_value = 204
        response.__enter__.return_value = response
        with mock.patch("music_fetch.diagnostics.open_url", return_value=response):
            result = probe_endpoint("API", "https://example.test", timeout=3)
        self.assertTrue(result.reachable)
        self.assertEqual(result.status_code, 204)
        response.read.assert_called_once_with(1)

    def test_http_error_still_proves_endpoint_is_reachable(self):
        http_error = error.HTTPError(
            "https://example.test", 403, "Forbidden", {}, None,
        )
        with mock.patch("music_fetch.diagnostics.open_url", side_effect=http_error):
            result = probe_endpoint("CDN", "https://example.test")
        self.assertTrue(result.reachable)
        self.assertEqual(result.status_code, 403)

    def test_connection_error_is_unreachable_and_credentials_are_redacted(self):
        failure = error.URLError(
            "proxy failed at socks5h://user:secret@proxy.local:1080"
        )
        with mock.patch("music_fetch.diagnostics.open_url", side_effect=failure):
            result = probe_endpoint("CDN", "https://example.test")
        self.assertFalse(result.reachable)
        self.assertNotIn("user:secret", result.detail)

    def test_network_diagnostics_runs_all_named_targets(self):
        with mock.patch(
            "music_fetch.diagnostics.probe_endpoint",
            side_effect=lambda name, _url, timeout: EndpointProbe(name, True, timeout),
        ) as probe:
            results = run_network_diagnostics(timeout=4)
        self.assertEqual(len(results), 2)
        self.assertEqual(probe.call_count, 2)
        self.assertEqual([result.status_code for result in results], [4, 4])


class DiagnosticReportTests(unittest.TestCase):
    def test_report_contains_runtime_state_without_sensitive_values(self):
        context = DiagnosticContext(
            app_version="1.12.0",
            log_path=Path("/tmp/music-fetch.log"),
            login_configured=True,
            proxy_type="socks5",
            proxy_host="127.0.0.1",
            proxy_port=1080,
            proxy_authenticated=True,
            ffmpeg_available=False,
            latest_task_state="failed",
            latest_error_code="DOWNLOAD_FAILED",
            latest_song_id="42",
        )
        log_tail = (
            "INFO ignored context\n"
            "WARNING MUSIC_U=raw-cookie\n"
            "ERROR proxy http://user:proxy-pass@127.0.0.1:1080 failed\n"
        )
        report = build_diagnostic_report(
            context,
            probes=(EndpointProbe("网易云 API", True, 200, "HTTP 200"),),
            log_tail=log_tail,
            sensitive_values=("raw-cookie", "proxy-pass"),
            generated_at=datetime(2026, 7, 19, 15, 0, 0),
        )
        self.assertIn("应用版本：1.12.0", report)
        self.assertIn("登录凭证：已配置 MUSIC_U", report)
        self.assertIn("网络代理：SOCKS5 127.0.0.1:1080，已配置认证", report)
        self.assertIn("最近错误码：DOWNLOAD_FAILED", report)
        self.assertIn("网易云 API：可达（HTTP 200）", report)
        self.assertNotIn("INFO ignored context", report)
        self.assertNotIn("raw-cookie", report)
        self.assertNotIn("proxy-pass", report)


if __name__ == "__main__":
    unittest.main()
