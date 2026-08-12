from __future__ import annotations

import unittest

from daily_brief_agent.smtp_send import build_message, split_subject_body


class SMTPMessageTests(unittest.TestCase):
    def test_split_subject_body_uses_generated_subject(self) -> None:
        subject, body = split_subject_body(
            "\nSubject: 每日大事与市场简报 - 2026-07-28 23:00 中国时间\n\n<html>正文</html>",
            "fallback",
        )
        self.assertEqual(subject, "每日大事与市场简报 - 2026-07-28 23:00 中国时间")
        self.assertEqual(body, "<html>正文</html>\n")

    def test_html_message_has_plain_and_html_alternatives(self) -> None:
        content = (
            "<html><body><h1>每日大事</h1><section><h2>全球重大事件</h2>"
            "<p>测试正文</p></section></body></html>"
        )
        message = build_message("sender@example.com", "reader@example.com", content, "测试")
        self.assertTrue(message.is_multipart())
        self.assertEqual(message.get_content_type(), "multipart/alternative")
        alternatives = list(message.iter_parts())
        self.assertEqual([part.get_content_type() for part in alternatives], ["text/plain", "text/html"])
        self.assertIn("全球重大事件", alternatives[0].get_content())
        self.assertIn("<html>", alternatives[1].get_content())

    def test_plain_text_message_stays_single_part(self) -> None:
        message = build_message(
            "sender@example.com",
            "reader@example.com",
            "普通文本正文\n",
            "测试",
        )
        self.assertFalse(message.is_multipart())
        self.assertEqual(message.get_content_type(), "text/plain")


if __name__ == "__main__":
    unittest.main()
