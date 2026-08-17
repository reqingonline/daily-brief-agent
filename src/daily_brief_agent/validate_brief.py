#!/usr/bin/env python3
"""Validate the generated daily brief before it is eligible for SMTP delivery."""

from __future__ import annotations

import argparse
from collections import Counter
import re
import sys
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
_ENGLISH_LEAK_PATTERNS = (
    re.compile(r"\breportedly\b", re.IGNORECASE),
    re.compile(r"\bas of (?:generation|writing) time\b", re.IGNORECASE),
    re.compile(r"\bawaits? approval\b", re.IGNORECASE),
    re.compile(r"\btop leadership\b", re.IGNORECASE),
    re.compile(r"\bchokepoint\b", re.IGNORECASE),
)


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _section_name(value: str) -> str:
    return re.sub(r"^\s*(?:[一二三四五六七八九十]+|\d+)\s*[、.．:]\s*", "", _clean(value))


class StructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict[str, Any]] = []
        self.links: list[str] = []
        self.visible_text: list[str] = []
        self._heading: str | None = None
        self._text: list[str] = []
        self._section: dict[str, Any] | None = None
        self._item: dict[str, Any] | None = None
        self._h3_links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "h2":
            self._heading = tag
            self._text = []
            self._section = None
            self._item = None
        elif tag == "h3":
            self._heading = tag
            self._text = []
            self._h3_links = []
        elif tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.links.append(href)
                if self._heading == "h3":
                    self._h3_links.append(href)
                elif self._item is not None:
                    self._item["links"].append(href)
        elif tag == "li" and self._section is not None:
            self._section["li_count"] += 1

    def handle_data(self, data: str) -> None:
        self.visible_text.append(data)
        if self._heading:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag != self._heading:
            return
        value = _clean("".join(self._text))
        if tag == "h2" and value:
            self._section = {
                "name": _section_name(value),
                "h3_count": 0,
                "li_count": 0,
                "items": [],
            }
            self.sections.append(self._section)
        elif tag == "h3" and value and self._section is not None:
            self._section["h3_count"] += 1
            self._item = {"title": value, "links": list(self._h3_links)}
            self._section["items"].append(self._item)
        self._heading = None
        self._text = []


def _find_section(sections: list[dict[str, Any]], name: str) -> tuple[int, dict[str, Any] | None]:
    for index, section in enumerate(sections):
        if name in section["name"]:
            return index, section
    return -1, None


def _item_hosts(section: dict[str, Any]) -> tuple[list[set[str]], set[str]]:
    item_hosts: list[set[str]] = []
    all_hosts: set[str] = set()
    for item in section.get("items", []):
        hosts: set[str] = set()
        for link in item.get("links", []):
            try:
                host = (urlparse(str(link)).hostname or "").casefold().removeprefix("www.")
            except ValueError:
                host = ""
            if host:
                hosts.add(host)
        item_hosts.append(hosts)
        all_hosts.update(hosts)
    return item_hosts, all_hosts


def _title_key(value: str) -> str:
    value = re.sub(r"\s*续报\s*", "", value, flags=re.IGNORECASE)
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", value.casefold())


def _source_quality_errors(section_name: str, section: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    item_hosts, all_hosts = _item_hosts(section)
    item_count = len(item_hosts)
    if item_count >= 5 and len(all_hosts) < 6:
        errors.append(f"source_diversity_low:{section_name}:{len(all_hosts)}")

    host_counts = Counter(host for hosts in item_hosts for host in hosts)
    if any(count > 3 for count in host_counts.values()):
        errors.append(f"source_concentration_exceeded:{section_name}")

    seen_titles: set[str] = set()
    for item in section.get("items", []):
        key = _title_key(str(item.get("title", "")))
        if key and key in seen_titles:
            errors.append(f"duplicate_item_title:{section_name}")
            break
        if key:
            seen_titles.add(key)
    return errors


def validate(content: str, local_date: date) -> list[str]:
    errors: list[str] = []
    subject_match = re.search(
        r"(?m)^Subject:\s*每日大事与市场简报\s*-\s*\d{4}-\d{2}-\d{2}\s+(?P<hour>\d{2}):\d{2}\s+中国时间\s*$",
        content,
    )
    if not subject_match:
        errors.append("subject_format_invalid")
    if not re.search(r"<html\b", content, flags=re.IGNORECASE) or not re.search(r"</html>\s*$", content, flags=re.IGNORECASE):
        errors.append("html_document_incomplete")

    parser = StructureParser()
    parser.feed(content)
    history_suppressed = subject_match is not None and subject_match.group("hour") == "23"
    required = ("本期 5 个要点", "全球重大事件", "国际关系观察", "权威智库报告", "国际战争观察")
    if not history_suppressed:
        required += ("历史上的今天",)
    for name in required:
        if _find_section(parser.sections, name)[1] is None:
            errors.append(f"required_section_missing:{name}")

    _, global_section = _find_section(parser.sections, "全球重大事件")
    global_count = global_section["h3_count"] if global_section else 0
    if not 1 <= global_count <= 15:
        errors.append(f"global_event_count:{global_count}_not_in_1_15")

    history_index, history_section = _find_section(parser.sections, "历史上的今天")
    if history_suppressed:
        if history_section is not None:
            errors.append("history_section_forbidden_at_23")
    else:
        history_count = max(history_section["h3_count"], history_section["li_count"]) if history_section else 0
        if not 3 <= history_count <= 5:
            errors.append(f"history_event_count:{history_count}_not_in_3_5")
    method_index, _ = _find_section(parser.sections, "数据与方法说明")
    if method_index >= 0 and history_index >= method_index:
        errors.append("history_not_before_method_footer")

    market_present = _find_section(parser.sections, "市场总览")[1] is not None
    stocks_present = _find_section(parser.sections, "股票与指数")[1] is not None
    if local_date.weekday() < 5 and not (market_present and stocks_present):
        errors.append("weekday_market_sections_missing")

    if any("news.google.com" in link.casefold() for link in parser.links):
        errors.append("google_news_link_present")
    if any("X 平台" in section["name"] or "微博" in section["name"] for section in parser.sections):
        errors.append("cancelled_social_section_present")
    if re.search(r"作者\s*[：:]\s*[^<\n]{0,30}(?:编辑与研究团队|研究团队|作者不详|未知作者)", content):
        errors.append("think_tank_author_placeholder")
    visible_text = "".join(parser.visible_text)
    if any(pattern.search(visible_text) for pattern in _ENGLISH_LEAK_PATTERNS):
        errors.append("english_leak_present")
    if global_section:
        errors.extend(_source_quality_errors("全球重大事件", global_section))
    _, war_section = _find_section(parser.sections, "国际战争观察")
    if war_section:
        errors.extend(_source_quality_errors("国际战争观察", war_section))
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message", type=Path)
    parser.add_argument("--date", help="Asia/Shanghai date in YYYY-MM-DD format")
    args = parser.parse_args(argv)
    local_date = date.fromisoformat(args.date) if args.date else datetime.now(SHANGHAI).date()
    try:
        content = args.message.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        print(f"brief_validation_error=message_read_failed:{type(exc).__name__}", file=sys.stderr)
        return 2
    errors = validate(content, local_date)
    if errors:
        for error in errors:
            print(f"brief_validation_error={error}", file=sys.stderr)
        return 1
    print("brief_validation=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
