# Buzzing Candidate Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Buzzing as a bounded, non-critical discovery pool that can improve the next daily brief without creating a Buzzing email section or weakening existing quality gates.

**Architecture:** Extend the existing feed parser with explicit aggregator metadata and external-link selection. Collect a small set of Buzzing category feeds separately, deduplicate them against regular news by normalized URL/title, and pass them to the model as optional candidates capped at three selections. A production switch and failure isolation keep Buzzing reversible and outside the regular source-health gate.

**Tech Stack:** Python 3.11+ standard library, unittest, Bash/systemd, SSH/SCP to the existing AWS VPS, Markdown configuration, Git/GitHub.

---

## Scope Lock

- Buzzing is optional discovery data, not an authority.
- The first production feed set is limited to `hn.buzzing.cc`, `ph.buzzing.cc`, `news.buzzing.cc`, and `nytimes.buzzing.cc` RSS feeds; the aggregate JSON endpoint is not used.
- A Buzzing item is eligible for model selection only when a non-Buzzing original URL is available.
- The model may select zero to three items and must merge them into existing sections; no final Buzzing section is added.
- Buzzing failure cannot set `health.critical`, cannot reduce the 11-lane regular-news count, and cannot bypass validation or SMTP gates.
- No Weibo/X collectors, crypto-only coverage, schedule, recipient, SMTP, validator, or subscription changes.
- The public repository is not pushed before the next real email is reviewed. Local commits may be used to stage and deploy the implementation; publication follows the observed result.

## File Map

- Modify `src/daily_brief_agent/source_collector.py`: feed-link normalization, aggregator parsing, candidate deduplication, Buzzing collection, bundle health, evidence rendering, and CLI marker.
- Modify `config/codex-runtime.env.example`: document the opt-out switch.
- Modify `config/source-policy.txt`: state the Buzzing trust boundary and original-link requirement.
- Modify `config/brief-prompt.txt`: give the model the optional-selection contract and three-item cap.
- Modify `tests/test_source_collector.py`: add fixtures for links, deduplication, failure isolation, and rendering.
- Modify `README.md`: document the optional source and opt-out behavior.
- Modify `docs/model-design.md`: document aggregator input separation and non-critical semantics.
- Add no runtime state, generated mail, logs, credentials, subscriber data, or VPS details to Git.

## Task 1: Add failing parser and candidate-pool tests

**Files:**

- Test: `D:/documents/qqfarm/daily-brief-agent/tests/test_source_collector.py`

- [ ] **Step 1: Add a Buzzing Atom fixture test before implementation**

Add a test that requires an external original link to be preserved separately
from the Buzzing feed URL:

```python
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
```

- [ ] **Step 2: Add failing tests for missing originals and cross-pool deduplication**

Add tests requiring missing originals to remain ineligible and a duplicate to
be removed against regular news:

```python
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

    def test_dedupe_supplemental_candidates_against_regular_news(self):
        regular = [{"title": "A new model launches", "url": "https://example.com/model"}]
        supplemental = [
            {"title": "A new model launches - Original", "url": "https://example.com/model", "original_url": "https://example.com/model"},
            {"title": "A separate lead", "url": "https://example.org/lead", "original_url": "https://example.org/lead"},
        ]
        result = collector.dedupe_supplemental_candidates(regular, supplemental)
        self.assertEqual([item["title"] for item in result], ["A separate lead"])
```

- [ ] **Step 3: Add failing tests for non-critical collection failure and evidence rendering**

Add tests that patch the feed group and assert Buzzing errors do not make the
health gate critical, while the evidence bundle labels the source correctly:

