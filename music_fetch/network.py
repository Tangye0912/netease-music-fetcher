#!/usr/bin/env python3
"""Shared network transport with application-level proxy support."""

from __future__ import annotations

import io
import threading
from dataclasses import dataclass
from email.message import Message
from typing import Any
from urllib import error, parse, request

from music_fetch.app_logging import get_logger

logger = get_logger("music_fetch.network")

SUPPORTED_PROXY_TYPES = ("http", "socks5")


class ProxyConfigError(ValueError):
    """Raised when proxy settings are incomplete or unsafe to apply."""


@dataclass(frozen=True)
class ProxyConfig:
    proxy_type: str = ""
    host: str = ""
    port: int = 0
    username: str = ""
    password: str = ""

    @property
    def enabled(self) -> bool:
        return bool(self.proxy_type)

    @property
    def proxy_url(self) -> str:
        if not self.enabled:
            return ""
        scheme = "socks5h" if self.proxy_type == "socks5" else "http"
        host = f"[{self.host}]" if ":" in self.host and not self.host.startswith("[") else self.host
        credentials = ""
        if self.username:
            encoded_user = parse.quote(self.username, safe="")
            encoded_password = parse.quote(self.password, safe="")
            credentials = f"{encoded_user}:{encoded_password}@"
        return f"{scheme}://{credentials}{host}:{self.port}"


_config_lock = threading.RLock()
_proxy_config = ProxyConfig()
_http_proxy_handler: request.BaseHandler | None = None


def normalize_proxy_config(
    proxy_type: str = "",
    host: str = "",
    port: int = 0,
    username: str = "",
    password: str = "",
) -> ProxyConfig:
    """Validate and normalize a proxy configuration without applying it."""
    normalized_type = str(proxy_type or "").strip().lower()
    if normalized_type in {"", "direct", "none"}:
        return ProxyConfig()
    if normalized_type not in SUPPORTED_PROXY_TYPES:
        raise ProxyConfigError(f"Unsupported proxy type: {normalized_type}")

    normalized_host = str(host or "").strip()
    if normalized_host.startswith("[") and normalized_host.endswith("]"):
        normalized_host = normalized_host[1:-1]
    if (
        not normalized_host
        or any(char.isspace() for char in normalized_host)
        or any(token in normalized_host for token in ("://", "/", "?", "#", "@"))
    ):
        raise ProxyConfigError("Proxy host must be a hostname or IP address without a URL scheme or path.")

    try:
        normalized_port = int(port)
    except (TypeError, ValueError) as err:
        raise ProxyConfigError("Proxy port must be an integer between 1 and 65535.") from err
    if not 1 <= normalized_port <= 65535:
        raise ProxyConfigError("Proxy port must be between 1 and 65535.")

    normalized_username = str(username or "").strip()
    normalized_password = str(password or "")
    if normalized_password and not normalized_username:
        raise ProxyConfigError("Proxy username is required when a password is provided.")

    return ProxyConfig(
        proxy_type=normalized_type,
        host=normalized_host,
        port=normalized_port,
        username=normalized_username,
        password=normalized_password,
    )


def configure_proxy(
    proxy_type: str = "",
    host: str = "",
    port: int = 0,
    username: str = "",
    password: str = "",
) -> ProxyConfig:
    """Apply proxy settings used by every urllib-based project request."""
    global _proxy_config, _http_proxy_handler
    config = normalize_proxy_config(proxy_type, host, port, username, password)
    with _config_lock:
        _proxy_config = config
        _http_proxy_handler = None
        if config.proxy_type == "http":
            proxy_url = config.proxy_url
            _http_proxy_handler = request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    if config.enabled:
        logger.info(
            "Proxy configured. type=%s host=%s port=%s authenticated=%s",
            config.proxy_type,
            config.host,
            config.port,
            bool(config.username),
        )
    else:
        logger.info("Application proxy disabled; using the system network configuration.")
    return config


def get_proxy_config() -> ProxyConfig:
    with _config_lock:
        return _proxy_config


class _RequestsResponseAdapter:
    """Expose the small urllib response surface used by this project."""

    def __init__(self, response: Any, session: Any) -> None:
        self._response = response
        self._session = session
        self.status = int(response.status_code)
        self.code = self.status
        self.headers = response.headers

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            return bytes(self._response.raw.read())
        return bytes(self._response.raw.read(size))

    def geturl(self) -> str:
        return str(self._response.url)

    def getcode(self) -> int:
        return self.status

    def close(self) -> None:
        self._response.close()
        self._session.close()

    def __enter__(self) -> "_RequestsResponseAdapter":
        return self

    def __exit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        self.close()


def _open_with_socks(req: request.Request, timeout: int) -> _RequestsResponseAdapter:
    try:
        import requests
    except ImportError as err:  # pragma: no cover - guarded by project dependency
        raise error.URLError("SOCKS5 proxy support requires requests[socks].") from err

    config = get_proxy_config()
    session = requests.Session()
    session.trust_env = False
    proxy_url = config.proxy_url
    session.proxies.update({"http": proxy_url, "https": proxy_url})
    try:
        response = session.request(
            method=req.get_method(),
            url=req.full_url,
            headers=dict(req.header_items()),
            data=req.data,
            timeout=timeout,
            allow_redirects=True,
            stream=True,
        )
    except requests.RequestException as err:
        session.close()
        raise error.URLError(str(err)) from err

    if response.status_code >= 400:
        body = bytes(response.content)
        final_url = str(response.url)
        status_code = int(response.status_code)
        reason = str(response.reason or "HTTP error")
        headers = Message()
        for key, value in response.headers.items():
            headers[str(key)] = str(value)
        response.close()
        session.close()
        raise error.HTTPError(final_url, status_code, reason, headers, io.BytesIO(body))
    return _RequestsResponseAdapter(response, session)


def open_url(req: request.Request, timeout: int) -> Any:
    """Open a URL through the active direct, HTTP, or SOCKS5 transport."""
    with _config_lock:
        config = _proxy_config
        http_handler = _http_proxy_handler
    if config.proxy_type == "socks5":
        return _open_with_socks(req, timeout)
    if http_handler is not None:
        return request.build_opener(http_handler).open(req, timeout=timeout)
    return request.urlopen(req, timeout=timeout)


__all__ = [
    "ProxyConfig",
    "ProxyConfigError",
    "SUPPORTED_PROXY_TYPES",
    "configure_proxy",
    "get_proxy_config",
    "normalize_proxy_config",
    "open_url",
]
