# Daily Brief Agent

Daily Brief Agent is a production-oriented pipeline for creating Chinese global-news and market email briefings. It combines broad source collection, history-aware editorial context, Codex generation with web search, strict local validation, bounded error-informed regeneration, safe Gmail subscription commands, and per-recipient SMTP delivery.

The public repository contains no production credentials, subscribers, reports, logs, or host details. Start with the [Chinese README](README.md) for installation and operations.

Core reliability rule: a quality failure may trigger a full repair generation, but validation is never bypassed and invalid output is never sent.