```python
    def test_buzzing_failure_is_non_critical(self):
        errors = []
        with mock.patch.object(
            collector,
            "collect_feed_group",
            side_effect=lambda *args, **kwargs: (_ for _ in ()).throw(collector.FetchError("feed_down")),
        ):
            result = collector.collect_buzzing(
                datetime(2026, 8, 14, tzinfo=timezone.utc),
                errors,
                regular_items=[],
            )
        self.assertEqual(result["items"], [])
        self.assertTrue(any(error["section"] == "buzzing" for error in errors))

    def test_rendered_bundle_marks_buzzing_as_discovery_only(self):
        bundle = {
            "collected_at": "2026-08-14T01:00:00Z",
            "local_date": "2026-08-14",
            "health": {
                "news_sources_ok": 0, "news_lanes_ok": 0, "news_lanes_total": 0,
                "news_items": 0, "buzzing_sources_ok": 1, "buzzing_items": 1,
                "fact_check_items": 0, "think_tank_items": 0, "war_items": 0,
                "market_items": 0, "market_requested": 0,
            },
            "news": {"sources": [], "items": []},
            "buzzing": {"sources": [], "items": [{
                "source": "Buzzing HN", "source_type": "aggregator",
                "title": "Discovery", "summary": "Summary",
                "url": "https://example.com/original",
                "original_url": "https://example.com/original",
                "feed_url": "https://hn.buzzing.cc/feed.xml",
                "published_at": "2026-08-14T01:00:00Z",
            }]},
            "fact_checks": {"sources": [], "items": []},
            "think_tanks": {"sources": [], "items": []},
            "war": {"sources": [], "items": []},
            "markets": {"items": [], "missing": []}, "errors": [],
        }
        rendered = collector.render_markdown(bundle)
        self.assertIn("非权威", rendered)
        self.assertIn("Discovery", rendered)
        self.assertIn("https://example.com/original", rendered)
```

- [ ] **Step 4: Run the focused tests and confirm the new tests fail for missing APIs**

Run:

```text
python -m unittest tests.test_source_collector -v
```

Expected: existing tests pass, and the new tests fail because the aggregator
arguments/helper/bundle fields are not implemented yet. Do not edit the tests
to make them pass without implementing the behavior.

## Task 2: Implement the bounded Buzzing collection path

**Files:**

- Modify: `D:/documents/qqfarm/daily-brief-agent/src/daily_brief_agent/source_collector.py`
- Test: `D:/documents/qqfarm/daily-brief-agent/tests/test_source_collector.py`

- [ ] **Step 1: Add explicit feed constants and switch**

Add a small feed configuration near the existing feed constants:

```python
BUZZING_FEEDS = [
    ("Buzzing HN", "https://hn.buzzing.cc/feed.xml", "technology_science"),
    ("Buzzing Product Hunt", "https://ph.buzzing.cc/feed.xml", "consumer_technology"),
    ("Buzzing World News", "https://news.buzzing.cc/feed.xml", "world_affairs"),
    ("Buzzing New York Times", "https://nytimes.buzzing.cc/feed.xml", "world_affairs"),
]
BUZZING_MAX_AGE_HOURS = 48
BUZZING_PER_SOURCE = 6
BUZZING_LIMIT = 12
BUZZING_SELECTION_LIMIT = 3


def buzzing_enabled() -> bool:
    return os.environ.get("DAILY_BRIEF_BUZZING_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
```

- [ ] **Step 2: Extend `parse_feed` without changing publisher defaults**

Change the signature to accept `source_type="publisher"` and
`prefer_external_link=False`. Collect all Atom/RSS link candidates, identify
non-`buzzing.cc` links for aggregator feeds, and emit `original_url` only for
aggregator records. Preserve the current default behavior for all existing
feeds, dates, titles, summaries, and direct URLs.

The implementation must use `urllib.parse.urlsplit`, reject links without an
HTTP(S) scheme, and never treat a Buzzing URL as an original URL. A missing
original becomes `original_url=None`; it remains a discovery record but is not
eligible for final citation.

- [ ] **Step 3: Add URL/title deduplication for the supplemental pool**

Add these helpers:

```python
def _url_key(url: str) -> str:
    parsed = urllib.parse.urlsplit(url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    return f"{host}{path}?{parsed.query}" if parsed.query else f"{host}{path}"


def dedupe_supplemental_candidates(
    regular_items: list[dict[str, Any]],
    supplemental_items: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen_urls = {_url_key(item.get("url", "")) for item in regular_items if item.get("url")}
    seen_titles = {_title_key(item.get("title", "")) for item in regular_items if item.get("title")}
    result = []
    for item in supplemental_items:
        url_key = _url_key(item.get("original_url") or item.get("url", ""))
        title_key = _title_key(item.get("title", ""))
        if url_key in seen_urls or title_key in seen_titles:
            continue
        if url_key:
            seen_urls.add(url_key)
        if title_key:
            seen_titles.add(title_key)
        result.append(item)
    return result
```

