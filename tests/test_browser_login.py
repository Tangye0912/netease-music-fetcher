import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib import request

from music_fetch import browser_login
from music_fetch.browser_login import (
    BrowserLoginError,
    build_cookie_string,
    find_browser_exe,
    pick_free_port,
    run_official_login,
)


class CookieStringTests(unittest.TestCase):
    def test_build_cookie_string_joins_name_value_pairs(self) -> None:
        cookies: list[dict[str, object]] = [
            {"name": "MUSIC_U", "value": "abc"},
            {"name": "__csrf", "value": "123"},
            {"name": "NMTID", "value": ""},  # empty value must be skipped
            {"name": "", "value": "x"},  # empty name must be skipped
        ]
        self.assertEqual(
            build_cookie_string(cookies),
            "MUSIC_U=abc; __csrf=123",
        )

    def test_build_cookie_string_empty(self) -> None:
        self.assertEqual(build_cookie_string([]), "")


class FindBrowserTests(unittest.TestCase):
    def test_returns_existing_candidate_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fake_browser = Path(tmp) / "msedge.exe"
            fake_browser.write_text("", encoding="utf-8")
            with mock.patch.object(browser_login, "_BROWSER_CANDIDATES", [str(fake_browser)]):
                self.assertEqual(find_browser_exe(), str(fake_browser))

    def test_falls_back_to_which(self) -> None:
        with mock.patch.object(browser_login, "_BROWSER_CANDIDATES", []), mock.patch.object(
            browser_login.shutil, "which", return_value="/fake/chrome"
        ):
            self.assertEqual(find_browser_exe(), "/fake/chrome")

    def test_returns_none_when_nothing_found(self) -> None:
        with mock.patch.object(browser_login, "_BROWSER_CANDIDATES", []), mock.patch.object(
            browser_login.shutil, "which", return_value=None
        ):
            self.assertIsNone(find_browser_exe())


class PickFreePortTests(unittest.TestCase):
    def test_returns_bindable_port_in_range(self) -> None:
        port = pick_free_port()
        self.assertTrue(1024 <= port <= 65535)


class LaunchBrowserTests(unittest.TestCase):
    def test_launch_includes_remote_allow_origins(self) -> None:
        with mock.patch.object(browser_login.subprocess, "Popen") as popen_mock:
            popen_mock.return_value = mock.Mock()
            browser_login._launch_browser("/fake/msedge.exe", 12345, "/tmp/profile", browser_login.LOGIN_URL)
        cmd = popen_mock.call_args.args[0]
        self.assertIn("--remote-allow-origins=*", cmd)
        self.assertIn("--remote-debugging-port=12345", cmd)
        self.assertIn("--user-data-dir=/tmp/profile", cmd)
        self.assertIn(browser_login.LOGIN_URL, cmd)


class LocalCdpTransportTests(unittest.TestCase):
    class _FakeResponse:
        def __init__(self, payload: bytes) -> None:
            self.payload = payload

        def read(self) -> bytes:
            return self.payload

        def __enter__(self) -> "LocalCdpTransportTests._FakeResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def test_direct_opener_has_no_proxy_configuration(self) -> None:
        proxy_handlers = [
            handler
            for handler in browser_login._DIRECT_OPENER.handlers
            if isinstance(handler, request.ProxyHandler)
        ]
        self.assertEqual(proxy_handlers, [])

    def test_wait_for_cdp_uses_local_direct_transport(self) -> None:
        response = self._FakeResponse(b'{"Browser":"Chrome"}')
        with mock.patch.object(browser_login, "_open_local_url", return_value=response) as open_local:
            port = browser_login._wait_for_cdp_ws(None, 12345, timeout=1)
        self.assertEqual(port, 12345)
        self.assertEqual(open_local.call_args.args[0].full_url, "http://127.0.0.1:12345/json/version")


