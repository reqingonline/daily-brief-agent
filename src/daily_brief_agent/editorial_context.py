#!/usr/bin/env python3
"""Build trusted edition context from sent briefs and on-this-day candidates."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
LATE_EDITION_START_HOUR = 17
USER_AGENT = "DailyBriefEditorialContext/1.0 (private email automation)"


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def _section_name(value: str) -> str:
    value = re.sub(r"^\s*(?:[一二三四五六七八九十]+|\d+)\s*[、.．:]\s*", "", value)
    return _clean(value)


def _item_title(value: str) -> str:
    value = re.sub(r"^\s*[\[【][^\]】]{1,40}[\]】]\s*", "", value)
    value = re.sub(r"^\s*[^0-9]{2,40}\d+\s*[.、．:]\s*", "", value)
    value = re.sub(r"^\s*\d+\s*[.、．:]\s*", "", value)
    value = re.sub(r"^\s*[\[【][^\]】]{1,40}[\]】]\s*", "", value)
    return _clean(value)


class BriefParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sections: list[dict[str, Any]] = []
        self.links: list[str] = []
        self._heading: str | None = None
        self._heading_text: list[str] = []
        self._section: dict[str, Any] | None = None
        self._item: dict[str, Any] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"h2", "h3"}:
            if tag == "h2":
                self._section = None
                self._item = None
            self._heading = tag
            self._heading_text = []
        elif tag == "a":
            href = dict(attrs).get("href")
            if href and href.startswith(("http://", "https://")):
                self.links.append(href)
                if self._section is not None and href not in self._section["links"]:
                    self._section["links"].append(href)
                if self._item is not None and href not in self._item["links"]:
                    self._item["links"].append(href)

    def handle_data(self, data: str) -> None:
        if self._heading:
            self._heading_text.append(data)
        elif self._section is not None:
            self._section["text_parts"].append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag != self._heading:
            return
        value = _clean("".join(self._heading_text))
        if tag == "h2" and value:
            self._section = {"name": _section_name(value), "items": [], "links": [], "text_parts": []}
            self.sections.append(self._section)
            self._item = None
        elif tag == "h3" and value and self._section is not None:
            self._item = {"title": _item_title(value), "links": []}
            self._section["items"].append(self._item)
        self._heading = None
        self._heading_text = []


def parse_brief(content: str, filename: str = "") -> dict[str, Any]:
    subject_match = re.search(r"(?m)^Subject:\s*(.+?)\s*$", content)
    parser = BriefParser()
    parser.feed(content)
    for section in parser.sections:
        section["text"] = _clean(" ".join(section.pop("text_parts")))[:2400]
    return {
        "filename": filename,
        "subject": _clean(subject_match.group(1)) if subject_match else "（主题缺失）",
        "sections": parser.sections,
        "links": list(dict.fromkeys(parser.links)),
    }


def recent_message_files(log_dir: Path, limit: int = 14) -> list[Path]:
    sent = sorted(log_dir.glob("sent-message-*.md"), reverse=True)
    if not sent:
        return sorted(log_dir.glob("last-message-*.md"), reverse=True)[:limit]
    selected = sent[:limit]
    seen_stamps = {path.stem.removeprefix("sent-message-") for path in selected}
    oldest_sent_stamp = min(seen_stamps)
    for path in sorted(log_dir.glob("last-message-*.md"), reverse=True):
        stamp = path.stem.removeprefix("last-message-")
        if stamp in seen_stamps or stamp >= oldest_sent_stamp:
            continue
        selected.append(path)
        seen_stamps.add(stamp)
        if len(selected) >= limit:
            break
    return selected


def edition_context(now: datetime | None = None) -> dict[str, Any]:
    now = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    weekend = now.weekday() >= 5
    edition = "早间版" if now.hour < LATE_EDITION_START_HOUR else "晚间版"
    if weekend:
        market_rule = "weekend_omit"
        market_note = "北京周末：默认省略市场总览和股票表格，只在发生重大公司或宏观事件时写非报价型财经新闻。"
    elif edition == "早间版":
        market_rule = "weekday_morning"
        market_note = "工作日早间版：A 股和港股尚未开盘，使用最近有效收盘；美股使用上一交易日收盘或可靠盘前数据，并逐项标明状态。"
    else:
        market_rule = "weekday_evening"
        market_note = "工作日晚间版：A 股和港股使用当日收盘；美股通常处于盘前或盘中，并逐项标明状态。"
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "local_date": now.date().isoformat(),
        "weekday": now.strftime("%A"),
        "is_weekend": weekend,
        "edition": edition,
        "market_rule": market_rule,
        "market_note": market_note,
    }


def fetch_json(url: str, timeout: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json", "Accept-Encoding": "identity"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        value = json.loads(response.read(3_000_000).decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("history_json_root_not_object")
    return value


def _event_key(event: dict[str, Any]) -> tuple[Any, ...]:
    year = event.get("year")
    for page in event.get("pages") or []:
        item = page.get("wikibase_item") if isinstance(page, dict) else None
        if item:
            return year, item
    text = re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", str(event.get("text") or "").casefold())
    return year, text[:160]


def _compact_pages(pages: Any) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    if not isinstance(pages, list):
        return result
    for page in pages[:3]:
        if not isinstance(page, dict):
            continue
        desktop = page.get("content_urls", {}).get("desktop", {}) if isinstance(page.get("content_urls"), dict) else {}
        result.append(
            {
                "title": _clean(str(page.get("title") or "")),
                "url": str(desktop.get("page") or ""),
                "wikibase_item": str(page.get("wikibase_item") or ""),
            }
        )
    return result


def fetch_history_candidates(now: datetime | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    now = (now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
    path = now.strftime("%m/%d")
    combined: dict[tuple[Any, ...], dict[str, Any]] = {}
    errors: list[str] = []
    for language in ("zh", "en"):
        url = f"https://api.wikimedia.org/feed/v1/wikipedia/{language}/onthisday/events/{path}"
        try:
            payload = fetch_json(url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(f"{language}:{type(exc).__name__}")
            continue
        for raw in payload.get("events") or []:
            if not isinstance(raw, dict) or not isinstance(raw.get("year"), int) or not raw.get("text"):
                continue
            event = {
                "year": raw["year"],
                "text": _clean(str(raw["text"]))[:700],
                "languages": [language],
                "pages": _compact_pages(raw.get("pages")),
            }
            key = _event_key(raw)
            if key in combined:
                combined[key]["languages"].append(language)
                existing_urls = {page["url"] for page in combined[key]["pages"]}
                combined[key]["pages"].extend(page for page in event["pages"] if page["url"] not in existing_urls)
            else:
                combined[key] = event
    events = sorted(combined.values(), key=lambda item: item["year"], reverse=True)
    return events[:80], errors


def render_context(
    edition: dict[str, Any],
    briefs: list[dict[str, Any]],
    history_events: list[dict[str, Any]],
    history_errors: list[str],
) -> str:
    lines = [
        "# 本期编辑上下文",
        "",
        f"- 生成时点（Asia/Shanghai）：{edition['generated_at']}",
        f"- 版本：{edition['edition']}",
        f"- 行情规则：{edition['market_rule']}；{edition['market_note']}",
        "- 去重窗口：新闻与战争：72 小时；事实核查与智库：7 天。",
        "- 续报条件：必须有实质新增，并在标题标注“续报”，首句明确本期新增事实。",
        "",
        "## 最近已发送内容",
        "",
        "以下内容用于避免复读，不代表本期仍应刊登。链接或标题命中去重窗口时默认排除。",
    ]
    if not briefs:
        lines.append("- 尚无可用的已发送邮件记录。")
    for brief_index, brief in enumerate(briefs):
        relevant = (
            ("全球重大事件", "事实核查", "权威智库报告", "国际战争观察")
            if brief_index < 6
            else ("事实核查", "权威智库报告")
        )
        lines.extend(["", f"### {brief['subject']}"])
        item_count = 0
        for section in brief["sections"]:
            if not any(name in section["name"] for name in relevant):
                continue
            for item in section["items"]:
                links = " ".join(item["links"][:3]) or "（无链接）"
                lines.append(f"- [{section['name']}] {item['title']} | {links}")
                item_count += 1
                if item_count >= 30:
                    break
            if not section["items"] and (section.get("text") or section.get("links")):
                summary = section.get("text", "")[:500] or "（旧版无条目标题）"
                links = " ".join(section.get("links", [])[:12]) or "（无链接）"
                lines.append(f"- [{section['name']}｜旧版段落] {summary} | {links}")
                item_count += 1
            if item_count >= 30:
                break
    lines.extend(
        [
            "",
            "## 历史上的今天候选",
            "",
            "候选来自 Wikimedia On This Day API，仅用于发现。最终选中的 3 至 5 条仍须用图书馆、档案馆、博物馆、百科全书、NASA 或其他权威原文核验。",
        ]
    )
    if history_errors:
        lines.append("- 候选接口降级：" + "、".join(history_errors))
    for event in history_events:
        pages = "；".join(
            f"{page['title']} {page['url']}".strip() for page in event["pages"][:3] if page.get("title") or page.get("url")
        ) or "无页面链接"
        lines.append(f"- {event['year']}：{event['text']}（语言：{'/'.join(event['languages'])}；页面：{pages}）")
    lines.append("")
    return "\n".join(lines)


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_name: str | None = None
    try:
        with NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False) as handle:
            temp_name = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        temp_name = None
    finally:
        if temp_name:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=14)
    parser.add_argument("--now", help="ISO timestamp for deterministic tests")
    args = parser.parse_args(argv)
    now = datetime.fromisoformat(args.now).astimezone(SHANGHAI) if args.now else datetime.now(SHANGHAI)
    briefs = []
    for path in recent_message_files(args.logs_dir, max(1, min(args.limit, 20))):
        try:
            briefs.append(parse_brief(path.read_text(encoding="utf-8"), path.name))
        except (OSError, UnicodeError):
            continue
    history, errors = fetch_history_candidates(now)
    write_atomic(args.output, render_context(edition_context(now), briefs, history, errors))
    print(f"editorial_context=briefs:{len(briefs)} history:{len(history)} errors:{len(errors)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
