import base64
import json
import unittest
from unittest import mock

from music_fetch.weapi import (
    WEAPI_IV,
    WEAPI_SECOND_KEY,
    build_weapi_params,
    weapi_request,
)


def _unpad(text: str) -> str:
    if not text:
        return text
    pad = ord(text[-1])
    if 1 <= pad <= 16:
        return text[:-pad]
    return text


class WeapiCryptoTests(unittest.TestCase):
    def test_encseckey_is_base64_128_bytes_and_params_are_base64(self) -> None:
        params, enc_sec_key = build_weapi_params({"type": 1})
        decoded = base64.b64decode(enc_sec_key, validate=True)
        self.assertEqual(len(decoded), 128)  # 1024-bit RSA ciphertext
        self.assertGreater(len(base64.b64decode(params, validate=True)), 0)

    def test_double_aes_roundtrip_recovers_json(self) -> None:
        from Crypto.Cipher import AES

        with mock.patch("music_fetch.weapi.random.choice", side_effect=list("a" * 16)):
            params, _ = build_weapi_params({"type": 1})
        # Second pass: the fixed second key decrypts params to a base64 blob.
        cipher2 = AES.new(WEAPI_SECOND_KEY.encode("utf-8"), AES.MODE_CBC, WEAPI_IV.encode("utf-8"))
        first_pass = _unpad(cipher2.decrypt(base64.b64decode(params)).decode("utf-8"))
        # First pass: the patched secret key ("a" * 16) decrypts to the JSON.
        cipher1 = AES.new(b"a" * 16, AES.MODE_CBC, WEAPI_IV.encode("utf-8"))
        text = _unpad(cipher1.decrypt(base64.b64decode(first_pass)).decode("utf-8"))
        self.assertEqual(json.loads(text), {"type": 1})

    def test_params_are_deterministic_given_fixed_random(self) -> None:
        # encSecKey uses PKCS1 v1.5 (random padding), so it varies per call;
        # only the AES params are deterministic for a fixed secret key.
        with mock.patch("music_fetch.weapi.random.choice", side_effect=list("b" * 16)):
            first_params, _ = build_weapi_params({"type": 1})
        with mock.patch("music_fetch.weapi.random.choice", side_effect=list("b" * 16)):
            second_params, _ = build_weapi_params({"type": 1})
        self.assertEqual(first_params, second_params)


class WeapiRequestTests(unittest.TestCase):
    @mock.patch("music_fetch.api._perform_request")
    def test_request_posts_params_and_encseckey(self, perform_mock: mock.Mock) -> None:
        perform_mock.return_value = (200, b'{"code": 801, "message": "wait"}')
        status, body = weapi_request("/login/qrcode/unikey", {"type": 1}, timeout=5)
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], 801)
        req = perform_mock.call_args.args[0]
        self.assertEqual(req.full_url, "https://music.163.com/weapi/login/qrcode/unikey")
        self.assertTrue(req.data.startswith(b"params="))
        self.assertIn(b"&encSecKey=", req.data)

    @mock.patch("music_fetch.api._perform_request")
    def test_request_body_is_url_encoded_form(self, perform_mock: mock.Mock) -> None:
        from urllib.parse import parse_qs

        perform_mock.return_value = (200, b'{"code": 200}')
        weapi_request("/login/qrcode/unikey", {"type": 1}, timeout=5)
        req = perform_mock.call_args.args[0]
        fields = parse_qs(req.data.decode("utf-8"))
        self.assertEqual(set(fields), {"params", "encSecKey"})
        self.assertTrue(fields["params"][0])
        self.assertTrue(fields["encSecKey"][0])

    @mock.patch("music_fetch.api._perform_request")
    def test_request_handles_invalid_json(self, perform_mock: mock.Mock) -> None:
        perform_mock.return_value = (200, b"not json")
        status, body = weapi_request("/login/qrcode/unikey", {"type": 1}, timeout=5)
        self.assertEqual(status, 200)
        self.assertEqual(body, {})


if __name__ == "__main__":
    unittest.main()
