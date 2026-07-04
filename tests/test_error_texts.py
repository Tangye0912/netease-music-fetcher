import unittest

from music_fetch.error_texts import user_error_message


class ErrorTextTests(unittest.TestCase):
    def test_known_code_mapping(self):
        text = user_error_message("AUTH_EXPIRED", "raw")
        self.assertIn("重新登录", text)

    def test_unknown_code_fallback_to_raw(self):
        text = user_error_message("SOME_NEW_CODE", "raw message")
        self.assertEqual(text, "raw message")

    def test_unknown_code_default(self):
        text = user_error_message("SOME_NEW_CODE", "")
        self.assertEqual(text, "操作失败，请稍后重试。")

    def test_network_error_with_certificate_failure_hint(self):
        text = user_error_message(
            "NETWORK_ERROR",
            "Network error: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in certificate chain",
        )
        self.assertIn("证书校验失败", text)


if __name__ == "__main__":
    unittest.main()
