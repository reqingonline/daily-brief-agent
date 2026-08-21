from __future__ import annotations

import unittest
from datetime import date

from daily_brief_agent import validate_brief as validator


def build_mail(*, global_count: int = 8, history_count: int = 3, market: bool = True, extra_link: str = "") -> str:
    global_items = "".join(
        f'<h3>{i}.【领域】事件 {i}<a href="https://source{i}.example.com/item/{i}">来源</a></h3>'
        for i in range(1, global_count + 1)
    )
    history_items = "".join(f"<h3>{1900 + i}年：历史事件 {i}</h3>" for i in range(history_count))
    futures_html = (
        "<h2>八、国际期货与大宗商品</h2>"
        "<h3>玉米期货 ZC=F</h3><h3>小麦期货 ZW=F</h3><h3>大豆期货 ZS=F</h3>"
        "<h3>黄金期货 GC=F</h3><h3>白银期货 SI=F</h3><h3>铜期货 HG=F</h3>"
    ) if market else ""
    stocks_html = (
        "<h2>九、股票与指数</h2>"
        "<h3>AAPL 苹果｜下一次财报：2026-10-29（预计）</h3>"
        "<h3>02513.HK 智谱（Z.AI）｜下一次财报：暂无可靠日期</h3>"
    ) if market else ""
    market_html = (
        "<h2>七、市场总览</h2>" + futures_html + stocks_html
        if market
        else ""
    )
    return f"""Subject: 每日大事与市场简报 - 2026-08-04 11:00 中国时间
<html><body>
<h2>一、本期 5 个要点</h2>
<h2>二、全球重大事件</h2>{global_items}
<h2>三、事实核查</h2>
<h2>四、国际关系观察</h2>
<h2>五、权威智库报告</h2>
<h2>六、国际战争观察</h2>
{market_html}
<h2>九、历史上的今天</h2>{history_items}
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

    def test_earnings_link_requires_today_and_first_party_domain(self):
        stale = '<a href="https://finance.yahoo.com/quote/AAPL">今日财报：2026-08-03｜官方公告链接</a>'
        errors = validator.validate(build_mail(extra_link=stale), date(2026, 8, 4))
        self.assertIn("earnings_discovery_link_present", errors)
        self.assertIn("earnings_link_date_not_today", errors)

        official = '<a href="https://www.sec.gov/Archives/edgar/data/320193/20260804/results.htm">官方公告</a>'
        self.assertNotIn(
            "earnings_official_domain_unapproved:sec.gov",
            validator.validate(
                build_mail(extra_link=f"今日财报：2026-08-04｜{official}"),
                date(2026, 8, 4),
            ),
        )

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
