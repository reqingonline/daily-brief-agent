from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from daily_brief_agent import editorial_context as context


SAMPLE_MAIL = """Subject: 每日大事与市场简报 - 2026-08-03 23:00 中国时间
<html><body>
<h2>二、全球重大事件</h2>
<h3>1.【公共健康】乌干达更新疫情通报</h3>
<p><a href="https://example.com/health">来源：Example</a></p>
<h2>五、权威智库报告</h2>
<h3>1. 一份区域安全报告</h3>
<p><a href="https://example.org/report">来源：Institute</a></p>
</body></html>
"""


class EditorialContextTests(unittest.TestCase):
    def test_parse_brief_extracts_subject_sections_titles_and_links(self):
        parsed = context.parse_brief(SAMPLE_MAIL, "sent-message-20260803-230003.md")
        self.assertIn("2026-08-03 23:00", parsed["subject"])
        self.assertEqual(parsed["sections"][0]["name"], "全球重大事件")
        self.assertEqual(parsed["sections"][0]["items"][0]["title"], "乌干达更新疫情通报")
        self.assertEqual(parsed["sections"][0]["items"][0]["links"], ["https://example.com/health"])

    def test_item_title_normalizes_legacy_heading_orders(self):
        self.assertEqual(context._item_title("国际政治与安全1. 一项外交进展"), "一项外交进展")
        self.assertEqual(context._item_title("[科技、科学] 2. 一项研究"), "一项研究")

    def test_parse_brief_keeps_section_links_without_h3_items(self):
        mail = """Subject: 每日大事与市场简报 - 2026-07-29 11:00 中国时间
        <html><body><h2>五、权威智库报告</h2><p>旧版段落报告</p>
        <a href="https://example.org/legacy-report">原文</a></body></html>"""
        parsed = context.parse_brief(mail)
        self.assertEqual(parsed["sections"][0]["links"], ["https://example.org/legacy-report"])
        self.assertIn("旧版段落报告", parsed["sections"][0]["text"])

    def test_recent_files_prefer_sent_history_and_fall_back_to_legacy(self):
        with tempfile.TemporaryDirectory() as raw:
            log_dir = Path(raw)
            (log_dir / "sent-message-20260803-230003.md").write_text(SAMPLE_MAIL, encoding="utf-8")
            (log_dir / "last-message-20260804-110003.md").write_text(SAMPLE_MAIL, encoding="utf-8")
            selected = context.recent_message_files(log_dir, limit=6)
            self.assertEqual([path.name for path in selected], ["sent-message-20260803-230003.md"])

        with tempfile.TemporaryDirectory() as raw:
            log_dir = Path(raw)
            (log_dir / "last-message-20260804-110003.md").write_text(SAMPLE_MAIL, encoding="utf-8")
            selected = context.recent_message_files(log_dir, limit=6)
            self.assertEqual([path.name for path in selected], ["last-message-20260804-110003.md"])

    def test_recent_files_seed_sent_history_with_older_legacy_messages(self):
        with tempfile.TemporaryDirectory() as raw:
            log_dir = Path(raw)
            for name in (
                "sent-message-20260804-110003.md",
                "last-message-20260804-110003.md",
                "last-message-20260803-230003.md",
                "last-message-20260803-110003.md",
            ):
                (log_dir / name).write_text(SAMPLE_MAIL, encoding="utf-8")
            selected = context.recent_message_files(log_dir, limit=3)
            self.assertEqual(
                [path.name for path in selected],
                [
                    "sent-message-20260804-110003.md",
                    "last-message-20260803-230003.md",
                    "last-message-20260803-110003.md",
                ],
            )

    def test_edition_context_uses_shanghai_time_and_market_state(self):
        morning = datetime(2026, 8, 4, 10, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
        evening = datetime(2026, 8, 4, 22, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
        weekend = datetime(2026, 8, 8, 10, 55, tzinfo=ZoneInfo("Asia/Shanghai"))
        self.assertEqual(context.edition_context(morning)["edition"], "午间版")
        self.assertEqual(context.edition_context(evening)["edition"], "晚间版")
        self.assertEqual(context.edition_context(morning)["market_rule"], "weekday_morning")
        self.assertEqual(context.edition_context(evening)["market_rule"], "weekday_evening")
        self.assertEqual(context.edition_context(weekend)["market_rule"], "weekend_omit")

    def test_fetch_history_combines_languages_and_deduplicates(self):
        zh = {"events": [{"year": 1969, "text": "阿波罗任务", "pages": [{"title": "阿波罗计划", "wikibase_item": "Q46611", "content_urls": {"desktop": {"page": "https://zh.example/apollo"}}}]}]}
        en = {"events": [{"year": 1969, "text": "Apollo mission", "pages": [{"title": "Apollo program", "wikibase_item": "Q46611", "content_urls": {"desktop": {"page": "https://en.example/apollo"}}}]}, {"year": 1914, "text": "A declaration", "pages": []}]}
        with mock.patch.object(context, "fetch_json", side_effect=[zh, en]):
            events, errors = context.fetch_history_candidates(datetime(2026, 8, 4, tzinfo=ZoneInfo("Asia/Shanghai")))
        self.assertFalse(errors)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0]["languages"], ["zh", "en"])
        self.assertEqual(events[1]["year"], 1914)

    def test_render_context_contains_repeat_windows_and_history_candidates(self):
        parsed = context.parse_brief(SAMPLE_MAIL, "sent-message-20260803-230003.md")
        rendered = context.render_context(
            context.edition_context(datetime(2026, 8, 4, 10, 55, tzinfo=ZoneInfo("Asia/Shanghai"))),
            [parsed],
            [{"year": 1914, "text": "一项历史事件", "languages": ["zh"], "pages": []}],
            [],
        )
        self.assertIn("新闻与战争：72 小时", rendered)
        self.assertIn("事实核查与智库：7 天", rendered)
        self.assertIn("https://example.com/health", rendered)
        self.assertIn("1914", rendered)

    def test_render_context_includes_legacy_section_links_without_items(self):
        legacy = context.parse_brief(
            """Subject: 每日大事与市场简报 - 2026-07-29 11:00 中国时间
            <html><body><h2>五、权威智库报告</h2><p>旧版智库摘要</p>
            <a href="https://example.org/legacy">原文</a></body></html>"""
        )
        rendered = context.render_context(
            context.edition_context(datetime(2026, 8, 4, 10, 55, tzinfo=ZoneInfo("Asia/Shanghai"))),
            [legacy], [], [],
        )
        self.assertIn("旧版智库摘要", rendered)
        self.assertIn("https://example.org/legacy", rendered)


if __name__ == "__main__":
    unittest.main()
