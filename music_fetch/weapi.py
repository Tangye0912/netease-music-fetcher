#!/usr/bin/env python3
"""Netease weapi transport — the standard web API encryption.

The music.163.com web client protects POST bodies with the "weapi" scheme:
AES-128-CBC double encryption plus RSA over the session key.  Third-party
tools use this for login endpoints where plain or mobile (eapi) flows get
rejected by risk control with code 8821.

  body = params=<b64 AES(AES(json, k), "0CoJUm6Qyw8W8jud")>
         &encSecKey=<hex RSA(reverse(k))>
"""

from __future__ import annotations

import base64
import json
import random
from typing import Any
from urllib import parse, request

from music_fetch.api import USER_AGENT

WEAPI_MODULUS = (
    "00e0b509f6259df8642dbc35662901477df22677ec152b5ff68ace615bb7b725152b3ab17"
    "a876aea8a5aa76d2e417629ec4ee341f56135fccf695280104e0312ecbda92557c93870114"
    "af6c9d05c4f7f0c3685b7a46bee255932575cce10b424d813cfe4875d3e82047b97ddef527"
    "41d546b8e289dc6935b3ece0462db0a22b8e7"
)
WEAPI_EXPONENT = "010001"
WEAPI_SECOND_KEY = "0CoJUm6Qyw8W8jud"
WEAPI_IV = "0102030405060708"
_RSA_CHARSET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _aes_cbc_encrypt(text: str, key: str) -> str:
    """AES-128-CBC (base64 output) with the shared 16-byte IV."""
    from Crypto.Cipher import AES  # local import keeps the module importable

    pad = 16 - (len(text) % 16)
    padded = (text + chr(pad) * pad).encode("utf-8")
    cipher = AES.new(key.encode("utf-8"), AES.MODE_CBC, WEAPI_IV.encode("utf-8"))
    return base64.b64encode(cipher.encrypt(padded)).decode("utf-8")


def _rsa_encrypt(secret_key: str) -> str:
    """RSA-encrypt the reversed session key (PKCS1 v1.5, base64 output).

    Matches the canonical weapi scheme used by the web client and by
    NeteaseCloudMusicApi: `publicEncrypt(reversed_key)` with RSA_PKCS1
    padding, base64-encoded.  The raw modular-exponentiation variant that
    some Python ports use is NOT accepted by the server (it returns an
    empty 200 body).
    """
    from Crypto.Cipher import PKCS1_v1_5
    from Crypto.PublicKey import RSA

    modulus = int(WEAPI_MODULUS, 16)
    exponent = int(WEAPI_EXPONENT, 16)
    pubkey = RSA.construct((modulus, exponent))
    encrypted = PKCS1_v1_5.new(pubkey).encrypt(secret_key[::-1].encode("utf-8"))
    return base64.b64encode(encrypted).decode("utf-8")


def build_weapi_params(payload: dict[str, Any]) -> tuple[str, str]:
    """Build (params, encSecKey) for a weapi POST body."""
    secret_key = "".join(random.choice(_RSA_CHARSET) for _ in range(16))
    first_pass = _aes_cbc_encrypt(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        secret_key,
    )
    params = _aes_cbc_encrypt(first_pass, WEAPI_SECOND_KEY)
    return params, _rsa_encrypt(secret_key)


def weapi_request(
    path: str, payload: dict[str, Any], timeout: int = 10
) -> tuple[int, dict[str, Any]]:
    """POST an encrypted weapi request; returns (http_status, parsed_body)."""
    # Avoid a circular import at module top.
    from music_fetch.api import _perform_request

    url = f"https://music.163.com/weapi{path}"
    params, enc_sec_key = build_weapi_params(payload)
    # params is base64 and may contain '+', '/', '=' — URL-encode the whole
    # form body or the server's form parser corrupts it (turns '+' into space).
    body = parse.urlencode({"params": params, "encSecKey": enc_sec_key})
    req = request.Request(
        url,
        data=body.encode("utf-8"),
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://music.163.com/",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    status, raw = _perform_request(req, timeout=timeout)
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return status, {}
    return status, parsed


__all__ = ["build_weapi_params", "weapi_request"]
