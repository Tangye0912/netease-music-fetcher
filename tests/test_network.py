"""Tests for the shared direct, HTTP, and SOCKS5 network transport."""

import unittest
import base64
import socketserver
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib import error, request
from unittest import mock

import requests

from music_fetch.network import (
    ProxyConfigError,
    configure_proxy,
    get_proxy_config,
    normalize_proxy_config,
    open_url,
)


@contextmanager
def _running_server(handler_class):
    class TestServer(socketserver.ThreadingTCPServer):
        allow_reuse_address = True
        daemon_threads = True

    server = TestServer(("127.0.0.1", 0), handler_class)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


class _HttpProxyHandler(BaseHTTPRequestHandler):
    request_path = ""
    proxy_authorization = ""

    def do_GET(self):
        type(self).request_path = self.path
        type(self).proxy_authorization = self.headers.get("Proxy-Authorization", "")
        body = b"http-proxy-ok"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format, *_args):
        return


def _recv_exact(sock, size):
    chunks = bytearray()
    while len(chunks) < size:
        chunk = sock.recv(size - len(chunks))
        if not chunk:
            raise ConnectionError("SOCKS5 test client disconnected unexpectedly")
        chunks.extend(chunk)
    return bytes(chunks)


class _Socks5ProxyHandler(socketserver.BaseRequestHandler):
    username = ""
    password = ""
    destination_host = ""
    request_line = ""

    def handle(self):
        sock = self.request
        sock.settimeout(3)
        version, method_count = _recv_exact(sock, 2)
        methods = _recv_exact(sock, method_count)
        if version != 5 or 2 not in methods:
            raise ConnectionError("SOCKS5 client did not offer username/password authentication")
        sock.sendall(b"\x05\x02")

        auth_version, username_length = _recv_exact(sock, 2)
        username = _recv_exact(sock, username_length).decode("utf-8")
        password_length = _recv_exact(sock, 1)[0]
        password = _recv_exact(sock, password_length).decode("utf-8")
        if auth_version != 1:
            raise ConnectionError("Unexpected SOCKS5 authentication version")
        type(self).username = username
        type(self).password = password
        sock.sendall(b"\x01\x00")

        version, command, _reserved, address_type = _recv_exact(sock, 4)
        if version != 5 or command != 1 or address_type != 3:
            raise ConnectionError("SOCKS5 client did not request a remote-DNS TCP connection")
        host_length = _recv_exact(sock, 1)[0]
        type(self).destination_host = _recv_exact(sock, host_length).decode("utf-8")
        _recv_exact(sock, 2)  # destination port
        sock.sendall(b"\x05\x00\x00\x01\x00\x00\x00\x00\x00\x00")

        request_data = bytearray()
        while b"\r\n\r\n" not in request_data:
            request_data.extend(sock.recv(4096))
        type(self).request_line = request_data.split(b"\r\n", 1)[0].decode("ascii")
        body = b"socks5-ok"
        sock.sendall(
            b"HTTP/1.1 200 OK\r\n"
            + f"Content-Length: {len(body)}\r\n".encode("ascii")
            + b"Connection: close\r\n\r\n"
            + body
        )


class ProxyConfigTests(unittest.TestCase):
    def tearDown(self):
        configure_proxy()

    def test_direct_aliases_disable_proxy(self):
        self.assertFalse(normalize_proxy_config().enabled)
        self.assertFalse(normalize_proxy_config("direct").enabled)
        self.assertFalse(normalize_proxy_config("none").enabled)

    def test_http_proxy_url_encodes_credentials(self):
        config = normalize_proxy_config(
            "http",
            "proxy.example.com",
            8080,
            "user@example.com",
            "p@ss word",
        )
        self.assertEqual(
            config.proxy_url,
            "http://user%40example.com:p%40ss%20word@proxy.example.com:8080",
        )

    def test_socks5_uses_remote_dns_scheme(self):
        config = normalize_proxy_config("socks5", "127.0.0.1", 1080)
        self.assertEqual(config.proxy_url, "socks5h://127.0.0.1:1080")

    def test_ipv6_host_is_bracketed_in_url(self):
        config = normalize_proxy_config("http", "[::1]", 7890)
        self.assertEqual(config.host, "::1")
        self.assertEqual(config.proxy_url, "http://[::1]:7890")

    def test_invalid_proxy_values_are_rejected(self):
        invalid_values = [
            ("ftp", "proxy.local", 21, "", ""),
            ("http", "", 8080, "", ""),
            ("http", "https://proxy.local", 8080, "", ""),
            ("http", "proxy.local/path", 8080, "", ""),
            ("http", "proxy.local", 0, "", ""),
            ("http", "proxy.local", 65536, "", ""),
            ("http", "proxy.local", 8080, "", "secret"),
        ]
        for values in invalid_values:
            with self.subTest(values=values), self.assertRaises(ProxyConfigError):
                normalize_proxy_config(*values)

    def test_configure_updates_active_config(self):
        configured = configure_proxy("http", "proxy.local", 8080)
        self.assertEqual(get_proxy_config(), configured)


