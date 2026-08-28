from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

from daily_brief_agent.earnings_calendar import (
    collect_earnings,
    find_sec_official_release,
    gate_official_link,
    parse_nasdaq_earnings_date,
)


class EarningsCalendarTests(unittest.TestCase):
    def test_nasdaq_parser_keeps_next_future_date_and_marks_estimate(self):
        item = {"key": "NVDA", "provider_symbol": "NVDA"}
        result = parse_nasdaq_earnings_date(
            {
                "data": {
                    "announcement": "Earnings announcement* for NVDA: Aug 26, 2026",
                    "reportText": "Expected to report earnings on 08/26/2026 after market close.",
                }
            },
            item,
            local_date=date(2026, 8, 21),
        )
        self.assertEqual(result["next_date"], date(2026, 8, 26))
        self.assertEqual(result["date_status"], "estimated")

    def test_nasdaq_parser_does_not_retain_a_past_date(self):
        result = parse_nasdaq_earnings_date(
            {"data": {"announcement": "Earnings announcement for AAPL: Jul 30, 2026", "reportText": ""}},
            {"key": "AAPL", "provider_symbol": "AAPL"},
            local_date=date(2026, 8, 21),
        )
        self.assertIsNone(result["next_date"])
        self.assertEqual(result["date_status"], "unavailable")

    def test_official_link_gate_rejects_old_or_aggregated_links(self):
        today = date(2026, 8, 21)
        self.assertIsNone(
            gate_official_link(
                "https://sec.gov/Archives/edgar/data/1/20260820/results.htm",
                announcement_date=date(2026, 8, 20),
                local_date=today,
                allowed_domains=("sec.gov",),
                today_release=True,
            )
        )
        self.assertIsNone(
            gate_official_link(
                "https://news.google.com/rss/articles/example",
                announcement_date=today,
                local_date=today,
                allowed_domains=("sec.gov",),
                today_release=True,
            )
        )
        self.assertEqual(
            gate_official_link(
                "https://sec.gov/Archives/edgar/data/1/20260821/results.htm",
                announcement_date=today,
                local_date=today,
                allowed_domains=("sec.gov",),
                today_release=True,
                link_checker=lambda url: url.endswith("results.htm"),
            ),
            "https://sec.gov/Archives/edgar/data/1/20260821/results.htm",
        )

    def test_sec_filing_parser_accepts_same_day_8k_item_202(self):
        payload = {
            "filings": {
                "recent": {
                    "filingDate": ["2026-08-21"],
                    "form": ["8-K"],
                    "items": ["2.02,9.01"],
                    "accessionNumber": ["0000320193-26-000001"],
                    "primaryDocument": ["earnings.htm"],
                }
            }
        }
        result = find_sec_official_release(
            payload,
            {"key": "AAPL", "sec_cik": "0000320193", "official_domains": ("sec.gov",)},
            local_date=date(2026, 8, 21),
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["announcement_date"], date(2026, 8, 21))
        self.assertIn("/Archives/edgar/data/320193/000032019326000001/earnings.htm", result["official_link"])

    def test_collect_isolates_non_us_and_provider_failures(self):
        calls: list[str] = []

        def fake_fetch(url: str):
            calls.append(url)
            if "BROKEN" in url:
                raise ValueError("provider down")
            return {"data": {"announcement": "", "reportText": ""}}

        errors: list[dict[str, str]] = []
        result = collect_earnings(
            [
                {"key": "02513.HK", "display_name": "智谱（Z.AI）", "market": "HK"},
                {"key": "BROKEN", "provider_symbol": "BROKEN", "display_name": "Broken", "market": "US"},
            ],
            datetime(2026, 8, 21, 2, tzinfo=timezone.utc),
            fetch_json=fake_fetch,
            errors=errors,
        )
        self.assertEqual(result["requested"], 2)
        self.assertEqual(result["available"], 0)
        self.assertEqual(result["items"][0]["status"], "unavailable")
        self.assertEqual(result["items"][1]["detail"], "provider_failed:ValueError")
        self.assertTrue(any(error["section"] == "earnings" for error in errors))
        self.assertEqual(len(calls), 1)

    def test_collect_attaches_sec_link_only_for_a_same_day_release(self):
        def fake_calendar(_url: str):
            return {
                "data": {
                    "announcement": "Earnings announcement* for NVDA: Aug 21, 2026",
                    "reportText": "Expected to report earnings today.",
                }
            }

        def fake_sec(_url: str):
            return {
                "filings": {
                    "recent": {
                        "filingDate": ["2026-08-21"],
                        "form": ["8-K"],
                        "items": ["2.02,9.01"],
                        "accessionNumber": ["0001045810-26-000001"],
                        "primaryDocument": ["quarterly-results.htm"],
                    }
                }
            }

        result = collect_earnings(
            [{
                "key": "NVDA",
                "provider_symbol": "NVDA",
                "display_name": "英伟达",
                "market": "US",
                "sec_cik": "0001045810",
                "official_domains": ("sec.gov",),
            }],
            datetime(2026, 8, 21, 2, tzinfo=timezone.utc),
            fetch_json=fake_calendar,
            fetch_optional_json=fake_sec,
        )
        record = result["items"][0]
        self.assertTrue(record["today_release"])
        self.assertEqual(record["announcement_date"], "2026-08-21")
        self.assertIn("sec.gov/Archives/edgar/data/1045810/", record["official_link"])


if __name__ == "__main__":
    unittest.main()
