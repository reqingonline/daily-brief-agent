"""Poll Gmail for exact daily-brief subscription commands.

Email is untrusted input. This worker reads message headers and inline body text
only; it never follows links or downloads attachment bodies.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import html
import os
import re
import stat
import sys
from email.message import EmailMessage
from email.utils import parseaddr
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

from .command_journal import CommandJournal
from .subscriber_store import StateError, SubscriberStore, normalize_sender


SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]
PROCESSED_LABEL = "\u7b80\u62a5\u8ba2\u9605-\u5df2\u5904\u7406"
MAX_MESSAGES = 100
MAX_DISCOVERY_MESSAGES = 5000
MAX_INLINE_BODY_BYTES = 256 * 1024
REPLIES = {
    "new_subscription": (
        "\u8ba2\u9605\u6210\u529f\u3002\u4f60\u5c06\u4ece\u4e0b\u4e00\u671f\u5f00\u59cb\u6536\u5230"
        "\u6bcf\u65e5\u5168\u7403\u5927\u4e8b\u4e0e\u5e02\u573a\u7b80\u62a5\uff08\u5317\u4eac\u65f605:00\u3001"
        "17:00\uff09\u3002"
    ),
    "already_subscribed": (
        "\u4f60\u5df2\u5728\u8ba2\u9605\u540d\u5355\u4e2d\uff0c\u65e0\u9700\u91cd\u590d\u8ba2\u9605\u3002"
    ),
    "unsubscribed": (
        "\u9000\u8ba2\u6210\u529f\u3002\u6b64\u90ae\u7bb1\u4ee5\u540e\u4e0d\u518d\u6536\u5230"
        "\u6bcf\u65e5\u5168\u7403\u5927\u4e8b\u4e0e\u5e02\u573a\u7b80\u62a5\u3002"
    ),
    "not_subscribed": (
        "\u6b64\u90ae\u7bb1\u5f53\u524d\u672a\u8ba2\u9605\uff0c\u65e0\u9700\u9000\u8ba2\u3002"
    ),
}

_COMMANDS = {
    "\u8ba2\u9605": "subscribe",
    "\u9000\u8ba2": "unsubscribe",
}
_QUOTE_PATTERNS = (
    re.compile(r"^On\s.+wrote:\s*$", re.IGNORECASE),
    re.compile(r"^\u5728\s*.+\u5199\u9053[\uff1a:]\s*$", re.IGNORECASE),
)
_AUTOMATED_LOCAL_PARTS = {
    "mailer-daemon",
    "postmaster",
    "no-reply",
    "noreply",
    "do-not-reply",
    "donotreply",
}
# Subscription commands are intended for ordinary personal senders.  These
# conservative prefixes cover common service, marketing, official and
# financial mailboxes without restricting the domain to a small allowlist.
_NON_PERSONAL_LOCAL_PARTS = {
    "account",
    "accounts",
    "admin",
    "administrator",
    "alert",
    "alerts",
    "billing",
    "contact",
    "customer",
    "help",
    "helpdesk",
    "info",
    "invoice",
    "invoices",
    "marketing",
    "news",
    "newsletter",
    "notify",
    "notification",
    "notifications",
    "official",
    "operator",
    "payment",
    "payments",
    "press",
    "promo",
    "promotions",
    "security",
    "service",
    "services",
    "support",
    "system",
    "transaction",
    "transactions",
    "updates",
    "verify",
    "verification",
    "wallet",
    "webmaster",
}
_NON_PERSONAL_DOMAIN_TOKENS = {
    "alerts",
    "finance",
    "financial",
    "government",
    "gov",
    "media",
    "news",
    "newsletter",
    "notify",
    "notification",
    "official",
    "press",
}
_FINANCIAL_DOMAIN_TOKENS = {
    "alipay",
    "bank",
    "banking",
    "broker",
    "brokerage",
    "card",
    "cards",
    "credit",
    "finance",
    "financial",
    "fund",
    "funds",
    "invest",
    "investment",
    "investments",
    "loan",
    "loans",
    "mastercard",
    "pay",
    "payment",
    "payments",
    "paypal",
    "securities",
    "stripe",
    "tenpay",
    "transaction",
    "transactions",
    "unionpay",
    "visa",
    "wallet",
}
_FINANCIAL_DOMAIN_SUFFIXES = {
    "abchina.com",
    "alipay.com",
    "bankcomm.com",
    "boc.cn",
    "ccb.com",
    "ccb.com.cn",
    "cebbank.com",
    "cib.com.cn",
    "citicbank.com",
    "cmbchina.com",
    "cmbc.com.cn",
    "dbs.com",
    "hsbc.com",
    "icbc.com.cn",
    "ocbc.com",
    "paypal.com",
    "payoneer.com",
    "pingan.com.cn",
    "psbc.com",
    "spdb.com.cn",
    "stripe.com",
    "tenpay.com",
    "uobgroup.com",
    "unionpay.com",
    "visa.com",
}
_SINGLETON_HEADERS = {
    "from",
    "subject",
    "message-id",
    "auto-submitted",
    "precedence",
    "list-id",
    "list-unsubscribe",
    "list-post",
    "return-path",
    "x-autoreply",
    "x-auto-response-suppress",
    "references",
}


class _HTMLTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0
        self._blockquote_depth = 0
        self._quote_div_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag == "blockquote":
            self._blockquote_depth += 1
            return
        if self._blockquote_depth:
            return
        if tag == "div":
            if self._quote_div_depth:
                self._quote_div_depth += 1
                return
            values = " ".join(value or "" for name, value in attrs if name in {"class", "id"})
            tokens = set(values.lower().split())
            if tokens.intersection({"gmail_quote", "yahoo_quoted"}):
                self._quote_div_depth = 1
                return
        if self._quote_div_depth:
            return
        if tag in {"script", "style", "head"}:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag in {"br", "p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "blockquote" and self._blockquote_depth:
            self._blockquote_depth -= 1
            return
        if self._blockquote_depth:
            return
        if tag == "div" and self._quote_div_depth:
            self._quote_div_depth -= 1
            return
        if self._quote_div_depth:
            return
        if tag in {"script", "style", "head"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and tag in {"p", "div", "li", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0 and not self._blockquote_depth and not self._quote_div_depth:
            self.parts.append(data)

    def text(self) -> str:
        return html.unescape("".join(self.parts))


def _remove_whitespace(value: str) -> str:
    return "".join(value.split())


def _is_quote_or_signature(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("--") or stripped.startswith(">"):
        return True
    return any(pattern.match(stripped) for pattern in _QUOTE_PATTERNS)


def first_unquoted_nonempty_line(body: str) -> str | None:
    """Return the first content line before a signature/quoted history marker."""

    for line in body.splitlines():
        if _is_quote_or_signature(line):
            break
        if line.strip():
            return line.strip()
    return None


def exact_command(subject: str, body: str) -> str | None:
    """Recognize only an exact command in subject or first safe body line."""

    subject_command = _COMMANDS.get(_remove_whitespace(subject or ""))
    first_line = first_unquoted_nonempty_line(body or "")
    body_command = _COMMANDS.get(first_line.strip()) if first_line is not None else None
    if subject_command and body_command and subject_command != body_command:
        return None
    return subject_command or body_command


def _decode_body_data(data: str) -> str:
    if len(data) > ((MAX_INLINE_BODY_BYTES + 2) // 3) * 4 + 4:
        return ""
    try:
        padding = "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(data + padding).decode("utf-8", errors="replace")
    except (ValueError, UnicodeError):
        return ""


def _part_is_attachment(part: Mapping[str, Any]) -> bool:
    if part.get("filename"):
        return True
    for header in part.get("headers", []) or []:
        if str(header.get("name", "")).lower() == "content-disposition":
            if "attachment" in str(header.get("value", "")).lower():
                return True
    return False


def _inline_text_parts(part: Mapping[str, Any]) -> Iterator[tuple[str, str]]:
    """Yield inline text already present in the message resource.

    A body containing only ``attachmentId`` is deliberately ignored instead of
    issuing an attachments.get request.
    """

    if _part_is_attachment(part):
        return
    body = part.get("body", {}) or {}
    mime_type = str(part.get("mimeType", "")).lower()
    if mime_type == "message/rfc822":
        return
    data = body.get("data")
    if data and mime_type in {"text/plain", "text/html"}:
        yield mime_type, _decode_body_data(str(data))
    for child in part.get("parts", []) or []:
        yield from _inline_text_parts(child)


def extract_body(payload: Mapping[str, Any]) -> str:
    parts = list(_inline_text_parts(payload))
    plain = [text for mime, text in parts if mime == "text/plain"]
    if plain:
        return "\n".join(plain)[:MAX_INLINE_BODY_BYTES]
    html_parts = [text for mime, text in parts if mime == "text/html"]
    rendered: list[str] = []
    for source in html_parts:
        parser = _HTMLTextExtractor()
        try:
            parser.feed(source)
            rendered.append(parser.text())
        except Exception:
            continue
    return "\n".join(rendered)[:MAX_INLINE_BODY_BYTES]


def headers_by_name(payload: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in payload.get("headers", []) or []:
        name = str(item.get("name", "")).lower()
        if not name:
            continue
        if name in result and name in _SINGLETON_HEADERS:
            raise ValueError("message contains a duplicated singleton header")
        if name not in result:
            result[name] = str(item.get("value", ""))
    return result


def _is_non_personal_sender(sender: str) -> bool:
    """Return True for common official, service, marketing or financial mailboxes."""

    local_part, domain = sender.rsplit("@", 1)
    local_part = local_part.casefold()
    domain = domain.casefold().rstrip(".")
    collapsed = re.sub(r"[._+]+", "-", local_part).strip("-")
    if any(
        collapsed == blocked or collapsed.startswith(blocked + "-")
        for blocked in _NON_PERSONAL_LOCAL_PARTS
    ):
        return True

    domain_labels = [label for label in re.split(r"[^a-z0-9]+", domain) if label]
    domain_tokens = set(domain_labels)
    if domain_tokens.intersection(_NON_PERSONAL_DOMAIN_TOKENS | _FINANCIAL_DOMAIN_TOKENS):
        return True
    return any(
        domain == suffix or domain.endswith("." + suffix)
        for suffix in _FINANCIAL_DOMAIN_SUFFIXES
    )


def sender_is_safe(headers: Mapping[str, str], owner: str) -> bool:
    """Reject the owner, bounces, auto-replies, lists, and service mail."""

    try:
        sender = normalize_sender(headers.get("from", ""))
    except ValueError:
        return False
    if sender == normalize_sender(owner):
        return False
    if _is_non_personal_sender(sender):
        return False
    local_part = sender.split("@", 1)[0]
    collapsed = re.sub(r"[._+]", "-", local_part)
    if any(
        collapsed == blocked or collapsed.startswith(blocked + "-")
        for blocked in _AUTOMATED_LOCAL_PARTS
    ):
        return False
    auto_submitted = headers.get("auto-submitted", "").strip().lower()
    if auto_submitted and auto_submitted != "no":
        return False
    if headers.get("precedence", "").strip().lower() in {"bulk", "junk", "list"}:
        return False
    if any(
        name in headers
        for name in ("list-id", "list-unsubscribe", "list-post", "x-autoreply")
    ):
        return False
    if headers.get("return-path", "").strip() == "<>":
        return False
    if "all" in headers.get("x-auto-response-suppress", "").lower():
        return False
    return True


def build_query(owner: str) -> str:
    owner_address = normalize_sender(owner)
    return (
        f'newer_than:7d -in:spam -in:trash -in:sent -label:"{PROCESSED_LABEL}" '
        f'{{\u8ba2\u9605 \u9000\u8ba2}} -from:{owner_address} -from:mailer-daemon '
        "-from:postmaster -from:no-reply -from:noreply"
    )


def iter_candidate_ids(service: Any, owner: str, limit: int) -> Iterator[str]:
    """Page Gmail IDs up to a bounded discovery ceiling.

    Command processing remains capped at ``MAX_MESSAGES``. Discovery may read
    metadata for more candidates so the globally oldest commands are selected.
    """

    remaining = min(max(0, int(limit)), MAX_DISCOVERY_MESSAGES)
    page_token: str | None = None
    while remaining:
        request = service.users().messages().list(
            userId="me",
            q=build_query(owner),
            maxResults=min(remaining, 500),
            pageToken=page_token,
        )
        response = request.execute()
        messages = response.get("messages", []) or []
        for item in messages[:remaining]:
            message_id = item.get("id")
            if message_id:
                yield str(message_id)
                remaining -= 1
        page_token = response.get("nextPageToken")
        if not remaining:
            if page_token:
                raise StateError("candidate discovery limit exceeded")
            return
        if not page_token or not messages:
            return


def find_processed_label(service: Any) -> str | None:
    response = service.users().labels().list(userId="me").execute()
    for label in response.get("labels", []) or []:
        if label.get("name") == PROCESSED_LABEL:
            return str(label["id"])
    return None


def ensure_processed_label(service: Any) -> str:
    existing = find_processed_label(service)
    if existing:
        return existing
    try:
        created = service.users().labels().create(
            userId="me",
            body={
                "name": PROCESSED_LABEL,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        ).execute()
        return str(created["id"])
    except Exception as exc:
        if getattr(getattr(exc, "resp", None), "status", None) == 409:
            existing = find_processed_label(service)
            if existing:
                return existing
        raise


def add_processed_label(service: Any, message_id: str, label_id: str) -> None:
    service.users().messages().modify(
        userId="me", id=message_id, body={"addLabelIds": [label_id]}
    ).execute()


def _reply_subject(original_subject: str) -> str:
    return original_subject.strip() or "\u8ba2\u9605\u7ba1\u7406"


def deterministic_reply_message_id(source_message_id: str, owner: str) -> str:
    digest = hashlib.sha256(source_message_id.encode("ascii")).hexdigest()[:32]
    domain = normalize_sender(owner).split("@", 1)[1]
    return f"<daily-brief-subscription-{digest}@{domain}>"


def thread_has_reply(service: Any, thread_id: str, reply_message_id: str) -> bool:
    """Check thread metadata before retrying a send after an uncertain failure."""

    resource = service.users().threads().get(
        userId="me",
        id=thread_id,
        format="metadata",
        metadataHeaders=["Message-ID"],
    ).execute()
    expected = reply_message_id.strip()
    for message in resource.get("messages", []) or []:
        headers = headers_by_name((message.get("payload", {}) or {}))
        if headers.get("message-id", "").strip() == expected:
            return True
    return False


def send_thread_reply(
    service: Any,
    *,
    owner: str,
    sender: str,
    subject: str,
    message_id_header: str,
    original_references: str,
    thread_id: str,
    reply_message_id: str,
    body: str,
) -> None:
    message = EmailMessage()
    message["From"] = normalize_sender(owner)
    message["To"] = normalize_sender(sender)
    message["Subject"] = _reply_subject(subject)
    message["Message-ID"] = reply_message_id
    message["Auto-Submitted"] = "auto-replied"
    if message_id_header:
        message["In-Reply-To"] = message_id_header
        references = re.findall(r"<[^<>\s]{1,200}>", original_references or "")[-20:]
        if message_id_header not in references:
            references.append(message_id_header)
        message["References"] = " ".join(references)
    message.set_content(body)
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    service.users().messages().send(
        userId="me", body={"raw": encoded, "threadId": thread_id}
    ).execute()


def load_gmail_service(token_path: Path, owner: str) -> Any:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("Gmail API dependencies are not installed") from exc

    if not token_path.is_file():
        raise RuntimeError("Gmail OAuth token is missing; run gmail_oauth_setup.py")
    if stat.S_IMODE(token_path.stat().st_mode) & 0o077:
        raise RuntimeError("Gmail OAuth token permissions are too broad")
    credentials = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if credentials.expired and credentials.refresh_token:
        credentials.refresh(Request())
        from subscriber_store import write_atomic

        # credentials JSON contains no subscriber state, but the same durable
        # replacement prevents a timer interruption from corrupting the token.
        import json

        write_atomic(token_path, json.loads(credentials.to_json()))
    if not credentials.valid:
        raise RuntimeError("Gmail OAuth credentials are not valid")
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()
    try:
        authorized_owner = normalize_sender(str(profile.get("emailAddress", "")))
    except ValueError as exc:
        raise RuntimeError("Gmail profile has no usable account") from exc
    if authorized_owner != normalize_sender(owner):
        raise RuntimeError("Gmail OAuth token belongs to a different account")
    return service


def process_messages(
    service: Any,
    store: SubscriberStore,
    journal: CommandJournal,
    *,
    owner: str,
    max_messages: int = MAX_MESSAGES,
    dry_run: bool = False,
) -> dict[str, int]:
    counts = {
        "new": 0,
        "removed": 0,
        "duplicate": 0,
        "ignored": 0,
        "failed": 0,
    }
    outcome_count = {
        "new_subscription": "new",
        "unsubscribed": "removed",
        "already_subscribed": "duplicate",
        "not_subscribed": "duplicate",
    }
    label_id = find_processed_label(service) if dry_run else ensure_processed_label(service)
    if not dry_run:
        journal.prune_labeled(max_age_days=8)

    # Discover the whole bounded seven-day candidate set using metadata only,
    # then select the globally oldest batch before reading any body or mutating
    # Gmail/state. This preserves order across batches larger than 100.
    try:
        candidate_ids = list(iter_candidate_ids(service, owner, MAX_DISCOVERY_MESSAGES))
    except Exception:
        counts["failed"] += 1
        return counts

    metadata: list[dict[str, Any]] = []
    for message_id in candidate_ids:
        try:
            item = service.users().messages().get(
                userId="me", id=message_id, format="metadata", metadataHeaders=[]
            ).execute()
            metadata.append(item)
        except Exception:
            counts["failed"] += 1
            return counts

    metadata.sort(
        key=lambda item: (int(item.get("internalDate", 0)), str(item.get("id", "")))
    )
    selected_ids = [str(item.get("id", "")) for item in metadata[:max_messages]]
    if any(not message_id for message_id in selected_ids):
        counts["failed"] += 1
        return counts

    resources: list[dict[str, Any]] = []
    for message_id in selected_ids:
        try:
            resources.append(
                service.users().messages().get(
                    userId="me", id=message_id, format="full"
                ).execute()
            )
        except Exception:
            counts["failed"] += 1
            return counts

    # Gmail search results are normally newest-first. Commands must be applied
    # oldest-first so multiple commands from one sender preserve mailbox order.
    resources.sort(key=lambda item: (int(item.get("internalDate", 0)), str(item.get("id", ""))))

    compatible_replays = {
        "new_subscription": {"new_subscription", "already_subscribed"},
        "unsubscribed": {"unsubscribed", "not_subscribed"},
    }
    for resource in resources:
        message_id = str(resource.get("id", ""))
        if not message_id:
            counts["failed"] += 1
            break
        try:
            payload = resource.get("payload", {}) or {}
            label_ids = set(resource.get("labelIds", []) or [])
            forbidden_label_ids = {"SPAM", "TRASH", "SENT"}
            if label_id:
                forbidden_label_ids.add(str(label_id))
            if label_ids.intersection(forbidden_label_ids):
                counts["ignored"] += 1
                continue
            if str(payload.get("mimeType", "")).lower() == "multipart/report":
                counts["ignored"] += 1
                continue
            headers = headers_by_name(payload)
            if not sender_is_safe(headers, owner):
                if not dry_run:
                    add_processed_label(service, message_id, str(label_id))
                counts["ignored"] += 1
                continue

            command = exact_command(headers.get("subject", ""), extract_body(payload))
            if command is None:
                if not dry_run:
                    add_processed_label(service, message_id, str(label_id))
                counts["ignored"] += 1
                continue

            if dry_run:
                counts["ignored"] += 1
                continue

            sender = normalize_sender(headers["from"])
            thread_id = str(resource["threadId"])
            record = journal.get(message_id)
            if record is None:
                outcome = store.preview(sender, command)
                record = journal.prepare(
                    message_id,
                    command=command,
                    outcome=outcome,
                    thread_id=thread_id,
                    reply_message_id=deterministic_reply_message_id(message_id, owner),
                )
            elif record["command"] != command or record["thread_id"] != thread_id:
                raise StateError("journal record does not match Gmail message")

            outcome = str(record["outcome"])
            phase = str(record["phase"])
            if phase == "prepared":
                if outcome in compatible_replays:
                    actual = store.apply(sender, command)
                    if actual not in compatible_replays[outcome]:
                        raise StateError("subscriber state conflicts with journaled outcome")
                record = journal.advance(message_id, "state_applied")
                phase = str(record["phase"])

            if phase == "state_applied":
                reply_message_id = str(record["reply_message_id"])
                if not thread_has_reply(service, thread_id, reply_message_id):
                    send_thread_reply(
                        service,
                        owner=owner,
                        sender=sender,
                        subject=headers.get("subject", ""),
                        message_id_header=headers.get("message-id", ""),
                        original_references=headers.get("references", ""),
                        thread_id=thread_id,
                        reply_message_id=reply_message_id,
                        body=REPLIES[outcome],
                    )
                record = journal.advance(message_id, "replied")
                phase = str(record["phase"])

            if phase == "replied":
                add_processed_label(service, message_id, str(label_id))
                record = journal.advance(message_id, "labeled")
                phase = str(record["phase"])
            elif phase == "labeled":
                # If Gmail search still returned it (for example label removal),
                # restore the label without sending or mutating state again.
                add_processed_label(service, message_id, str(label_id))

            if phase != "labeled":
                raise StateError("command did not reach labeled phase")
            counts[outcome_count[outcome]] += 1
        except Exception:
            # Never log sender addresses or message content. A nonzero exit lets
            # systemd surface the failure while leaving the message unlabelled.
            # Stop here so a newer command cannot overtake the failed command.
            counts["failed"] += 1
            break
    return counts


def _positive_bounded_int(value: str) -> int:
    parsed = int(value)
    if not 1 <= parsed <= MAX_MESSAGES:
        raise argparse.ArgumentTypeError(f"must be between 1 and {MAX_MESSAGES}")
    return parsed


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    base = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--owner",
        default=os.environ.get("GMAIL_OWNER"),
        help="Gmail account address (or set GMAIL_OWNER)",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=base / "state" / "daily-brief-subscribers.json",
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=base / "secrets" / "gmail-oauth" / "token.json",
    )
    parser.add_argument(
        "--journal-file",
        type=Path,
        default=base / "state" / "gmail-command-journal.json",
    )
    parser.add_argument("--max-messages", type=_positive_bounded_int, default=MAX_MESSAGES)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.owner:
        print("configuration_error=missing_gmail_owner", file=sys.stderr)
        return 2
    try:
        owner = normalize_sender(args.owner)
        service = load_gmail_service(args.token_file, owner)
        store = SubscriberStore(args.state_file, owner)
        journal = CommandJournal(args.journal_file)
        if not args.dry_run:
            store.read()
        counts = process_messages(
            service,
            store,
            journal,
            owner=owner,
            max_messages=args.max_messages,
            dry_run=args.dry_run,
        )
    except Exception:
        print("subscription_manager_error=initialization_failed", file=sys.stderr)
        return 1

    print(
        " ".join(f"{name}={value}" for name, value in counts.items())
        + f" dry_run={str(args.dry_run).lower()}"
    )
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
