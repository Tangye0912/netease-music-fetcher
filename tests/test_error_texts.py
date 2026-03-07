import unittest

from error_texts import user_error_message


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


if __name__ == "__main__":
    unittest.main()