class ReadMusicCookiesTests(unittest.TestCase):
    class _FakeWs:
        def __init__(self, responses: list[dict[str, object]]) -> None:
            self.responses = responses
            self.sent: list[str] = []
            self.closed = False

        def settimeout(self, _value: float) -> None:
            return None

        def send(self, payload: str) -> None:
            self.sent.append(payload)

        def recv(self) -> str:
            if self.responses:
                return json_dumps(self.responses.pop(0))
            raise OSError("closed")

        def close(self) -> None:
            self.closed = True

    def _patch_websocket(self, responses: list[dict[str, object]]) -> mock.Mock:
        fake_module = mock.Mock()
        fake_module.create_connection.return_value = self._FakeWs(responses)
        patch = mock.patch.dict(sys.modules, {"websocket": fake_module})
        patch.start()
        self.addCleanup(patch.stop)
        return fake_module

    def test_reads_and_filters_music_163_cookies(self) -> None:
        websocket = self._patch_websocket(
            [
                {
                    "id": 1000,
                    "result": {"result": {"type": "string", "value": "MUSIC_U=eval-cookie; __csrf=eval"}},
                },
                {
                    "id": 1001,
                    "result": {
                        "cookies": [
                            {"name": "MUSIC_U", "value": "music-value", "domain": "music.163.com"},
                            {"name": "OTHER", "value": "x", "domain": "example.com"},
                            {"name": "__csrf", "value": "csrf", "domain": ".163.com"},
                        ]
                    },
                },
            ]
        )
        with mock.patch.object(browser_login, "_find_page_ws", return_value="ws://page"):
            result = browser_login._read_music_cookies(12345, timeout=5)
        self.assertIn("MUSIC_U=eval-cookie", result)
        self.assertIn("MUSIC_U=music-value", result)
        self.assertNotIn("OTHER", result)
        self.assertEqual(
            websocket.create_connection.call_args.kwargs["http_no_proxy"],
            ["127.0.0.1", "localhost"],
        )

    def test_returns_empty_when_no_page_target(self) -> None:
        with mock.patch.object(browser_login, "_find_page_ws", return_value=None):
            self.assertEqual(browser_login._read_music_cookies(12345, timeout=2), "")


