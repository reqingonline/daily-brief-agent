"""Small, fail-closed adapters for next earnings dates and official releases.

The calendar provider is used for date discovery only.  A link is emitted only
when an independently supplied filing record proves that the release happened
on the current Asia/Shanghai date and the URL belongs to a configured first-
party domain.  This keeps an estimated date from turning into a stale or
aggregated citation in the daily brief.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
import re
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
NASDAQ_EARNINGS_URL = "https://api.nasdaq.com/api/analyst/{symbol}/earnings-date"
SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVE_URL = "https://www.sec.gov/Archives/edgar/data/{cik_number}/{accession}/{document}"

_DATE_PATTERNS = (
    re.compile(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},\s+\d{4}\b", re.I),
    re.compile(r"\b\d{1,2}/\d{1,2}/\d{4}\b"),
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),
)
_SEC_EARNINGS_FORMS = {"10-K", "10-Q", "20-F"}


@dataclass(frozen=True)
class EarningsRecord:
    """The only fields the renderer needs for one watched company."""

    key: str
    display_name: str
    market: str
    next_date: str | None
    date_status: str
    today_expected: bool
    today_release: bool
    official_link: str | None
    announcement_date: str | None
    source_name: str
    source_url: str | None
    status: str
    detail: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _date_from_text(value: str) -> date | None:
    value = value.strip()
    for pattern in _DATE_PATTERNS:
        match = pattern.search(value)
        if not match:
            continue
        candidate = match.group(0)
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    return None


def _date_value(value: Any) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.astimezone(SHANGHAI).date() if value.tzinfo else value.date()
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).astimezone(SHANGHAI).date()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        return _date_from_text(value)
    return None


def _future_date(candidates: list[date], local_date: date) -> date | None:
    future = sorted({candidate for candidate in candidates if candidate >= local_date})
    return future[0] if future else None


def _official_host_allowed(url: str, allowed_domains: tuple[str, ...]) -> bool:
    parsed = urlsplit(url.strip())
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        return False
    host = parsed.hostname.casefold().rstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in allowed_domains)


def gate_official_link(
    url: str | None,
    *,
    announcement_date: date | None,
    local_date: date,
    allowed_domains: tuple[str, ...],
    today_release: bool,
    link_checker: Callable[[str], bool] | None = None,
) -> str | None:
    """Return a link only when every same-day and first-party check passes."""

    if not url or not today_release or announcement_date != local_date:
        return None
    if not _official_host_allowed(url, allowed_domains):
        return None
    if link_checker is not None and not link_checker(url):
        return None
    return url.strip()


def parse_nasdaq_earnings_date(
    payload: Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    local_date: date,
) -> dict[str, Any]:
    """Parse Nasdaq's public analyst-date response without inventing a date."""

    data = payload.get("data")
    if not isinstance(data, Mapping):
        raise ValueError("nasdaq_earnings_data_missing")
    announcement = str(data.get("announcement") or "")
    report_text = str(data.get("reportText") or "")
    candidates: list[date] = []
    for text in (announcement, report_text):
        for pattern in _DATE_PATTERNS:
            candidates.extend(
                candidate
                for candidate in (_date_value(match.group(0)) for match in pattern.finditer(text))
                if candidate is not None
            )
    next_date = _future_date(candidates, local_date)
    provider_symbol = str(item.get("provider_symbol") or item.get("key") or "")
    source_url = NASDAQ_EARNINGS_URL.format(symbol=provider_symbol)
    if next_date is None:
        return {
            "next_date": None,
            "date_status": "unavailable",
            "source_name": "Nasdaq/Zacks earnings date",
            "source_url": source_url,
            "detail": "provider_did_not_supply_future_date",
        }
    return {
        "next_date": next_date,
        "date_status": "estimated",
        "source_name": "Nasdaq/Zacks earnings date",
        "source_url": source_url,
        "detail": report_text[:220] if report_text else None,
    }


