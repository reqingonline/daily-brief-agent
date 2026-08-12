"""Persistent idempotency journal for Gmail subscription commands."""

from __future__ import annotations

import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .subscriber_store import StateError, write_atomic


_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_COMMANDS = {"subscribe", "unsubscribe"}
_OUTCOMES = {
    "new_subscription",
    "already_subscribed",
    "unsubscribed",
    "not_subscribed",
}
_PHASES = ("prepared", "state_applied", "replied", "labeled")


class CommandJournal:
    """Store non-address command progress so retries preserve the first outcome."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read_all(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "messages": {}}
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError("could not read command journal") from exc
        if (
            not isinstance(value, dict)
            or value.get("version") != 1
            or not isinstance(value.get("messages"), dict)
        ):
            raise StateError("command journal has invalid schema")
        for message_id, record in value["messages"].items():
            self._validate_record(message_id, record)
        return value

    @staticmethod
    def _validate_record(message_id: str, record: Any) -> None:
        if not isinstance(message_id, str) or not _MESSAGE_ID_RE.fullmatch(message_id):
            raise StateError("command journal contains an invalid message id")
        if not isinstance(record, dict):
            raise StateError("command journal record must be an object")
        if record.get("command") not in _COMMANDS:
            raise StateError("command journal contains an invalid command")
        if record.get("outcome") not in _OUTCOMES:
            raise StateError("command journal contains an invalid outcome")
        if record.get("phase") not in _PHASES:
            raise StateError("command journal contains an invalid phase")
        if not isinstance(record.get("thread_id"), str) or not record["thread_id"]:
            raise StateError("command journal contains an invalid thread id")
        if "reply_message_id" in record and not isinstance(record["reply_message_id"], str):
            raise StateError("command journal contains an invalid reply message id")
        if not isinstance(record.get("updated_at"), str):
            raise StateError("command journal contains an invalid timestamp")
        try:
            datetime.fromisoformat(record["updated_at"])
        except ValueError as exc:
            raise StateError("command journal contains an invalid timestamp") from exc

    def get(self, message_id: str) -> dict[str, Any] | None:
        if not _MESSAGE_ID_RE.fullmatch(message_id):
            raise StateError("invalid Gmail message id")
        record = self._read_all()["messages"].get(message_id)
        return copy.deepcopy(record) if record is not None else None

    def prepare(
        self,
        message_id: str,
        *,
        command: str,
        outcome: str,
        thread_id: str,
        reply_message_id: str,
    ) -> dict[str, Any]:
        value = self._read_all()
        existing = value["messages"].get(message_id)
        if existing is not None:
            if existing["command"] != command or existing["thread_id"] != thread_id:
                raise StateError("command journal conflicts with Gmail message")
            return copy.deepcopy(existing)
        record = {
            "command": command,
            "outcome": outcome,
            "phase": "prepared",
            "thread_id": thread_id,
            "reply_message_id": reply_message_id,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        self._validate_record(message_id, record)
        value["messages"][message_id] = record
        write_atomic(self.path, value)
        return copy.deepcopy(record)

    def advance(self, message_id: str, phase: str) -> dict[str, Any]:
        if phase not in _PHASES:
            raise ValueError("invalid command phase")
        value = self._read_all()
        record = value["messages"].get(message_id)
        if record is None:
            raise StateError("command journal record is missing")
        old_index = _PHASES.index(record["phase"])
        new_index = _PHASES.index(phase)
        if new_index < old_index or new_index > old_index + 1:
            raise StateError("invalid command phase transition")
        if new_index != old_index:
            record["phase"] = phase
            record["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            write_atomic(self.path, value)
        return copy.deepcopy(record)

    def prune_labeled(self, max_age_days: int = 8) -> int:
        """Remove completed receipts older than the Gmail search window."""

        if max_age_days < 8:
            raise ValueError("journal retention must cover the seven-day search window")
        value = self._read_all()
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        removed = 0
        for message_id, record in list(value["messages"].items()):
            updated = datetime.fromisoformat(record["updated_at"])
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            if record["phase"] == "labeled" and updated < cutoff:
                del value["messages"][message_id]
                removed += 1
        if removed:
            write_atomic(self.path, value)
        return removed