class RunOfficialLoginTests(unittest.TestCase):
    def _fake_proc(self) -> mock.Mock:
        proc = mock.Mock()
        proc.terminate = mock.Mock()
        proc.kill = mock.Mock()
        proc.wait = mock.Mock(return_value=0)
        return proc

    def test_raises_when_no_browser_found(self) -> None:
        with mock.patch.object(browser_login, "find_browser_exe", return_value=None):
            with self.assertRaises(BrowserLoginError) as raised:
                run_official_login(on_status=lambda _m: None)
        self.assertNotIn("粘贴 Cookie", str(raised.exception))
        self.assertIn("安装 Chrome 或 Edge", str(raised.exception))

    def test_always_launches_with_isolated_profile(self) -> None:
        proc = self._fake_proc()
        with mock.patch.object(browser_login, "find_browser_exe", return_value="/fake/msedge.exe"), mock.patch.object(
            browser_login, "pick_free_port", return_value=12345
        ), mock.patch.object(
            browser_login, "_launch_browser", return_value=proc
        ) as launch_mock, mock.patch.object(
            browser_login.tempfile, "mkdtemp", return_value="/isolated/profile"
        ), mock.patch.object(
            browser_login, "_wait_for_cdp_ws", return_value=12345
        ), mock.patch.object(
            browser_login, "_read_music_cookies", return_value="MUSIC_U=abc; __csrf=1"
        ), mock.patch.object(
            browser_login.shutil, "rmtree"
        ):
            cookie = run_official_login(timeout=10, on_status=lambda _m: None)
        self.assertIn("MUSIC_U=abc", cookie)
        self.assertEqual(launch_mock.call_args.args[2], "/isolated/profile")
        proc.terminate.assert_called_once_with()
        proc.wait.assert_called_once_with(timeout=5.0)

    def test_forces_browser_exit_when_terminate_times_out(self) -> None:
        proc = self._fake_proc()
        proc.wait.side_effect = [subprocess.TimeoutExpired("browser", 5), 0]
        with mock.patch.object(browser_login, "find_browser_exe", return_value="/fake/msedge.exe"), mock.patch.object(
            browser_login, "pick_free_port", return_value=12345
        ), mock.patch.object(
            browser_login, "_launch_browser", return_value=proc
        ), mock.patch.object(
            browser_login.tempfile, "mkdtemp", return_value="/isolated/profile"
        ), mock.patch.object(
            browser_login, "_wait_for_cdp_ws", return_value=12345
        ), mock.patch.object(
            browser_login, "_read_music_cookies", return_value="MUSIC_U=abc; __csrf=1"
        ), mock.patch.object(
            browser_login.shutil, "rmtree"
        ):
            cookie = run_official_login(timeout=10, on_status=lambda _m: None)
        self.assertIn("MUSIC_U=abc", cookie)
        proc.kill.assert_called_once_with()
        self.assertEqual(proc.wait.call_count, 2)

    def test_times_out_without_cookie(self) -> None:
        proc = self._fake_proc()
        with mock.patch.object(browser_login, "find_browser_exe", return_value="/fake/msedge.exe"), mock.patch.object(
            browser_login, "pick_free_port", return_value=12345
        ), mock.patch.object(
            browser_login, "_launch_browser", return_value=proc
        ), mock.patch.object(
            browser_login, "_wait_for_cdp_ws", return_value=12345
        ), mock.patch.object(
            browser_login, "_read_music_cookies", return_value=""
        ):
            with self.assertRaises(browser_login.MusicFetchError):
                run_official_login(timeout=1, on_status=lambda _m: None)

    def test_profile_cleanup_failure_is_reported(self) -> None:
        with mock.patch.object(browser_login.shutil, "rmtree", side_effect=OSError("busy")), mock.patch.object(
            browser_login.time, "sleep"
        ):
            with self.assertRaises(BrowserLoginError) as raised:
                browser_login._remove_temp_profile("/isolated/profile")
        self.assertIn("临时登录数据未能清理", str(raised.exception))

    def test_cleanup_failure_after_success_still_returns_cookie(self) -> None:
        proc = self._fake_proc()
        messages: list[str] = []
        with mock.patch.object(browser_login, "find_browser_exe", return_value="/fake/msedge.exe"), mock.patch.object(
            browser_login, "pick_free_port", return_value=12345
        ), mock.patch.object(
            browser_login, "_launch_browser", return_value=proc
        ), mock.patch.object(
            browser_login.tempfile, "mkdtemp", return_value="/isolated/profile"
        ), mock.patch.object(
            browser_login, "_wait_for_cdp_ws", return_value=12345
        ), mock.patch.object(
            browser_login, "_read_music_cookies", return_value="MUSIC_U=abc; __csrf=1"
        ), mock.patch.object(
            browser_login, "_remove_temp_profile", side_effect=BrowserLoginError("临时登录数据未能清理")
        ), mock.patch.object(
            browser_login, "_stop_browser", return_value=False
        ):
            cookie = run_official_login(timeout=10, on_status=messages.append)
        # A successful login must not be masked by a cleanup failure.
        self.assertIn("MUSIC_U=abc", cookie)
        self.assertTrue(any("清理未完成" in message for message in messages))

    def test_diagnose_never_outputs_cookie_value(self) -> None:
        proc = self._fake_proc()
        with mock.patch.object(browser_login, "find_browser_exe", return_value="/fake/msedge.exe"), mock.patch.object(
            browser_login, "pick_free_port", return_value=12345
        ), mock.patch.object(
            browser_login, "_launch_browser", return_value=proc
        ), mock.patch.object(
            browser_login, "_wait_for_cdp_ws", return_value=12345
        ), mock.patch.object(
            browser_login, "_find_page_ws", return_value="ws://page"
        ), mock.patch.object(
            browser_login, "_read_music_cookies", return_value="MUSIC_U=secret; __csrf=secret"
        ):
            lines = browser_login.diagnose(timeout=1)
        self.assertIn("cookies_found=True", lines)
        self.assertFalse(any("secret" in line or "cookie_preview" in line for line in lines))


class ReadDevtoolsPortTests(unittest.TestCase):
    def test_reads_port_from_devtools_active_port_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "DevToolsActivePort").write_text("51234\n/devtools/browser/abc\n", encoding="utf-8")
            self.assertEqual(browser_login._read_devtools_port(tmp), 51234)

    def test_returns_none_when_file_missing_or_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(browser_login._read_devtools_port(tmp))
            (Path(tmp) / "DevToolsActivePort").write_text("not-a-number\n", encoding="utf-8")
            self.assertIsNone(browser_login._read_devtools_port(tmp))


def json_dumps(value: dict[str, object]) -> str:
    import json

    return json.dumps(value)


if __name__ == "__main__":
    unittest.main()
