import unittest
from unittest import mock

from music_fetch.eapi import build_eapi_params, decrypt_eapi_response, eapi_request


class EapiCryptoTests(unittest.TestCase):
    def test_params_are_uppercase_hex_and_padded(self):
        params = build_eapi_params("/api/login/qrcode/unikey", {"type": "3"})
        self.assertTrue(params.isupper())
        self.assertEqual(len(params) % 32, 0)
        int(params, 16)  # must be valid hex

    def test_params_are_deterministic(self):
        first = build_eapi_params("/api/x", {"a": "1"})
        second = build_eapi_params("/api/x", {"a": "1"})
        self.assertEqual(first, second)

    def test_params_roundtrip_through_decrypt(self):
        from Crypto.Cipher import AES
        import music_fetch.eapi as eapi_module

        params = build_eapi_params("/api/login/qrcode/client/login", {"key": "k1", "type": "3"})
        cipher = AES.new(eapi_module.EAPI_KEY, AES.MODE_ECB)
        decrypted = eapi_module._pkcs7_unpad(cipher.decrypt(bytes.fromhex(params)))
        text = decrypted.decode("utf-8")
        self.assertTrue(text.startswith("/api/login/qrcode/client/login-36cd479b6b5-"))
        self.assertIn("\"key\":\"k1\"", text)

    def test_decrypt_response_handles_encrypted_body(self):
        build_eapi_params("/api/login/qrcode/client/login", {"key": "k1", "type": "3"})
        from Crypto.Cipher import AES
        import music_fetch.eapi as eapi_module

        cipher = AES.new(eapi_module.EAPI_KEY, AES.MODE_ECB)
        payload = '{"code": 801, "message": "等待扫码"}'
        encrypted = cipher.encrypt(eapi_module._pkcs7_pad(payload.encode("utf-8")))
        result = decrypt_eapi_response(encrypted.hex())
        self.assertEqual(result["code"], 801)

    def test_decrypt_response_falls_back_to_plain_json(self):
        result = decrypt_eapi_response('{"code": 200}')
        self.assertEqual(result["code"], 200)


class EapiRequestTests(unittest.TestCase):
    @mock.patch("music_fetch.api._perform_request")
    def test_request_posts_params_and_decrypts(self, perform_mock):
        import music_fetch.eapi as eapi_module
        from Crypto.Cipher import AES

        payload = '{"code": 801, "message": "等待扫码"}'
        cipher = AES.new(eapi_module.EAPI_KEY, AES.MODE_ECB)
        encrypted = cipher.encrypt(eapi_module._pkcs7_pad(payload.encode("utf-8")))
        perform_mock.return_value = (200, encrypted.hex().encode("utf-8"))

        status, body = eapi_request("/api/login/qrcode/client/login", {"key": "k1", "type": "3"}, timeout=5)
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], 801)
        req = perform_mock.call_args.args[0]
        self.assertEqual(req.full_url, "https://music.163.com/eapi/api/login/qrcode/client/login")
        self.assertTrue(req.data.startswith(b"params="))


if __name__ == "__main__":
    unittest.main()