Only supplemental items with `original_url` remain eligible for the prompt;
the evidence renderer may display missing-original records as discovery-only
but must not imply that their Buzzing URL is a direct source.

- [ ] **Step 4: Implement `collect_buzzing` as a non-critical group**

Implement `collect_buzzing(now, errors, regular_items)` by returning an empty
collection when the switch is disabled, collecting each configured feed with
`source_type="aggregator"` and `prefer_external_link=True`, adding the regular
category label, and applying `dedupe_supplemental_candidates` plus the total
cap. Catch the same fetch/parse exceptions as the existing feed group, record
`section="buzzing"`, and never raise them to the regular health gate.

- [ ] **Step 5: Add the Buzzing collection to `collect_all` without changing the critical expression**

Call Buzzing after regular news collection, before fact checks, and add a
separate `buzzing` bundle plus `buzzing_sources_ok` and `buzzing_items` health
fields. Do not include those fields in the `critical` expression or in
`news_items`, `news_sources_ok`, or `news_lanes_ok`.

- [ ] **Step 6: Render and log the internal candidate pool**

Add a health row and a clearly marked internal section such as
`## Buzzing 补充发现（非权威，仅供模型选题）`. Display the feed provenance,
original URL when present, and a warning when it is absent. The section is only
in the evidence bundle; no model instruction or final-email section may name
Buzzing as a required delivered section. Add `buzzing:<count>` to the stable
collection marker for tomorrow's diagnostic review.

- [ ] **Step 7: Run the focused tests and confirm they pass**

Run:

```text
python -m unittest tests.test_source_collector -v
```

Expected: all source-collector tests pass, including the new parser,
dedupe, failure-isolation, and rendering tests.

## Task 3: Update policy, prompt, configuration examples, and docs

**Files:**

- Modify: `D:/documents/qqfarm/daily-brief-agent/config/source-policy.txt`
- Modify: `D:/documents/qqfarm/daily-brief-agent/config/brief-prompt.txt`
- Modify: `D:/documents/qqfarm/daily-brief-agent/config/codex-runtime.env.example`
- Modify: `D:/documents/qqfarm/daily-brief-agent/README.md`
- Modify: `D:/documents/qqfarm/daily-brief-agent/docs/model-design.md`

- [ ] **Step 1: Add source-policy rules**

Append rules stating that Buzzing is an untrusted aggregator discovery pool;
the model may not use its translated title/summary as sole factual support;
the original publisher link is required for selection; zero to three items are
allowed; no Buzzing section is allowed; duplicate and crypto-only items are
ignored; and Buzzing failure is non-critical.

- [ ] **Step 2: Add prompt selection rules**

Append a model-facing contract with the same rules, explicitly requiring the
model to merge worthwhile items into an existing section and to omit all
Buzzing candidates when they add no material value. State that the source
bundle's Buzzing section is internal evidence, not a required output heading.

- [ ] **Step 3: Document the opt-out switch and trust boundary**

Add `DAILY_BRIEF_BUZZING_ENABLED=1` to the example runtime configuration and
explain that setting it to `0` disables only the optional pool. Update the
README feature/configuration sections and the model-design data-flow section;
do not include any production paths, addresses, recipients, or secrets.

- [ ] **Step 4: Run text/privacy checks**

Run:

```text
git diff --check
python tools/privacy_scan.py
```

Expected: no whitespace errors and `privacy_scan=ok` or the repository's
existing successful privacy-scan marker.

## Task 4: Local regression and staged commit

**Files:** all files from Tasks 1–3.

- [ ] **Step 1: Run the full local verification suite**

Run exactly:

```text
python -m compileall -q src tests tools
python -m unittest discover -s tests -p 'test_*.py' -v
Get-ChildItem scripts -Filter *.sh | ForEach-Object { bash -n $_.FullName }
python tools/privacy_scan.py
git diff --check
```

Expected: compileall exits 0; unittest reports zero failures/errors; every
shell syntax check exits 0; privacy scan passes; and diff check is clean.

- [ ] **Step 2: Inspect the diff for production-boundary violations**

Run:

```text
git status --short
git diff --stat
git diff -- config src tests README.md docs/model-design.md
```

Confirm the diff contains only the optional Buzzing implementation, tests,
policy/prompt/docs/examples, and no runtime data or credentials.

