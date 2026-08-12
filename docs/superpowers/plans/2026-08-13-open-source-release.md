# Daily Brief Agent Open-Source Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a sanitized, reproducible public release of the production-proven daily briefing workflow at `reqingonline/daily-brief-agent`.

**Architecture:** Build a new repository from a strict whitelist of audited production source files. Preserve behavior while deriving paths from the repository root, replacing runtime identity with examples, deleting unused social collectors, and adding deterministic orchestration and privacy release gates.

**Tech Stack:** Python 3.11+, Bash, Codex CLI, Gmail API, SMTP, systemd, GitHub Actions

---

### Task 1: Create the Public Repository Skeleton

**Files:**
- Create: `.gitignore`
- Create: `.gitattributes`
- Create: `LICENSE`
- Create: `README.md`
- Create: `README.en.md`
- Create: `SECURITY.md`
- Create: `CONTRIBUTING.md`
- Create: `pyproject.toml`
- Create: `requirements.txt`

- [ ] **Step 1: Add deny-by-default runtime exclusions**

The `.gitignore` must exclude `.env`, `config/codex-runtime.env`, `state/*` except examples, `secrets/`, `logs/`, `workspace/`, `.venv/`, caches, generated messages, source bundles, OAuth JSON, and private keys. `.gitattributes` must normalize text files to LF so Bash scripts remain executable on Linux.

- [ ] **Step 2: Add MIT licensing and project metadata**

Create an MIT license for 2026 XiaoRe. Define Python `>=3.11`, the three pinned Google dependencies from the audited production `requirements.txt`, and unittest discovery as the documented test command.

- [ ] **Step 3: Document purpose and safety boundary**

README must describe the six-stage pipeline, include a quick-start that uses only example identities, explain that Codex authentication is local runtime state, and explicitly warn users never to commit subscriber state, OAuth files, SMTP passwords, logs, or generated reports.

- [ ] **Step 4: Commit the skeleton**

```bash
git add .gitignore .gitattributes LICENSE README.md README.en.md SECURITY.md CONTRIBUTING.md pyproject.toml requirements.txt
git commit -m "chore: scaffold public project"
```

### Task 2: Import and Sanitize the Python Components

**Files:**
- Create: `src/daily_brief_agent/__init__.py`
- Create: `src/daily_brief_agent/source_collector.py`
- Create: `src/daily_brief_agent/editorial_context.py`
- Create: `src/daily_brief_agent/validate_brief.py`
- Create: `src/daily_brief_agent/smtp_send.py`
- Create: `src/daily_brief_agent/subscriber_store.py`
- Create: `src/daily_brief_agent/command_journal.py`
- Create: `src/daily_brief_agent/gmail_subscription_manager.py`
- Create: `src/daily_brief_agent/gmail_oauth_setup.py`
- Test: `tests/test_source_collector.py`
- Test: `tests/test_editorial_context.py`
- Test: `tests/test_validate_brief.py`
- Test: `tests/test_smtp_send.py`
- Test: `tests/test_gmail_subscription_manager.py`

- [ ] **Step 1: Import only audited files**

Copy the audited source files whose production hashes are recorded during the release session. Do not copy any runtime directory or environment file. Adapt imports to the `daily_brief_agent` package and place tests under `tests/`.

- [ ] **Step 2: Remove inactive social-media code**

Delete `parse_weibo_jsonld`, `collect_weibo`, `_TrendsParser`, `parse_trends24`, and `collect_x_trends`. Keep the rendered source bundle free of social sections. Update tests so removed symbols cannot return accidentally.

- [ ] **Step 3: Remove production path fallback**

Change SMTP environment loading so it reads only an explicitly supplied `DAILY_BRIEF_ENV_FILE` or the repository `.env`; remove the legacy private-host SMTP environment fallback.

- [ ] **Step 4: Run focused tests**

```bash
python -m unittest discover -s tests -p "test_*.py" -v
```

Expected: all imported unit tests pass and no test performs network or SMTP delivery.

- [ ] **Step 5: Commit source and tests**

```bash
git add src tests
git commit -m "feat: publish briefing pipeline"
```

### Task 3: Publish Configuration and Runtime Examples

**Files:**
- Create: `.env.example`
- Create: `config/brief-prompt.txt`
- Create: `config/source-policy.txt`
- Create: `config/codex-runtime.env.example`
- Create: `state/subscribers.example.json`

- [ ] **Step 1: Add non-secret examples**

Use only `owner@example.com`, `reader@example.com`, `smtp.example.com`, `gpt-5`, and placeholder paths. The subscriber example must pass `validate_state` and contain no real identity.

- [ ] **Step 2: Preserve editorial policy**

Import the audited prompt and source policy, then scan them for email addresses, host identifiers, production paths, credentials, and social-media requirements. Remove only private or obsolete text; preserve source diversity, direct-link, fact-versus-analysis, history, market, and section rules.

- [ ] **Step 3: Commit configuration**

```bash
git add .env.example config state/subscribers.example.json
git commit -m "docs: add safe runtime examples"
```

### Task 4: Add Portable Orchestration and Timing Telemetry

**Files:**
- Create: `scripts/run-daily-brief.sh`
- Create: `scripts/run-subscription-preflight.sh`
- Create: `tests/test_runner_retry.py`

- [ ] **Step 1: Port the production runner**

