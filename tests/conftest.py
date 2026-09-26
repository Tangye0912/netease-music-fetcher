"""Shared test guards.

A unit test must never open a real network connection: it makes the suite depend
on the outside world and, worse, a leaked background thread can interfere with
another test's fake socket handler.  Loopback stays allowed so the tests that
spin up local HTTP/SOCKS servers keep working.
"""

from __future__ import annotations

import socket
import urllib.request

import pytest

_ALLOWED_HOSTS = {"127.0.0.1", "::1", "localhost", ""}
_real_connect = socket.socket.connect


def _guarded_connect(self: socket.socket, address: object) -> object:
    host = address[0] if isinstance(address, tuple) else address
    if str(host) not in _ALLOWED_HOSTS:
        raise RuntimeError(
            f"test attempted a real network connection to {host!r}; "
            "mock the request or use a loopback server instead"
        )
    return _real_connect(self, address)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def block_real_network(monkeypatch: pytest.MonkeyPatch) -> None:
    # Proxy discovery must be off as well: on a machine with a system proxy
    # (urllib.getproxies() reads the macOS/Windows settings) a missing mock
    # connects to the loopback proxy, which the guard below allows, so the real
    # request slips through locally and only blows up in CI.
    monkeypatch.setattr(urllib.request, "getproxies", lambda: {})
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