- [ ] **Step 3: Commit the implementation locally but do not push**

Run:

```text
git add src/daily_brief_agent/source_collector.py config/codex-runtime.env.example config/source-policy.txt config/brief-prompt.txt tests/test_source_collector.py README.md docs/model-design.md docs/superpowers/plans/2026-08-14-buzzing-candidate-pool.md
git diff --cached --check
git commit -m "feat: add optional Buzzing candidate pool"
```

The commit remains local until tomorrow's real email is judged.

## Task 5: Back up and stage the VPS implementation

**Files on VPS:** the matching source collector, prompt, policy, and runtime
example/config files under the existing private production workspace. The
resolved production path is kept only in private execution notes and is not
written into this public repository. Do not copy public state, logs,
subscribers, secrets, or generated mail to the repository.

- [ ] **Step 1: Read-only preflight**

Check the current production commit/file hashes, timer state, latest successful
delivery markers, and whether the working tree is clean. Confirm the active
VPS code still has the existing repair/validation path before changing it.

- [ ] **Step 2: Create a timestamped backup inside the private project area**

Copy only the exact files to be replaced into a mode-700 backup directory under
the private project workspace. Resolve and verify the target paths first; do not
use a broad recursive delete or overwrite. Record the backup path locally in
the execution notes, not in the public repository.

- [ ] **Step 3: Transfer only reviewed files**

Use SCP/SSH to transfer the source collector, prompt, policy, and runtime
configuration line. Do not alter systemd units, recipient state, SMTP files,
OAuth files, logs, or workspace history.

- [ ] **Step 4: Verify remote syntax and config state**

Run the remote Python compile check, inspect only the Buzzing switch value and
non-secret file hashes, and confirm systemd timer/service definitions are
unchanged.

## Task 6: Dry-run validation and tomorrow's real acceptance

- [ ] **Step 1: Run the collector in a private workspace**

Run the existing collector with normal required-source gates, then inspect only
counts, error markers, Buzzing source status, original-link ratio, and whether
the regular-news health counts remain unchanged. If Buzzing is unavailable,
leave the switch disabled and report the evidence rather than weakening a gate.

- [ ] **Step 2: Run one full `DAILY_BRIEF_DRY_RUN=1` report if the collector is healthy**

Use the existing runner so the combined prompt, model selection, validator, and
repair path are exercised without SMTP delivery. Review the generated report
for duplicate/noisy Buzzing additions and direct-source links. Keep the dry-run
artifact private and do not place it in Git.

- [ ] **Step 3: Leave the existing 11:00 timer as the next real experiment**

Do not change the timer. Tomorrow, 2026-08-15 at 11:00 Asia/Shanghai, inspect
the service journal and the private sent-message metadata. Acceptance requires
all existing markers:

```text
brief_validation=ok
recipient_count=1
send_success=1
send_failed=0
```

In addition, review whether the report contains zero to three genuinely useful
Buzzing-derived additions, no standalone Buzzing heading, no unverified
Buzzing-only claims, and no repeated headlines. `systemd active` alone is not
acceptance.

- [ ] **Step 4: Decide publication after the real result**

If the email is materially better and the existing gates pass, run the final
verification suite again, inspect the committed diff, and publish the local
implementation through the reviewed GitHub workflow. If the result is noisy,
set `DAILY_BRIEF_BUZZING_ENABLED=0` on the VPS, preserve the existing brief,
and do not publish the implementation as an improvement.

## Plan Self-Review

- Spec coverage: parser metadata, original links, dedupe, optional selection,
  three-item cap, no standalone section, failure isolation, crypto exclusion,
  docs, tests, staged VPS rollout, real delivery acceptance, and conditional
  publication are all mapped to Tasks 1–6.
- Placeholder scan: no `TBD`, `TODO`, or unspecified implementation step is
  used; commands and expected outcomes are concrete.
- Type consistency: `source_type`, `original_url`, `collect_buzzing`,
  `dedupe_supplemental_candidates`, `buzzing`, and the health fields are named
  consistently across tests, implementation, rendering, and rollout.
- Safety review: no schedule, recipient, SMTP, OAuth, systemd, or quality-gate
  change is included; backups precede VPS replacement; publication is
  conditional on the actual 11:00 delivery.
