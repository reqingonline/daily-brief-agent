"""Validated, atomic storage for daily-brief subscribers.

Only ``subscribers`` and ``updated_at`` are ever changed by command handling.
The ``fixed_recipients`` field is retained for schema compatibility but is not
used by delivery and is never modified here.
"""

from __future__ import annotations

import copy
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any, Mapping


REQUIRED_KEYS = {
    "version",
    "owner",
    "fixed_recipients",
    "subscribers",
    "updated_at",
}
CHINA_TZ = timezone(timedelta(hours=8))
_EMAIL_RE = re.compile(r"^[^\s@<>]+@[^\s@<>]+\.[^\s@<>]+$")


class StateError(RuntimeError):
    """Raised when subscriber state cannot be safely read or written."""


def normalize_sender(value: str) -> str:
    """Return one normalized mailbox address, rejecting ambiguous input."""

    if not isinstance(value, str) or "\r" in value or "\n" in value:
        raise ValueError("sender has no usable email address")
    parsed = getaddresses([value])
    if len(parsed) != 1:
        raise ValueError("sender has no usable email address")
    _display_name, address = parsed[0]
    address = address.strip().lower()
    if not address or not _EMAIL_RE.fullmatch(address):
        raise ValueError("sender has no usable email address")
    return address


def _validate_address_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise StateError(f"{field} must be an array")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise StateError(f"{field} must contain only strings")
        try:
            result.append(normalize_sender(item))
        except ValueError as exc:
            raise StateError(f"{field} contains an invalid address") from exc
    return result


def validate_state(value: Any, expected_owner: str | None = None) -> dict[str, Any]:
    """Validate schema while preserving all existing fields and values."""

    if not isinstance(value, dict):
        raise StateError("subscriber state must be an object")
    missing = REQUIRED_KEYS.difference(value)
    if missing:
        raise StateError("subscriber state is missing required fields")
    if not isinstance(value["version"], int) or isinstance(value["version"], bool):
        raise StateError("version must be an integer")
    if not isinstance(value["owner"], str):
        raise StateError("owner must be a string")
    try:
        owner = normalize_sender(value["owner"])
    except ValueError as exc:
        raise StateError("owner is invalid") from exc
    if expected_owner is not None and owner != normalize_sender(expected_owner):
        raise StateError("owner does not match configured Gmail account")
    _validate_address_list(value["fixed_recipients"], "fixed_recipients")
    _validate_address_list(value["subscribers"], "subscribers")
    if not isinstance(value["updated_at"], str) or not value["updated_at"].strip():
        raise StateError("updated_at must be a nonempty string")
    return copy.deepcopy(value)


def write_atomic(path: Path, value: Mapping[str, Any]) -> None:
    """Durably replace *path* without exposing a partially written file."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_name: str | None = None
    try:
        with NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as tmp:
            temp_name = tmp.name
            json.dump(value, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp.flush()
            os.fsync(tmp.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, path)
        temp_name = None
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
        except (AttributeError, OSError):
            directory_fd = None
        if directory_fd is not None:
            try:
                try:
                    os.fsync(directory_fd)
                except OSError:
                    # The file itself is already fsynced. Some filesystems do
                    # not support directory fsync; do not report a false write
                    # failure after the atomic replacement has completed.
                    pass
            finally:
                os.close(directory_fd)
    except Exception as exc:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except FileNotFoundError:
                pass
        raise StateError("could not atomically write subscriber state") from exc


class SubscriberStore:
    """Read and update a subscriber-state JSON file."""

    def __init__(self, path: str | Path, expected_owner: str):
        self.path = Path(path)
        self.expected_owner = normalize_sender(expected_owner)

    def initialize(self, value: Mapping[str, Any], *, overwrite: bool = False) -> None:
        if self.path.exists() and not overwrite:
            raise StateError("subscriber state already exists")
        validated = validate_state(dict(value), self.expected_owner)
        validated["subscribers"] = sorted(set(_validate_address_list(
            validated["subscribers"], "subscribers"
        )))
        write_atomic(self.path, validated)

    def read(self) -> dict[str, Any]:
        try:
            with self.path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError("could not read subscriber state") from exc
        return validate_state(value, self.expected_owner)

    def apply(self, sender: str, command: str) -> str:
        address = normalize_sender(sender)
        if command not in {"subscribe", "unsubscribe"}:
            raise ValueError("unsupported subscription command")

        current = self.read()
        normalized = set(_validate_address_list(current["subscribers"], "subscribers"))

        if command == "subscribe":
            if address in normalized:
                return "already_subscribed"
            normalized.add(address)
            outcome = "new_subscription"
        else:
            if address not in normalized:
                return "not_subscribed"
            normalized.remove(address)
            outcome = "unsubscribed"

        updated = copy.deepcopy(current)
        updated["subscribers"] = sorted(normalized)
        updated["updated_at"] = datetime.now(CHINA_TZ).isoformat(timespec="seconds")
        write_atomic(self.path, validate_state(updated, self.expected_owner))
        return outcome

    def preview(self, sender: str, command: str) -> str:
        """Compute an outcome without changing state (used before journaling)."""

        address = normalize_sender(sender)
        if command not in {"subscribe", "unsubscribe"}:
            raise ValueError("unsupported subscription command")
        current = self.read()
        normalized = set(_validate_address_list(current["subscribers"], "subscribers"))
        if command == "subscribe":
            return "already_subscribed" if address in normalized else "new_subscription"
        return "unsubscribed" if address in normalized else "not_subscribed"
