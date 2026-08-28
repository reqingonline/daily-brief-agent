# Buzzing Candidate Pool Design

## Purpose

Add Buzzing as a supplementary discovery input for the daily brief without
turning it into an editorial section or an authoritative reporting source.
Buzzing is useful for breadth and Chinese-language discovery, but it is an
aggregator/translation layer: its titles and summaries may be duplicated,
truncated, translated, or detached from the original context. The brief must
therefore treat Buzzing as untrusted candidate data and continue to rely on
direct original sources for factual support.

The feature is intentionally additive. Existing source-diversity checks,
fact-check rules, market checks, output validation, bounded repair, recipient
handling, SMTP delivery, and the no-Weibo/no-X policy remain unchanged.

## Approaches Considered

### 1. Make Buzzing a normal news lane

Rejected. This would give an aggregator the same collection and editorial
weight as direct publishers, could make a Buzzing outage affect the source
health gate, and would encourage duplicated translated headlines.

### 2. Collect Buzzing as an optional candidate pool

Selected. Collect a bounded set of recent Buzzing feed entries, label them as
aggregator discoveries, deduplicate them against the regular news bundle, and
let the model include zero to three items only when they add material value.
The model must cite the direct original URL when one is available and must not
use Buzzing alone to establish a factual claim.

### 3. Mention Buzzing only in documentation

Rejected for this iteration. Documentation alone would not test whether the
source improves the actual brief. The selected design keeps the source
non-critical while allowing measured, reversible editorial value.

## Scope and Non-Goals

### In scope

- A bounded Buzzing RSS/Atom collection path in the public source collector.
- Explicit aggregator metadata and direct-link handling.
- Cross-pool title/URL deduplication before the model sees candidates.
- Prompt and source-policy rules for optional inclusion, original-source
  verification, and no standalone Buzzing section.
- Deterministic tests for parsing, deduplication, failure isolation, and
  rendering.
- Public documentation of the trust boundary and the production rollout.
- A shadow/dry-run validation on the VPS before enabling the live candidate
  input.

### Out of scope

- A Buzzing section in the delivered email.
- A Buzzing quota, minimum, or requirement for every email.
- Scraping Buzzing HTML pages or using browser cookies/login state.
- Treating Buzzing as a fact-check authority or replacing direct sources.
- Reintroducing Weibo or X collectors.
- Adding crypto-only coverage, a crypto section, or cryptocurrency
  recommendations.
- Changes to the email schedule, recipients, SMTP credentials, quality gates,
  or systemd service structure.

## Data Flow

1. The collector fetches only a small, explicit set of Buzzing RSS/Atom feeds
   over the existing bounded HTTP client. The first implementation should use
   the stable public feed endpoint(s), with a small per-feed and total-item
   cap. It must not fetch the multi-megabyte aggregate JSON endpoint.
2. Each record is normalized into the existing item shape and additionally
   marked with `source_type="aggregator"`. The record retains the Buzzing feed
   URL as discovery provenance and prefers the original article URL for the
   item URL. If no direct original URL can be identified, the record is kept
   only as a discovery candidate and cannot be selected as a final citation.
3. Buzzing records are deduplicated by normalized URL and title fingerprint
   against the regular news candidates. A Buzzing item that repeats an
   existing candidate does not increase the normal news count and does not
   receive extra editorial weight.
4. The bundle carries Buzzing candidates separately from the regular news
   collection so the prompt can preserve the trust boundary. This is an
   internal evidence-bundle distinction, not an email section.
5. The model may select zero to three Buzzing candidates and merge them into
   the existing technology, consumer, business, culture, or other relevant
   sections. It may omit all of them. There is no forced placement and no
   requirement that a Buzzing item appear in the final email.
6. The existing validator evaluates the final report exactly as before. A
   Buzzing fetch failure, empty feed, or all-candidates-rejected result cannot
   make source collection critical and cannot bypass any existing validator
   failure.

## Candidate and Link Rules

- The feed title/summary is untrusted discovery text. It may guide topic
  selection but is not evidence by itself.
- The final item link should point to the original publisher, not to a
  translated Buzzing landing page, whenever the feed exposes that link.
- The renderer should expose both provenance fields to the model when useful:
  `feed_url` for discovery provenance and `url`/`original_url` for the direct
  article. It must never silently label a Buzzing translation as an original
  report.
- A candidate without a usable direct source may be ignored even when its
  title looks interesting. It must not be used as the sole support for a
  factual sentence.
- Candidate timestamps are source timestamps when available. The system must
  not present the time at which Buzzing translated or aggregated an item as
  the original publication time.