Resolve `BASE_DIR` from `scripts/..`, set `PYTHON` from `DAILY_BRIEF_PYTHON` with `.venv/bin/python` fallback, invoke package modules with `python -m`, retain the 30-minute preflight freshness requirement, source collection, prompt boundaries, basic output gate, maximum two repairs, validation, dry-run mode, and SMTP counters.

- [ ] **Step 2: Add stage timing markers**

Emit integer-second markers for `editorial_context_seconds`, `source_collection_seconds`, each `model_generation_seconds`, `validation_seconds`, and `smtp_seconds`, plus `total_seconds`. Timing output must not contain message bodies or secrets.

- [ ] **Step 3: Add isolated retry regression**

Create a unittest that builds a temporary project fixture with fake Codex and fake SMTP behavior. Its first generated report must fail source concentration, its second must pass, and assertions must require exactly two model calls, `brief_repair=ok attempts=1`, and `send_success=1 send_failed=0` without network delivery.

- [ ] **Step 4: Run shell and orchestration checks**

```bash
bash -n scripts/run-daily-brief.sh scripts/run-subscription-preflight.sh
python -m unittest tests.test_runner_retry -v
```

Expected: Bash exits 0 and the isolated retry test passes.

- [ ] **Step 5: Commit orchestration**

```bash
git add scripts tests/test_runner_retry.py
git commit -m "feat: add validated repair orchestration"
```

### Task 5: Add Generic systemd Deployment Assets

**Files:**
- Create: `systemd/daily-brief-agent.service`
- Create: `systemd/daily-brief-agent.timer`
- Create: `systemd/daily-brief-subscription.service`
- Create: `systemd/daily-brief-subscription.timer`
- Create: `docs/deployment.md`

- [ ] **Step 1: Create generic units**

Use service user `dailybrief`, installation root `/opt/daily-brief-agent`, `UMask=0077`, network-online ordering, and bounded service timeouts. Schedule subscription preflight at `10,22:45:00 Asia/Shanghai` and generation at `11,23:00:00 Asia/Shanghai`, both with `Persistent=true`.

- [ ] **Step 2: Document installation and rollback**

Document dedicated-user creation, virtual environment setup, example-file copying, OAuth permissions, Codex authentication, SMTP configuration, dry-run validation, timer enablement, journal markers, backup, and rollback. Do not include the production host or identity.

- [ ] **Step 3: Verify units**

```bash
systemd-analyze verify systemd/*.service systemd/*.timer
```

Expected: no unit errors on Linux with systemd.

- [ ] **Step 4: Commit deployment assets**

```bash
git add systemd docs/deployment.md
git commit -m "docs: add systemd deployment"
```

### Task 6: Add CI and Privacy Release Gates

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `tools/privacy_scan.py`
- Create: `tests/test_privacy_scan.py`

- [ ] **Step 1: Implement a tracked-file privacy scanner**

Scan `git ls-files` content and names for private-key headers, common token formats, non-example email addresses, production absolute paths, IPv4 literals outside documentation-safe ranges, OAuth/token files, runtime state, logs, generated reports, and environment files. Return non-zero and print only file and rule identifiers, not secret values.

- [ ] **Step 2: Test scanner allow and deny cases**

Use temporary Git repositories to prove `owner@example.com` and `/opt/daily-brief-agent` pass while a private-key header, real-looking email, public IPv4 address, `token.json`, and `logs/sent-message.md` fail.

- [ ] **Step 3: Add GitHub Actions**

CI must run on push and pull request with Python 3.11 and 3.12, install the project, run all unittests, compile Python, run Bash syntax checks, and execute the privacy scanner.

- [ ] **Step 4: Commit release gates**

```bash
git add .github tools tests/test_privacy_scan.py
git commit -m "ci: enforce tests and privacy scan"
```

### Task 7: Perform the Full Release Verification

**Files:**
- Verify: all tracked files and Git history

- [ ] **Step 1: Run all local checks**

```bash
python -m compileall -q src tests tools
python -m unittest discover -s tests -p "test_*.py" -v
bash -n scripts/*.sh
python tools/privacy_scan.py
```

Expected: every command exits 0 with zero test failures and `privacy_scan=ok`.

- [ ] **Step 2: Inspect repository scope**

```bash
git status --short
git ls-files
git log --oneline --decorate --stat
```

Expected: clean worktree; no runtime, secret, log, backup, generated report, production environment, or unrelated workspace file is tracked.

### Task 8: Publish and Verify GitHub

**Files:**
- Remote: `reqingonline/daily-brief-agent`

- [ ] **Step 1: Create the public repository and push**

```bash
gh repo create reqingonline/daily-brief-agent --public --source . --remote origin --push --description "Production-grade AI daily briefing pipeline with source diversity, validation, repair, subscriptions, and SMTP delivery."
```

- [ ] **Step 2: Verify the remote independently**

Use `gh repo view`, `gh api repos/reqingonline/daily-brief-agent/contents`, and a fresh shallow clone in a temporary directory. Confirm visibility `PUBLIC`, default branch `main`, MIT license, expected commit, CI workflow, clean privacy scan, and passing tests from the clone.

- [ ] **Step 3: Report the release**

Return the repository URL, exact commit, validation counts, privacy result, CI status if available, and any optional configuration still required for a new operator to send a real report.
