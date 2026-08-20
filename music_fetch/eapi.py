#!/usr/bin/env python3
"""Netease eapi transport — AES-128-ECB encrypted API calls.

The modern NetEase client talks to the /eapi/ endpoints instead of the
plain /api/ ones; risk control rejects plain requests for sensitive flows
(e.g. QR login confirmation returns code 8821).  This module implements
the well-known eapi scheme:

  raw = path + "-36cd479b6b5-" + json + "-36cd479b6b5-" + md5(
        "nobody" + path + "use" + json + "md5forencrypt")
  body = "params=" + hex(AES-128-ECB(raw, key="e82ckenh8dichen8"))
"""

from __future__ import annotations

import hashlib
import json
from typing import Any
from urllib import request

from music_fetch.api import USER_AGENT

EAPI_KEY = b"e82ckenh8dichen8"
EAPI_MAGIC = "36cd479b6b5"


def _pkcs7_pad(data: bytes) -> bytes:
    pad = 16 - (len(data) % 16)
    return data + bytes([pad]) * pad


def _pkcs7_unpad(data: bytes) -> bytes:
    if not data:
        return data
    pad = data[-1]
    if pad < 1 or pad > 16:
        return data
    return data[:-pad]


def build_eapi_params(path: str, payload: dict[str, Any]) -> str:
    """Build the encrypted params value for an eapi POST."""
    from Crypto.Cipher import AES  # local import keeps the module importable

    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    text = f"nobody{path}use{data}md5forencrypt"
    md5str = hashlib.md5(text.encode("utf-8")).hexdigest()
    raw = f"{path}-{EAPI_MAGIC}-{data}-{EAPI_MAGIC}-{md5str}"
    cipher = AES.new(EAPI_KEY, AES.MODE_ECB)
    encrypted = cipher.encrypt(_pkcs7_pad(raw.encode("utf-8")))
    return encrypted.hex().upper()


def decrypt_eapi_response(body: str) -> dict[str, Any]:
    """Decrypt an eapi response body (hex-encoded AES-ECB) into JSON."""
    from Crypto.Cipher import AES

    cipher = AES.new(EAPI_KEY, AES.MODE_ECB)
    try:
        decrypted = _pkcs7_unpad(cipher.decrypt(bytes.fromhex(body.strip())))
        return json.loads(decrypted.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        # Some eapi endpoints answer with plain JSON; return it as-is.
        return json.loads(body)


def eapi_request(
    path: str,
    payload: dict[str, Any],
    timeout: int = 10,
    user_agent: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """POST an encrypted eapi request; returns (http_status, parsed_body).

    *user_agent* overrides the shared desktop User-Agent when a request must
    present a different client identity (e.g. the mobile app UA for the QR
    login flow).
    """
    # Avoid a circular import at module top.
    from music_fetch.api import _perform_request

    url = f"https://music.163.com/eapi{path}"
    body = f"params={build_eapi_params(path, payload)}"
    req = request.Request(
        url,
        data=body.encode("utf-8"),
        headers={
            "User-Agent": user_agent or USER_AGENT,
            "Referer": "https://music.163.com/",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    status, raw = _perform_request(req, timeout=timeout)
    try:
        parsed = decrypt_eapi_response(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return status, {}
    return status, parsed


__all__ = [
    "build_eapi_params",
    "decrypt_eapi_response",
    "eapi_request",
]
