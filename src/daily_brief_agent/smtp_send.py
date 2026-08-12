"""Send one generated brief separately to subscribers from a JSON state file."""

from __future__ import annotations

import argparse
import os
import smtplib
import ssl
import sys
from datetime import datetime
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from .subscriber_store import StateError, normalize_sender


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / ".env"
_ALLOWED_ENV_KEYS = {
    "EMAIL_ADDRESS",
    "EMAIL_PASSWORD",
    "EMAIL_SMTP_HOST",
    "EMAIL_SMTP_PORT",
    "SMTP_FROM",
    "DAILY_BRIEF_SUBJECT",
}


def load_env(path: str | Path | None = None) -> None:
    """Load allowlisted SMTP keys from an explicit or project-local env file."""

    selected = path or os.environ.get("DAILY_BRIEF_ENV_FILE") or DEFAULT_ENV_FILE
    env_path = Path(selected)
    if not env_path.is_file():
        return
    try:
        lines = env_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RuntimeError("could not read SMTP environment file") from exc
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, separator, value = line.partition("=")
        key = key.strip()
        if not separator or key not in _ALLOWED_ENV_KEYS:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load_recipients(state_path: str | Path) -> list[str]:
    """Read, normalize, and deduplicate only the ``subscribers`` field."""

    import json

    path = Path(state_path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            state: Any = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError("could not read recipient state") from exc
    if not isinstance(state, dict) or not isinstance(state.get("subscribers"), list):
        raise StateError("recipient state has no subscribers array")
    recipients: set[str] = set()
    for value in state["subscribers"]:
        if not isinstance(value, str):
            raise StateError("subscribers must contain only strings")
        try:
            recipients.add(normalize_sender(value))
        except ValueError as exc:
            raise StateError("subscribers contains an invalid address") from exc
    return sorted(recipients)


class _ReadableHTMLParser(HTMLParser):
    """Extract a compact plain-text fallback from generated email HTML."""

    _BLOCK_TAGS = {
        "article",
        "blockquote",
        "br",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "li",
        "p",
        "section",
        "table",
        "tr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.skip_depth += 1
        if not self.skip_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")
        if not self.skip_depth and tag in {"td", "th"}:
            self.parts.append("\t")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.skip_depth:
            self.skip_depth -= 1
            return
        if not self.skip_depth and tag in self._BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def html_to_text(content: str) -> str:
    parser = _ReadableHTMLParser()
    parser.feed(content)
    lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
    compact: list[str] = []
    for line in lines:
        if line:
            compact.append(line)
        elif compact and compact[-1]:
            compact.append("")
    return "\n".join(compact).strip() + "\n"


def _looks_like_html(content: str) -> bool:
    sample = content.lstrip().lower()
    return sample.startswith("<!doctype html") or "<html" in sample[:500] or "<body" in sample[:500]


def build_message(sender: str, recipient: str, content: str, subject: str) -> EmailMessage:
    message = EmailMessage()
    message["From"] = normalize_sender(sender)
    message["To"] = normalize_sender(recipient)
    message["Subject"] = subject
    if _looks_like_html(content):
        message.set_content(html_to_text(content))
        message.add_alternative(content, subtype="html")
    else:
        message.set_content(content)
    return message


def split_subject_body(content: str, fallback_subject: str) -> tuple[str, str]:
    """Remove a generated first ``Subject:`` line from the message body."""

    lines = content.lstrip("\ufeff").splitlines()
    first_nonempty = next((index for index, line in enumerate(lines) if line.strip()), None)
    if first_nonempty is None:
        return fallback_subject, ""
    first_line = lines[first_nonempty].strip()
    prefix, separator, value = first_line.partition(":")
    if separator and prefix.strip().lower() == "subject" and value.strip():
        body_lines = lines[first_nonempty + 1 :]
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        return value.strip(), "\n".join(body_lines).rstrip() + "\n"
    return fallback_subject, content


def _smtp_config() -> tuple[str, int, str, str, str]:
    host = os.environ.get("EMAIL_SMTP_HOST") or os.environ.get("SMTP_HOST", "smtp.gmail.com")
    try:
        port = int(os.environ.get("EMAIL_SMTP_PORT") or os.environ.get("SMTP_PORT", "465"))
    except ValueError as exc:
        raise RuntimeError("SMTP_PORT must be an integer") from exc
    username = (
        os.environ.get("EMAIL_ADDRESS")
        or os.environ.get("SMTP_USERNAME")
        or os.environ.get("SMTP_USER")
        or ""
    )
    password = (
        os.environ.get("EMAIL_PASSWORD")
        or os.environ.get("SMTP_PASSWORD")
        or os.environ.get("GMAIL_APP_PASSWORD")
        or ""
    )
    sender = os.environ.get("SMTP_FROM") or username
    if not username or not password or not sender:
        raise RuntimeError("SMTP credentials are not configured")
    return host, port, username, password, normalize_sender(sender)


def send_all(recipients: list[str], content: str, subject: str) -> tuple[int, int]:
    host, port, username, password, sender = _smtp_config()
    context = ssl.create_default_context()
    success = 0
    failed = 0

    if port == 465:
        client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, context=context, timeout=60)
    else:
        client = smtplib.SMTP(host, port, timeout=60)
    with client:
        if port != 465:
            client.ehlo()
            client.starttls(context=context)
            client.ehlo()
        client.login(username, password)
        for recipient in recipients:
            try:
                client.send_message(build_message(sender, recipient, content, subject))
                success += 1
            except Exception:
                failed += 1
    return success, failed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("message_file", type=Path)
    parser.add_argument("recipient_file", type=Path)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        load_env()
        generated = args.message_file.read_text(encoding="utf-8")
        recipients = load_recipients(args.recipient_file)
    except (OSError, StateError):
        print("smtp_send_error=input_invalid", file=sys.stderr)
        return 1

    print(f"recipient_count={len(recipients)}")
    if args.dry_run:
        print("dry_run=true send_success=0 send_failed=0")
        return 0
    if not recipients:
        print("send_success=0 send_failed=0")
        return 0

    fallback_subject = os.environ.get(
        "DAILY_BRIEF_SUBJECT",
        (
            "\u6bcf\u65e5\u5927\u4e8b\u4e0e\u5e02\u573a\u7b80\u62a5 - "
            f"{datetime.now().astimezone().strftime('%Y-%m-%d %H:%M')} "
            "\u4e2d\u56fd\u65f6\u95f4"
        ),
    )
    subject, content = split_subject_body(generated, fallback_subject)
    try:
        success, failed = send_all(recipients, content, subject)
    except Exception:
        print("smtp_send_error=transport_failed", file=sys.stderr)
        return 1
    print(f"send_success={success} send_failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
