from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from daily_brief_agent import source_collector as collector


class SourceCollectorParserTests(unittest.TestCase):
    def test_social_collectors_are_not_published(self):
        self.assertFalse(hasattr(collector, "collect_weibo"))
        self.assertFalse(hasattr(collector, "collect_x_trends"))

    def test_interleave_news_groups_prevents_one_source_dominating_the_front(self):
        groups = [
            [{"title": "A1"}, {"title": "A2"}],
            [{"title": "B1"}, {"title": "B2"}],
            [{"title": "C1"}],
        ]
        result = collector.interleave_news(groups, limit=10)
        self.assertEqual([item["title"] for item in result], ["A1", "B1", "C1", "A2", "B2"])

    def test_interleave_deduplicates_google_news_publisher_suffix(self):
        groups = [
            [{"title": "Major energy agreement reshapes regional supply"}],
            [{"title": "Major energy agreement reshapes regional supply - Reuters"}],
        ]
        result = collector.interleave_news(groups, limit=10)
        self.assertEqual(len(result), 1)

    def test_parse_rss_keeps_recent_items_and_direct_links(self):
        xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel><title>Example</title>
          <item><title>Recent global event</title><link>https://example.com/recent</link>
            <description>Useful summary</description><pubDate>Sat, 18 Jul 2026 05:30:00 GMT</pubDate></item>
          <item><title>Old event</title><link>https://example.com/old</link>
            <pubDate>Wed, 15 Jul 2026 05:30:00 GMT</pubDate></item>
        </channel></rss>"""
        now = datetime(2026, 7, 18, 7, 0, tzinfo=timezone.utc)
        items = collector.parse_feed(xml, "Example", "https://example.com/rss", now, 36)
        self.assertEqual([item["title"] for item in items], ["Recent global event"])
        self.assertEqual(items[0]["url"], "https://example.com/recent")
        self.assertEqual(items[0]["source"], "Example")

    def test_parse_aggregator_feed_prefers_external_original_link(self):
        xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <title>Useful product discovery</title>
            <link rel="alternate" href="https://hn.buzzing.cc/p/useful" />
            <link rel="related" href="https://news.ycombinator.com/item?id=123" />
            <summary>Translated discovery summary</summary>
            <published>2026-08-14T01:00:00Z</published>
          </entry>
        </feed>"""
        items = collector.parse_feed(
            xml,
            "Buzzing HN",
            "https://hn.buzzing.cc/feed.xml",
            datetime(2026, 8, 14, 2, tzinfo=timezone.utc),
            36,
            source_type="aggregator",
            prefer_external_link=True,
        )
        self.assertEqual(items[0]["url"], "https://news.ycombinator.com/item?id=123")
        self.assertEqual(items[0]["original_url"], "https://news.ycombinator.com/item?id=123")
        self.assertEqual(items[0]["feed_url"], "https://hn.buzzing.cc/feed.xml")
        self.assertEqual(items[0]["source_type"], "aggregator")

    def test_aggregator_without_external_link_has_no_original_url(self):
        xml = """<rss><channel><item>
          <title>Buzzing-only lead</title>
          <link>https://news.buzzing.cc/p/only-lead</link>
          <pubDate>Fri, 14 Aug 2026 01:00:00 GMT</pubDate>
        </item></channel></rss>"""
        items = collector.parse_feed(
            xml,
            "Buzzing News",
            "https://news.buzzing.cc/feed.xml",
            datetime(2026, 8, 14, 2, tzinfo=timezone.utc),
            36,
            source_type="aggregator",
            prefer_external_link=True,
        )
        self.assertIsNone(items[0]["original_url"])

    def test_aggregator_discovery_links_are_not_treated_as_original_sources(self):
        xml = """<rss><channel><item>
          <title>Aggregated report</title>
          <link>https://news.google.com/rss/articles/example</link>
          <pubDate>Fri, 14 Aug 2026 01:00:00 GMT</pubDate>
        </item></channel></rss>"""
        items = collector.parse_feed(
            xml,
            "Buzzing News",
            "https://news.buzzing.cc/feed.xml",
            datetime(2026, 8, 14, 2, tzinfo=timezone.utc),
            36,
            source_type="aggregator",
            prefer_external_link=True,
        )
        self.assertIsNone(items[0]["original_url"])

    def test_collect_buzzing_excludes_discovery_only_items_from_eligible_pool(self):
        feed_items = [
            {
                "source": "Buzzing News",
                "title": "Only a translated lead",
                "summary": "summary",
                "url": "https://news.buzzing.cc/lead",
                "original_url": None,
                "published_at": "2026-08-14T01:00:00Z",
            },
            {
                "source": "Buzzing HN",
                "title": "Original lead",
                "summary": "summary",
                "url": "https://example.org/original",
                "original_url": "https://example.org/original",
                "published_at": "2026-08-14T01:00:00Z",
            },
        ]
        with mock.patch.object(
            collector,
            "BUZZING_FEEDS",
            [("Buzzing News", "https://news.buzzing.cc/feed.xml", "world_affairs")],
        ), mock.patch.object(
            collector,
            "collect_feed_group",
            return_value={"sources": [{"source": "Buzzing News", "ok": True, "items": 2, "url": "https://news.buzzing.cc/feed.xml"}], "items": feed_items},
        ):
            result = collector.collect_buzzing(
                datetime(2026, 8, 14, tzinfo=timezone.utc),
                [],
                regular_items=[],
            )
        self.assertEqual([item["title"] for item in result["items"]], ["Original lead"])
        self.assertEqual([item["title"] for item in result["discovery_only"]], ["Only a translated lead"])

    def test_dedupe_supplemental_candidates_against_regular_news(self):
        regular = [{"title": "A new model launches", "url": "https://example.com/model"}]
        supplemental = [
            {
                "title": "A new model launches - Original",
                "url": "https://example.com/model",
                "original_url": "https://example.com/model",
            },
            {
                "title": "A separate lead",
                "url": "https://example.org/lead",
                "original_url": "https://example.org/lead",
            },
        ]
        result = collector.dedupe_supplemental_candidates(regular, supplemental)
        self.assertEqual([item["title"] for item in result], ["A separate lead"])

    def test_buzzing_failure_is_non_critical(self):
        errors: list[dict[str, str]] = []
        with mock.patch.object(collector, "BUZZING_FEEDS", [("Buzzing HN", "https://hn.buzzing.cc/feed.xml", "technology_science")]), mock.patch.object(
            collector,
            "collect_feed_group",
            side_effect=collector.FetchError("feed_down"),
        ):
            result = collector.collect_buzzing(
                datetime(2026, 8, 14, tzinfo=timezone.utc),
                errors,
                regular_items=[],
            )
        self.assertEqual(result["items"], [])
        self.assertTrue(any(error["section"] == "buzzing" for error in errors))

    def test_collect_all_keeps_buzzing_outside_regular_health_gate(self):
        regular_news = {
            "sources": [{"ok": True, "items": 1}] * 8,
            "lanes": [{"sources_ok": 1, "items": 40}] * 7,
            "items": [{"title": f"Regular {index}", "url": f"https://example.com/{index}"} for index in range(40)],
        }
        empty_group = {"sources": [], "items": []}
        market_items = [{"key": f"Market {index}"} for index in range(20)]
        buzzing = {
            "sources": [{"ok": True, "items": 1}],
            "items": [{"title": "Optional lead", "url": "https://example.org/optional"}],
            "selection_limit": 3,
            "enabled": True,
        }
        with mock.patch.object(collector, "collect_news", return_value=regular_news), mock.patch.object(
            collector, "collect_buzzing", return_value=buzzing
        ), mock.patch.object(collector, "collect_feed_group", return_value=empty_group), mock.patch.object(
            collector, "collect_markets", return_value={"items": market_items, "missing": [], "requested": 20}
        ):
            bundle = collector.collect_all(datetime(2026, 8, 14, tzinfo=timezone.utc))
        self.assertFalse(bundle["health"]["critical"])
        self.assertEqual(bundle["health"]["news_items"], 40)
        self.assertEqual(bundle["health"]["buzzing_items"], 1)

    def test_rendered_bundle_marks_buzzing_as_discovery_only(self):
        bundle = {
            "collected_at": "2026-08-14T01:00:00Z",
            "local_date": "2026-08-14",
            "health": {
                "news_sources_ok": 0,
                "news_lanes_ok": 0,
                "news_lanes_total": 0,
                "news_items": 0,
                "buzzing_sources_ok": 1,
                "buzzing_items": 1,
                "fact_check_items": 0,
                "think_tank_items": 0,
                "war_items": 0,
                "market_items": 0,
                "market_requested": 0,
            },
            "news": {"sources": [], "items": []},
            "buzzing": {
                "sources": [],
                "items": [{
                    "source": "Buzzing HN",
                    "source_type": "aggregator",
                    "title": "Discovery",
                    "summary": "Summary",
                    "url": "https://example.com/original",
                    "original_url": "https://example.com/original",
                    "feed_url": "https://hn.buzzing.cc/feed.xml",
                    "published_at": "2026-08-14T01:00:00Z",
                }],
            },
            "fact_checks": {"sources": [], "items": []},
            "think_tanks": {"sources": [], "items": []},
            "war": {"sources": [], "items": []},
            "markets": {"items": [], "missing": []},
            "errors": [],
        }
        rendered = collector.render_markdown(bundle)
        self.assertIn("非权威", rendered)
        self.assertIn("Discovery", rendered)
        self.assertIn("https://example.com/original", rendered)

    def test_runtime_source_sets_cover_fact_checks_think_tanks_and_war(self):
        fact_names = {name for name, _ in collector.FACT_CHECK_FEEDS}
        think_tank_names = {name for name, _ in collector.THINK_TANK_FEEDS}
        war_names = {name for name, _ in collector.WAR_FEEDS}
        self.assertIn("Snopes", fact_names)
        self.assertIn("Foreign Affairs", think_tank_names)
        self.assertIn("Brookings", think_tank_names)
        self.assertIn("The War Zone", war_names)
        self.assertIn("ISW discovery", war_names)
        self.assertIn("ACLED conflict monitor discovery", war_names)

    def test_news_lanes_cover_meaningful_cross_industry_topics(self):
        self.assertEqual(
            set(collector.NEWS_LANES),
            {
                "world_affairs",
                "business_economy",
                "technology_science",
                "health",
                "climate_energy",
                "industry_supply_chains",
                "agriculture_food",
                "regional_development",
                "sports",
                "culture_entertainment",
                "consumer_technology",
            },
        )
        for lane in collector.NEWS_LANES.values():
            self.assertGreaterEqual(len(lane["feeds"]), 4)
            self.assertTrue(lane["label"])

    def test_collect_news_adds_category_metadata_and_interleaves_lanes(self):
        lanes = {
            "first": {
                "label": "First lane",
                "max_age_hours": 48,
                "feeds": [("Source A", "https://example.com/a")],
            },
            "second": {
                "label": "Second lane",
                "max_age_hours": 72,
                "feeds": [("Source B", "https://example.com/b")],
            },
        }

        def fake_group(feeds, now, errors, **kwargs):
            name, url = feeds[0]
            return {
                "sources": [{"source": name, "ok": True, "items": 2, "url": url}],
                "items": [
                    {
                        "source": name,
                        "title": f"{name} one",
                        "summary": "",
                        "url": f"{url}/one",
                        "published_at": "2026-07-31T00:00:00Z",
                    },
                    {
                        "source": name,
                        "title": f"{name} two",
                        "summary": "",
                        "url": f"{url}/two",
                        "published_at": "2026-07-31T00:00:00Z",
                    },
                ],
            }

        with mock.patch.object(collector, "NEWS_LANES", lanes), mock.patch.object(
            collector, "collect_feed_group", side_effect=fake_group
        ):
            result = collector.collect_news(
                datetime(2026, 7, 31, tzinfo=timezone.utc),
                [],
            )

        self.assertEqual(
            [item["source"] for item in result["items"]],
            ["Source A", "Source B", "Source A", "Source B"],
        )
        self.assertEqual(
            [item["category"] for item in result["items"]],
            ["first", "second", "first", "second"],
        )
        self.assertEqual(result["lanes"][0]["label"], "First lane")
        self.assertEqual(result["lanes"][1]["sources_ok"], 1)

    def test_market_symbols_use_documentation_safe_default_basket(self):
        symbols = {item["key"]: item for item in collector.MARKET_SYMBOLS}
        self.assertEqual(symbols["Shanghai Composite"]["yahoo"], "000001.SS")
        self.assertEqual(symbols["Shenzhen Component"]["yahoo"], "399001.SZ")
        self.assertNotIn("SPCX", symbols)
        self.assertNotIn("SKHX", symbols)

    def test_rendered_bundle_has_new_sections_and_no_social_sections(self):
        empty_group = {"sources": [], "items": []}
        bundle = {
            "collected_at": "2026-07-28T03:00:00Z",
            "local_date": "2026-07-28",
            "health": {
                "news_sources_ok": 0,
                "news_items": 0,
                "fact_check_items": 0,
                "think_tank_items": 0,
                "war_items": 0,
                "market_items": 0,
                "market_requested": 0,
            },
            "news": empty_group,
            "fact_checks": empty_group,
            "think_tanks": empty_group,
            "war": empty_group,
            "markets": {"items": [], "missing": []},
            "errors": [],
        }
        output = collector.render_markdown(bundle)
        self.assertIn("## 事实核查候选", output)
        self.assertIn("## 权威智库报告候选", output)
        self.assertIn("## 国际战争观察候选", output)
        self.assertNotIn("微博当日结构化前十", output)
        self.assertNotIn("X 公开趋势快照", output)

    def test_parse_cnbc_includes_extended_market_and_status(self):
        payload = {
            "FormattedQuoteResult": {
                "FormattedQuote": [
                    {
                        "symbol": "AAPL",
                        "code": 0,
                        "name": "Apple Inc",
                        "last": "333.74",
                        "change": "+0.48",
                        "change_pct": "+0.14%",
                        "last_timedate": "07/17/26 EDT",
                        "curmktstatus": "POST_MKT",
                        "currencyCode": "USD",
                        "ExtendedMktQuote": {
                            "type": "POST_MKT",
                            "last": "333.69",
                            "change": "-0.05",
                            "change_pct": "-0.02%",
                        },
                    }
                ]
            }
        }
        result = collector.parse_cnbc_quotes(payload, {"AAPL": "AAPL"})
        self.assertEqual(result["AAPL"]["price"], "333.74")
        self.assertEqual(result["AAPL"]["market_status"], "POST_MKT")
        self.assertEqual(result["AAPL"]["extended"]["price"], "333.69")

    def test_parse_yahoo_computes_change_from_previous_close(self):
        payload = {
            "chart": {
                "result": [
                    {
                        "meta": {
                            "symbol": "AAPL",
                            "currency": "USD",
                            "regularMarketPrice": 333.74,
                            "chartPreviousClose": 333.26,
                            "regularMarketTime": 1784318401,
                            "exchangeTimezoneName": "America/New_York",
                        }
                    }
                ],
                "error": None,
            }
        }
        result = collector.parse_yahoo_quote(payload, "AAPL")
        self.assertAlmostEqual(result["change"], 0.48, places=2)
        self.assertAlmostEqual(result["change_pct"], 0.144, places=2)
        self.assertEqual(result["provider"], "Yahoo Finance chart")

    def test_parse_tencent_quotes_for_china_indexes(self):
        payload = (
            'v_sh000001="1~上证指数~000001~3560.00~3550.00~3540.00~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~'
            '20260804095845~10.00~0.28~3565.00~3535.00";\n'
            'v_sz399001="51~深证成指~399001~11200.00~11100.00~11050.00~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~0~'
            '20260804095844~100.00~0.90~11250.00~11000.00";'
        )
        result = collector.parse_tencent_quotes(
            payload,
            {"sh000001": "Shanghai Composite", "sz399001": "Shenzhen Component"},
        )
        self.assertEqual(result["Shanghai Composite"]["name"], "上证指数")
        self.assertEqual(result["Shanghai Composite"]["price"], 3560.0)
        self.assertEqual(result["Shanghai Composite"]["change_pct"], 0.28)
        self.assertEqual(result["Shanghai Composite"]["data_time"], "2026-08-04T09:58:45+08:00")
        self.assertEqual(result["Shenzhen Component"]["provider"], "Tencent quote")


if __name__ == "__main__":
    unittest.main()
