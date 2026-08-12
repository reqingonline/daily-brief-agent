# Daily Brief Agent Open-Source Release Design

## Purpose

Publish the proven daily briefing workflow as a reusable public project without exposing any production identity, credentials, subscriber data, generated mail, operational history, or VPS details. The public project must be installable on a fresh Linux host and must preserve the defining editorial and reliability design: broad source collection, history-aware editing, quality validation, bounded error-informed regeneration, safe subscription handling, and SMTP delivery.

## Approaches Considered

### 1. Publish a raw production snapshot

This is the fastest approach but is rejected. The production directory contains secrets, subscriber state, generated reports, logs, backups, host-specific paths, and deployment history. Even an exclusion-based copy creates an unacceptable chance of accidental disclosure.

### 2. Build a faithful standalone extraction

This is the selected approach. Copy only an explicit source whitelist into a new repository, remove dead social-media collectors, replace host-specific configuration with examples, add reproducible installation assets, retain the current behavior and tests, and run independent secret scans before publication.

### 3. Rewrite the service as a new framework

This could create a cleaner long-term package but would delay release and risk changing the editorial behavior that has already produced good reports. A deeper package refactor is deferred until the faithful extraction has a stable public baseline.

## Repository and License

- GitHub owner: `reqingonline`
- Repository: `daily-brief-agent`
- Visibility: public
- Default branch: `main`
- License: MIT
- Primary documentation language: Simplified Chinese, with an English overview for discoverability

The production VPS remains private and is not converted into the Git repository.

## Included Components

- `src/`: source collection, editorial-history context, validation, SMTP sending, Gmail subscription management, subscriber-state validation, OAuth setup, and command journal.
- `scripts/`: orchestration scripts for subscription preflight and report generation, including bounded quality repair.
- `config/`: the editorial prompt, source policy, and non-secret runtime examples.
- `systemd/`: generic service and timer templates for 10:45/22:45 preflight and 11:00/23:00 generation in Asia/Shanghai.
- `tests/`: deterministic unit tests for source parsing, editorial context, validation, SMTP message construction, subscription safety, and orchestration repair behavior.
- `.github/workflows/ci.yml`: syntax checks, unit tests, and a secret-pattern check.
- Documentation: architecture, installation, configuration, security, contribution, and production migration notes.

## Explicit Exclusions

The repository and every Git commit must exclude:

- Gmail OAuth client secrets and refresh tokens;
- SMTP usernames, passwords, and real sender addresses;
- real recipients, subscriber state, owner identity, processed-message state, and command journal state;
- generated or rejected messages, source bundles, editorial history, logs, workspaces, caches, backups, and virtual environments;
- production environment files, IP addresses, ports, usernames, private-key paths, and absolute VPS paths;
- model-provider credentials or authenticated Codex state.

Only documentation-safe example values such as `owner@example.com`, `smtp.example.com`, `/opt/daily-brief-agent`, and `gpt-5` may appear.

## Architecture and Data Flow

1. The subscription preflight reads Gmail commands from an authenticated account, applies sender-safety and exact-command checks, updates subscriber state atomically, and writes a freshness marker.
2. The main runner verifies the marker, builds history-aware editorial context, collects a broad source bundle, and composes an untrusted-data-delimited model prompt.
3. The configured Codex model searches and produces a complete Chinese HTML report.
4. A basic output gate and the Python validator enforce section structure, language, source diversity, direct-link rules, market requirements, and prohibited social sections.
5. A failed quality check triggers at most two complete, error-informed regenerations. Validation is never bypassed.
6. Only a validated report reaches the SMTP sender. The sender reads active recipients from validated state and emits structured success/failure counters.

State and secret files remain runtime-only and are protected by restrictive permissions.

## Configuration Design

The public project uses three classes of configuration:

- Committed policy: editorial prompt and source policy.
- Committed examples: `.env.example`, `config/codex-runtime.env.example`, and `state/subscribers.example.json`.
- Uncommitted runtime data: `.env`, `config/codex-runtime.env`, `state/daily-brief-subscribers.json`, OAuth files, logs, and workspaces.

Paths in scripts are derived from the repository root. The systemd templates use `/opt/daily-brief-agent` and a dedicated `dailybrief` service user; documentation explains how to substitute another installation path and user.

## Error Handling and Observability

Every major stage emits a stable `key=value` marker. Failures remain fail-closed: stale subscription state, source-collection failure, model failure, malformed output, exhausted quality repair, invalid recipient state, or SMTP failure exits non-zero. Rejected output is kept locally with mode `0600` but ignored by Git.

The runner records per-stage elapsed seconds so operators can distinguish collection, model generation, validation/repair, and SMTP latency. It must not print credentials, full subscriber state, or message bodies to standard output.

## Testing and Release Gates

Publication requires all of the following:

1. Python unit tests pass on a clean environment.
2. Bash syntax checks pass for every shell script.
3. The validator rejects source concentration and accepts diverse sources.
4. An isolated orchestration test proves `invalid first draft -> one repair -> validation success -> fake SMTP success` without external delivery.
5. A repository-wide scan finds no private keys, tokens, real email addresses, VPS identifiers, production paths, runtime state, logs, or generated reports.
6. Git history contains only the new public repository and no imported production history.
7. The public GitHub repository is fetched after push and its default branch, visibility, commit, file list, license, and CI workflow are verified.

## Production Boundary

Publishing does not redeploy or modify the live VPS. The public repository is a sanitized extraction and documentation baseline. A future production migration can compare hashes, stage changes, back up the live service, and deploy explicitly; that migration is outside this release.