- Candidate summaries are bounded and cleaned using the existing parser
  limits. No full article text is fetched or copied.
- Crypto-only topics, token price movements, exchange promotions, airdrops,
  and similar cryptocurrency industry content are excluded from this pool.

## Editorial Selection Contract

The prompt and source policy should instruct the model to include a Buzzing
candidate only when all of the following are true:

- it is materially relevant to the reader's current brief;
- it is not a duplicate of a regular candidate or an already selected item;
- it adds information, context, or a useful product/project lead rather than
  another translated headline;
- the direct original source is accessible and appropriate for citation;
- any factual claim is corroborated or clearly attributed to the original
  source, with inference separated from fact;
- it is not crypto-only and does not create a prohibited social-media section.

The model must prefer a smaller, higher-value selection over filling space.
Zero selected items is a valid outcome. Buzzing must never be named as a
separate email section merely because it supplied a candidate.

## Failure Isolation and Observability

Buzzing is a non-critical collection group:

- Fetch, XML, timeout, or HTTP errors are recorded in the existing error list
  with a `buzzing` section marker.
- The collection log may report Buzzing source/item counts for diagnosis.
- Buzzing counts must not be included in the regular news-lane health count or
  the minimum regular-news item threshold.
- The collector exits successfully when the existing required sources pass,
  even if every Buzzing feed fails.
- The runner must not print feed contents, message bodies, credentials, or
  subscriber data.

## Configuration and Rollout

The public repository should expose a documentation-safe switch for disabling
the optional pool, such as `DAILY_BRIEF_BUZZING_ENABLED=0`, with the default
being enabled for the additive, non-critical collection path. Feed URLs and
caps remain code/configuration values that contain no secrets.

Rollout order:

1. Add the design and implementation to the public repository, with tests and
   documentation updates.
2. Run the full local test suite, syntax checks, repository privacy scan, and
   a deterministic fixture-based collection/rendering check.
3. Sync the reviewed public commit to the VPS without touching schedule,
   recipient, SMTP, or validator configuration.
4. Run a shadow/dry-run collection and inspect the candidate count, direct
   links, deduplication behavior, and unchanged health gate.
5. Enable the optional candidate pool for the next scheduled run only after
   the shadow evidence is clean.
6. Verify the actual delivery outcome using the existing acceptance markers:
   `brief_validation=ok`, `recipient_count=1`, `send_success=1`, and
   `send_failed=0`. A running systemd timer alone is not acceptance.

If the first live run produces noise, the switch can disable only Buzzing;
the rest of the brief continues with the previous source bundle.

## Tests and Acceptance Criteria

Add deterministic tests covering:

1. A Buzzing Atom/RSS fixture preserves the original article link, feed
   provenance, timestamp, and aggregator marker.
2. An entry without a direct original URL cannot be rendered as an accepted
   final citation.
3. Duplicate Buzzing and regular-news titles/URLs collapse to one candidate.
4. A Buzzing fetch or parse failure is recorded but does not set the overall
   source health to critical when regular sources meet their existing gate.
5. The rendered evidence bundle labels Buzzing as non-authoritative discovery
   and does not create a final-email section contract.
6. The prompt/policy text requires original-source verification, allows zero
   selections, caps selection at three, and excludes crypto-only candidates.
7. Existing tests for 11 news lanes, source diversity, validator rejection,
   bounded repair, subscriptions, SMTP, privacy, and no social sections still
   pass unchanged.

The feature is accepted only when the public repository passes its existing
release checks plus the new tests, and the VPS produces one real validated
delivery after shadow validation. A source that merely fetches successfully
does not count as an editorial improvement; the first live report must be
reviewed for duplicate/noise rate and direct-link quality.

## Files Expected to Change After Spec Approval

- `src/daily_brief_agent/source_collector.py`: optional feed configuration,
  normalization, deduplication, rendering, and non-critical health metadata.
- `config/source-policy.txt`: aggregator trust boundary and direct-source
  rules.
- `config/brief-prompt.txt`: optional selection contract, three-item cap, and
  no-standalone-section rule.
- `tests/test_source_collector.py`: parser, dedupe, failure isolation, and
  rendering fixtures.
- `tests/test_editorial_context.py` or the most relevant prompt/config test:
  policy/prompt contract checks if the current test shape supports them.
- `README.md` and `docs/model-design.md`: explain Buzzing as a non-authoritative
  candidate pool and document the opt-out switch.

No recipients, secrets, generated reports, VPS paths, logs, or production
state may be added to the repository.
