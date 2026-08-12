# Security Policy

## Supported version

Security fixes are applied to the latest `main` branch until versioned releases begin.

## Reporting a vulnerability

Please use GitHub's private vulnerability reporting feature. Do not open a public issue containing credentials, subscriber addresses, generated private reports, OAuth files, or SMTP configuration.

## Runtime boundary

This project processes untrusted web and email content. Source text is delimited as untrusted input before model use. Gmail commands must match the supported command grammar exactly, and attachments or linked content are never executed. Quality validation is fail-closed and is not bypassed during repair.

Keep `.env`, `secrets/`, `state/`, `logs/`, `workspace/`, Codex authentication state, and generated reports outside Git. Run `python tools/privacy_scan.py` before every public release.