class OpenUrlTests(unittest.TestCase):
    def tearDown(self):
        configure_proxy()

    def test_direct_transport_delegates_to_urllib(self):
        req = request.Request("https://example.com")
        response = mock.MagicMock()
        with mock.patch("music_fetch.network.request.urlopen", return_value=response) as urlopen:
            self.assertIs(open_url(req, timeout=5), response)
        urlopen.assert_called_once_with(req, timeout=5)

    def test_http_transport_builds_proxy_opener(self):
        configure_proxy("http", "proxy.local", 8080, "user", "pass")
        req = request.Request("https://example.com")
        opener = mock.MagicMock()
        response = mock.MagicMock()
        opener.open.return_value = response
        with mock.patch("music_fetch.network.request.build_opener", return_value=opener) as build_opener:
            self.assertIs(open_url(req, timeout=7), response)

        handler = build_opener.call_args.args[0]
        self.assertEqual(
            handler.proxies,
            {
                "http": "http://user:pass@proxy.local:8080",
                "https": "http://user:pass@proxy.local:8080",
            },
        )
        opener.open.assert_called_once_with(req, timeout=7)

    def test_socks_transport_applies_proxy_to_http_and_https(self):
        configure_proxy("socks5", "proxy.local", 1080, "user", "pass")
        req = request.Request(
            "https://example.com/api",
            data=b"key=value",
            headers={"X-Test": "yes"},
            method="POST",
        )
        session = mock.MagicMock()
        response = mock.MagicMock()
        response.status_code = 200
        response.url = "https://example.com/api"
        response.headers = {"Content-Type": "application/json"}
        response.raw.read.side_effect = [b"ok", b""]
        session.request.return_value = response

        with mock.patch("requests.Session", return_value=session):
            opened = open_url(req, timeout=9)
            self.assertEqual(opened.read(2), b"ok")
            opened.close()

        proxy_url = "socks5h://user:pass@proxy.local:1080"
        session.proxies.update.assert_called_once_with({"http": proxy_url, "https": proxy_url})
        session.request.assert_called_once_with(
            method="POST",
            url="https://example.com/api",
            headers={"X-test": "yes"},
            data=b"key=value",
            timeout=9,
            allow_redirects=True,
            stream=True,
        )
        response.close.assert_called_once()
        session.close.assert_called_once()

    def test_socks_http_error_is_translated_to_urllib_error(self):
        configure_proxy("socks5", "proxy.local", 1080)
        req = request.Request("https://example.com")
        session = mock.MagicMock()
        response = mock.MagicMock()
        response.status_code = 407
        response.url = "https://example.com"
        response.reason = "Proxy Authentication Required"
        response.headers = {"Content-Type": "text/plain"}
        response.content = b"proxy auth required"
        session.request.return_value = response

        with mock.patch("requests.Session", return_value=session):
            with self.assertRaises(error.HTTPError) as raised:
                open_url(req, timeout=5)

        self.assertEqual(raised.exception.code, 407)
        self.assertEqual(raised.exception.read(), b"proxy auth required")

    def test_socks_request_error_is_translated_to_url_error(self):
        configure_proxy("socks5", "proxy.local", 1080)
        req = request.Request("https://example.com")
        session = mock.MagicMock()
        session.request.side_effect = requests.exceptions.ProxyError("proxy unavailable")

        with mock.patch("requests.Session", return_value=session):
            with self.assertRaises(error.URLError) as raised:
                open_url(req, timeout=5)

        self.assertIn("proxy unavailable", str(raised.exception.reason))
        session.close.assert_called_once()


class NetworkArchitectureTests(unittest.TestCase):
    def test_only_shared_transport_calls_urllib_urlopen_directly(self):
        package_dir = Path(__file__).resolve().parents[1] / "music_fetch"
        offenders = []
        for source_path in package_dir.glob("*.py"):
            if source_path.name == "network.py":
                continue
            if "request.urlopen(" in source_path.read_text(encoding="utf-8"):
                offenders.append(source_path.name)
        self.assertEqual(offenders, [])


class ProxyEndToEndTests(unittest.TestCase):
    def tearDown(self):
        configure_proxy()

    def test_http_proxy_routes_request_with_basic_authentication(self):
        _HttpProxyHandler.request_path = ""
        _HttpProxyHandler.proxy_authorization = ""
        with _running_server(_HttpProxyHandler) as server:
            configure_proxy("http", "127.0.0.1", server.server_address[1], "proxy-user", "proxy-pass")
            req = request.Request("http://example.test/resource", method="GET")
            with open_url(req, timeout=3) as response:
                body = response.read()

        expected_auth = base64.b64encode(b"proxy-user:proxy-pass").decode("ascii")
        self.assertEqual(body, b"http-proxy-ok")
        self.assertEqual(_HttpProxyHandler.request_path, "http://example.test/resource")
        self.assertEqual(_HttpProxyHandler.proxy_authorization, f"Basic {expected_auth}")

    def test_socks5_proxy_performs_authentication_and_remote_dns(self):
        _Socks5ProxyHandler.username = ""
        _Socks5ProxyHandler.password = ""
        _Socks5ProxyHandler.destination_host = ""
        _Socks5ProxyHandler.request_line = ""
        with _running_server(_Socks5ProxyHandler) as server:
            configure_proxy("socks5", "127.0.0.1", server.server_address[1], "proxy-user", "proxy-pass")
            req = request.Request("http://example.test/resource", method="GET")
            with open_url(req, timeout=3) as response:
                body = response.read()

        self.assertEqual(body, b"socks5-ok")
        self.assertEqual(_Socks5ProxyHandler.username, "proxy-user")
        self.assertEqual(_Socks5ProxyHandler.password, "proxy-pass")
        self.assertEqual(_Socks5ProxyHandler.destination_host, "example.test")
        self.assertEqual(_Socks5ProxyHandler.request_line, "GET /resource HTTP/1.1")


if __name__ == "__main__":
    unittest.main()
