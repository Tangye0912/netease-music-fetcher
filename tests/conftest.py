"""Shared test guards.

A unit test must never open a real network connection: it makes the suite depend
on the outside world and, worse, a leaked background thread can interfere with
another test's fake socket handler.  Loopback stays allowed so the tests that
spin up local HTTP/SOCKS servers keep working.

Opting in: ``tests/test_live_api.py`` checks assumptions that only the real
NetEase API can answer.  It runs only when ``MUSIC_FETCH_LIVE_COOKIE`` is set,
and only that module may bypass the guard.
"""

from __future__ import annotations

import os
import socket
import urllib.request

import pytest

LIVE_COOKIE_ENV = "MUSIC_FETCH_LIVE_COOKIE"
LIVE_MODULE = "test_live_api.py"

_ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost", ""}
_real_connect = socket.socket.connect


def live_cookie() -> str:
    """Session cookie for the opt-in live checks ("" when not provided)."""
    return (os.environ.get(LIVE_COOKIE_ENV) or "").strip()


def _guarded_connect(self: socket.socket, address: object) -> object:
    host = address[0] if isinstance(address, tuple) else address
    if str(host) not in _ALLOWED_HOSTS:
        raise RuntimeError(
            f"test attempted a real network connection to {host!r}; "
            "mock the request or use a loopback server instead"
        )
    return _real_connect(self, address)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def block_real_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    # Proxy discovery must be off as well: on a machine with a system proxy
    # (urllib.getproxies() reads the macOS/Windows settings) a missing mock
    # connects to the loopback proxy, which the guard below allows, so the real
    # request slips through locally and only blows up in CI.
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    if live_cookie() and getattr(request.node, "path", None) is not None and request.node.path.name == LIVE_MODULE:
        return
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
