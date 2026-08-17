from __future__ import annotations

import unittest
from datetime import date

from daily_brief_agent import validate_brief as validator


def build_mail(
    *,
    global_count: int = 8,
    history_count: int = 3,
    market: bool = True,
    extra_link: str = "",
    hour: int = 11,
    include_facts: bool = True,
    include_history: bool = True,
) -> str:
    global_items = "".join(
        f'<h3>{i}.【领域】事件 {i}<a href="https://source{i}.example.com/item/{i}">来源</a></h3>'
        for i in range(1, global_count + 1)
    )
    history_items = "".join(f"<h3>{1900 + i}年：历史事件 {i}</h3>" for i in range(history_count))
    market_html = "<h2>七、市场总览</h2><h2>八、股票与指数</h2>" if market else ""
    facts_html = "<h2>三、事实核查</h2>" if include_facts else ""
    history_html = f"<h2>九、历史上的今天</h2>{history_items}" if include_history else ""
    return f"""Subject: 每日大事与市场简报 - 2026-08-04 {hour:02d}:00 中国时间
<html><body>
<h2>一、本期 5 个要点</h2>
<h2>二、全球重大事件</h2>{global_items}
{facts_html}
<h2>四、国际关系观察</h2>
<h2>五、权威智库报告</h2>
<h2>六、国际战争观察</h2>
{market_html}
{history_html}
<p><a href="https://example.com/source">来源</a>{extra_link}</p>
<h2>数据与方法说明</h2>
</body></html>"""


def build_list_history_mail(history_count: int = 4) -> str:
    mail = build_mail(history_count=0)
    items = "".join(f"<li><strong>{1900 + i}年：历史事件 {i}</strong></li>" for i in range(history_count))
    return mail.replace("<h2>九、历史上的今天</h2>", f"<h2>九、历史上的今天</h2><ol>{items}</ol>")


class ValidateBriefTests(unittest.TestCase):
    def test_valid_weekday_mail_passes(self):
        self.assertEqual(validator.validate(build_mail(), date(2026, 8, 4)), [])

    def test_weekday_requires_market_sections(self):
        errors = validator.validate(build_mail(market=False), date(2026, 8, 4))
        self.assertIn("weekday_market_sections_missing", errors)

    def test_weekend_allows_market_omission(self):
        self.assertEqual(validator.validate(build_mail(market=False), date(2026, 8, 8)), [])

    def test_global_events_have_hard_maximum(self):
        errors = validator.validate(build_mail(global_count=16), date(2026, 8, 4))
        self.assertIn("global_event_count:16_not_in_1_15", errors)

    def test_history_requires_three_to_five_entries(self):
        errors = validator.validate(build_mail(history_count=2), date(2026, 8, 4))
        self.assertIn("history_event_count:2_not_in_3_5", errors)

    def test_fact_check_section_is_optional(self):
        self.assertEqual(validator.validate(build_mail(include_facts=False), date(2026, 8, 4)), [])

    def test_evening_edition_omits_history(self):
        self.assertEqual(
            validator.validate(build_mail(hour=23, include_history=False), date(2026, 8, 4)),
            [],
        )

    def test_evening_edition_rejects_history(self):
        errors = validator.validate(build_mail(hour=23), date(2026, 8, 4))
        self.assertIn("history_section_forbidden_at_23", errors)

    def test_history_accepts_semantic_list_items(self):
        self.assertEqual(validator.validate(build_list_history_mail(), date(2026, 8, 4)), [])

    def test_history_must_precede_method_footer(self):
        mail = build_mail().replace("<h2>九、历史上的今天</h2>", "<h2>历史上的今天</h2>").replace(
            "<h2>数据与方法说明</h2>", "<h2>八、数据与方法说明</h2>"
        )
        self.assertEqual(validator.validate(mail, date(2026, 8, 4)), [])

    def test_google_news_links_and_social_sections_are_rejected(self):
        link = '<a href="https://news.google.com/rss/articles/abc">聚合</a>'
        errors = validator.validate(build_mail(extra_link=link), date(2026, 8, 4))
        self.assertIn("google_news_link_present", errors)
        social = build_mail().replace("<h2>三、事实核查</h2>", "<h2>X 平台热帖</h2>")
        self.assertIn("cancelled_social_section_present", validator.validate(social, date(2026, 8, 4)))

    def test_invented_think_tank_author_placeholder_is_rejected(self):
        mail = build_mail().replace("<h2>五、权威智库报告</h2>", "<h2>五、权威智库报告</h2><p>作者：某机构研究团队</p>")
        self.assertIn("think_tank_author_placeholder", validator.validate(mail, date(2026, 8, 4)))

    def test_english_leak_is_rejected(self):
        mail = build_mail().replace("</body>", "<p>The source reportedly awaits approval.</p></body>")
        self.assertIn("english_leak_present", validator.validate(mail, date(2026, 8, 4)))

    def test_source_concentration_is_rejected(self):
        mail = build_mail()
        for i in range(1, 9):
            mail = mail.replace(
                f"https://source{i}.example.com/item/{i}",
                f"https://apnews.com/article/{i}",
            )
        errors = validator.validate(mail, date(2026, 8, 4))
        self.assertIn("source_concentration_exceeded:全球重大事件", errors)


if __name__ == "__main__":
    unittest.main()