def _sec_rows(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    filings = payload.get("filings")
    recent = filings.get("recent") if isinstance(filings, Mapping) else None
    if not isinstance(recent, Mapping):
        return []
    keys = (
        "filingDate",
        "form",
        "accessionNumber",
        "primaryDocument",
        "items",
    )
    length = max((len(recent.get(key, [])) for key in keys if isinstance(recent.get(key), list)), default=0)
    rows: list[dict[str, Any]] = []
    for index in range(length):
        rows.append({key: recent.get(key, [None] * length)[index] if isinstance(recent.get(key), list) and index < len(recent[key]) else None for key in keys})
    return rows


def find_sec_official_release(
    payload: Mapping[str, Any],
    item: Mapping[str, Any],
    *,
    local_date: date,
    link_checker: Callable[[str], bool] | None = None,
) -> dict[str, Any] | None:
    """Find a same-day SEC earnings filing and apply the first-party gate."""

    cik = str(item.get("sec_cik") or "").lstrip("0")
    if not cik.isdigit():
        return None
    padded_cik = cik.zfill(10)
    allowed_domains = tuple(item.get("official_domains") or ("sec.gov",))
    for row in _sec_rows(payload):
        filing_date = _date_value(row.get("filingDate"))
        if filing_date != local_date:
            continue
        form = str(row.get("form") or "").upper()
        items = str(row.get("items") or "")
        document = str(row.get("primaryDocument") or "")
        is_earnings = form in _SEC_EARNINGS_FORMS
        if form == "8-K":
            is_earnings = "2.02" in items
        elif form == "6-K":
            is_earnings = bool(re.search(r"earnings|results|financial", document, re.I))
        if not is_earnings or not document or not re.fullmatch(r"[A-Za-z0-9._-]+", document):
            continue
        accession_number = str(row.get("accessionNumber") or "")
        accession = accession_number.replace("-", "")
        if not re.fullmatch(r"\d{18}", accession):
            continue
        url = SEC_ARCHIVE_URL.format(
            cik_number=int(cik),
            accession=accession,
            document=document,
        )
        link = gate_official_link(
            url,
            announcement_date=filing_date,
            local_date=local_date,
            allowed_domains=allowed_domains,
            today_release=True,
            link_checker=link_checker,
        )
        if link:
            return {
                "announcement_date": filing_date,
                "official_link": link,
                "source_name": "SEC filing",
                "source_url": link,
            }
    return None


def _unavailable(item: Mapping[str, Any], *, source_name: str, source_url: str | None, detail: str | None) -> EarningsRecord:
    return EarningsRecord(
        key=str(item["key"]),
        display_name=str(item.get("display_name") or item["key"]),
        market=str(item.get("market") or "unknown"),
        next_date=None,
        date_status="unavailable",
        today_expected=False,
        today_release=False,
        official_link=None,
        announcement_date=None,
        source_name=source_name,
        source_url=source_url,
        status="unavailable",
        detail=detail,
    )


def collect_earnings(
    watchlist: list[Mapping[str, Any]],
    now: datetime,
    *,
    fetch_json: Callable[[str], Mapping[str, Any]],
    fetch_optional_json: Callable[[str], Mapping[str, Any]] | None = None,
    errors: list[dict[str, str]] | None = None,
    link_checker: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Collect one record per watched stock; one provider failure is isolated."""

    errors = errors if errors is not None else []
    local_date = now.astimezone(SHANGHAI).date()
    records: list[EarningsRecord] = []
    for item in watchlist:
        key = str(item.get("key") or "")
        market = str(item.get("market") or "").upper()
        if not key:
            continue
        provider_symbol = str(item.get("provider_symbol") or key)
        if market != "US":
            records.append(
                _unavailable(
                    item,
                    source_name="未配置可靠财报日历",
                    source_url=None,
                    detail="market_provider_not_configured",
                )
            )
            continue
        source_url = NASDAQ_EARNINGS_URL.format(symbol=provider_symbol)
        try:
            parsed = parse_nasdaq_earnings_date(
                fetch_json(source_url),
                item,
                local_date=local_date,
            )
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append({"section": "earnings", "source": key, "error": f"provider_failed:{type(exc).__name__}"})
            records.append(
                _unavailable(
                    item,
                    source_name="Nasdaq/Zacks earnings date",
                    source_url=source_url,
                    detail=f"provider_failed:{type(exc).__name__}",
                )
            )
            continue

        next_date = parsed.get("next_date")
        today_expected = next_date == local_date
        official_link: str | None = None
        announcement_date: date | None = None
        today_release = False
        official_release = item.get("official_release")
        if today_expected and isinstance(official_release, Mapping):
            announcement_date = _date_value(official_release.get("announcement_date"))
            candidate_url = str(official_release.get("url") or "")
            official_link = gate_official_link(
                candidate_url,
                announcement_date=announcement_date,
                local_date=local_date,
                allowed_domains=tuple(item.get("official_domains") or ()),
                today_release=True,
                link_checker=link_checker,
            )
            today_release = official_link is not None

        if today_expected and not today_release and item.get("sec_cik") and fetch_optional_json:
            cik = str(item["sec_cik"]).lstrip("0")
            if cik.isdigit():
                sec_url = SEC_SUBMISSIONS_URL.format(cik=cik.zfill(10))
                try:
                    sec_release = find_sec_official_release(
                        fetch_optional_json(sec_url),
                        item,
                        local_date=local_date,
                        link_checker=link_checker,
                    )
                except (OSError, ValueError, TypeError, KeyError) as exc:
                    errors.append({"section": "earnings_official", "source": key, "error": f"sec_failed:{type(exc).__name__}"})
                    sec_release = None
                if sec_release:
                    announcement_date = sec_release["announcement_date"]
                    official_link = sec_release["official_link"]
                    today_release = True

        records.append(
            EarningsRecord(
                key=key,
                display_name=str(item.get("display_name") or key),
                market=market,
                next_date=next_date.isoformat() if isinstance(next_date, date) else None,
                date_status=str(parsed.get("date_status") or "unavailable"),
                today_expected=today_expected,
                today_release=today_release,
                official_link=official_link,
                announcement_date=announcement_date.isoformat() if announcement_date else None,
                source_name=str(parsed.get("source_name") or "财报日历"),
                source_url=str(parsed.get("source_url") or source_url),
                status="ok" if next_date else "unavailable",
                detail=str(parsed.get("detail") or "")[:220] or None,
            )
        )
    return {
        "items": [record.as_dict() for record in records],
        "requested": len(watchlist),
        "available": sum(1 for record in records if record.status == "ok"),
    }
