from __future__ import annotations

import argparse
from dataclasses import dataclass
import html
import json
from pathlib import Path
import re
from typing import Any, Iterable, Sequence


_COMPLETION_EVENT_TYPES = frozenset({"turn.completed", "response.completed"})
_NOTE_PATTERN = re.compile(
    r"<p\b(?=[^>]*\bbrief-model-note\b)[^>]*>.*?</p>",
    re.IGNORECASE | re.DOTALL,
)
_INSERTION_TAGS = ("</header>", "</h1>", "</body>")


@dataclass(frozen=True)
class UsageSummary:
    total_tokens: int | None
    usage_events: int
    malformed_lines: int


def _nonnegative_integer(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _event_usage_total(event: dict[str, Any]) -> int | None:
    if event.get("type") not in _COMPLETION_EVENT_TYPES:
        return None
    usage = event.get("usage")
    if not isinstance(usage, dict):
        return None

    total_tokens = _nonnegative_integer(usage.get("total_tokens"))
    if total_tokens is not None:
        return total_tokens

    input_tokens = _nonnegative_integer(usage.get("input_tokens"))
    output_tokens = _nonnegative_integer(usage.get("output_tokens"))
    if input_tokens is None or output_tokens is None:
        return None
    return input_tokens + output_tokens


def aggregate_usage(event_files: Iterable[Path]) -> UsageSummary:
    """Aggregate reliable token counts from Codex JSONL completion events."""

    total_tokens = 0
    usage_events = 0
    malformed_lines = 0
    for event_file in event_files:
        with event_file.open("r", encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    malformed_lines += 1
                    continue
                if not isinstance(event, dict):
                    continue
                event_total = _event_usage_total(event)
                if event_total is None:
                    continue
                total_tokens += event_total
                usage_events += 1

    return UsageSummary(
        total_tokens=total_tokens if usage_events else None,
        usage_events=usage_events,
        malformed_lines=malformed_lines,
    )


def _render_note(model: str, total_tokens: int | None) -> str:
    safe_model = html.escape(model.strip() or "unknown", quote=True)
    if total_tokens is None:
        usage_text = "暂不可得"
    else:
        usage_text = f"{total_tokens:,} tokens"
    return (
        '<p class="meta brief-model-note" '
        'style="margin:2px 0 0;font-size:11px;color:#98a2b3;">'
        f"注：生成模型 {safe_model} · 本次总用量：{usage_text}</p>"
    )


def annotate_message(content: str, model: str, total_tokens: int | None) -> str:
    """Add or replace the subtle generation metadata note in an HTML email."""

    note = _render_note(model, total_tokens)
    if _NOTE_PATTERN.search(content):
        return _NOTE_PATTERN.sub(note, content, count=1)

    for closing_tag in _INSERTION_TAGS:
        match = re.search(re.escape(closing_tag), content, re.IGNORECASE)
        if match:
            return f"{content[:match.end()]}\n{note}\n{content[match.end():]}"
    raise ValueError("generated message has no supported HTML insertion point")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="generated message before metadata injection")
    parser.add_argument("output", type=Path, help="message after metadata injection")
    parser.add_argument("--model", required=True, help="explicit model selected by the runner")
    parser.add_argument(
        "--events",
        action="append",
        type=Path,
        default=[],
        help="Codex JSONL event file; may be repeated",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    summary = aggregate_usage(args.events)
    content = args.input.read_text(encoding="utf-8")
    annotated = annotate_message(content, args.model, summary.total_tokens)
    args.output.write_text(annotated, encoding="utf-8")

    total_text = "unavailable" if summary.total_tokens is None else str(summary.total_tokens)
    source_text = "codex_json" if summary.total_tokens is not None else "unavailable"
    print(
        "generation_metadata="
        f"model={args.model} total_tokens={total_text} usage_source={source_text} "
        f"usage_events={summary.usage_events} malformed_lines={summary.malformed_lines}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
