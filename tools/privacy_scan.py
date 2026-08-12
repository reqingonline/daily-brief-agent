#!/usr/bin/env python3
"""Scan tracked files and Git history for accidental private release material."""

from __future__ import annotations

import argparse
import ipaddress
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


@dataclass(frozen=True, order=True)
class Finding:
    rule: str
    path: str
    revision: str = "working-tree"


EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
IPV4_RE = re.compile(r"(?<![0-9.])(?:\d{1,3}\.){3}\d{1,3}(?![0-9.])")
PRIVATE_KEY_RE = re.compile(
    ("BEGIN " + "(?:RSA |OPENSSH |EC )?" + "PRIVATE KEY").encode("ascii")
)
TOKEN_RES = (
    re.compile(("gh" + "[opusr]_[A-Za-z0-9]{20,}").encode("ascii")),
    re.compile(("github" + "_pat_[A-Za-z0-9_]{20,}").encode("ascii")),
    re.compile(("sk" + "-[A-Za-z0-9]{20,}").encode("ascii")),
    re.compile(("AKIA" + "[0-9A-Z]{16}").encode("ascii")),
)
PRODUCTION_PATH_RES = (
    re.compile(rb"/home/[A-Za-z0-9._-]+/"),
    re.compile(rb"[A-Za-z]:\\Users\\[^\\\r\n]+\\"),
)
RUNTIME_DIRS = {"logs", "secrets", "workspace", "backups", ".venv", "__pycache__"}
FORBIDDEN_BASENAMES = {
    ".env",
    "codex-runtime.env",
    "token.json",
    "client_secret.json",
    "daily-brief-subscribers.json",
    "gmail-command-journal.json",
    "subscription-preflight.ok",
}
GENERATED_NAME_RE = re.compile(
    r"(?:sent-message|last-message|rejected-message|dry-run-message|source-bundle|editorial-context)-?.*\.(?:md|json)$",
    re.IGNORECASE,
)


def run_git(root: Path, *args: str, check: bool = True) -> bytes:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(completed.stderr.decode("utf-8", "replace").strip())
    return completed.stdout


def tracked_paths(root: Path) -> list[str]:
    raw = run_git(root, "ls-files", "-z")
    return [item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item]


def history_entries(root: Path) -> Iterable[tuple[str, str, bytes]]:
    commits = run_git(root, "rev-list", "--all", check=False).decode("ascii", "ignore").split()
    seen: set[tuple[str, str]] = set()
    for commit in commits:
        raw = run_git(root, "ls-tree", "-rz", "--full-tree", commit)
        for entry in raw.split(b"\0"):
            if not entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            object_id = metadata.split()[2].decode("ascii")
            path = raw_path.decode("utf-8", "surrogateescape")
            key = (object_id, path)
            if key in seen:
                continue
            seen.add(key)
            yield commit[:12], path, run_git(root, "show", f"{commit}:{path}")


def filename_findings(path: str, revision: str) -> list[Finding]:
    normalized = PurePosixPath(path.replace("\\", "/"))
    parts = set(normalized.parts)
    findings: list[Finding] = []
    if parts & RUNTIME_DIRS:
        findings.append(Finding("runtime-directory", path, revision))
    if normalized.name in FORBIDDEN_BASENAMES:
        findings.append(Finding("runtime-or-secret-file", path, revision))
    if GENERATED_NAME_RE.search(normalized.name):
        findings.append(Finding("generated-report-or-bundle", path, revision))
    if normalized.suffix.lower() in {".pem", ".p12", ".pfx"} or normalized.name.endswith(".key"):
        findings.append(Finding("private-key-file", path, revision))
    return findings


def content_findings(path: str, data: bytes, revision: str) -> list[Finding]:
    if b"\0" in data:
        return []
    findings: list[Finding] = []
    if PRIVATE_KEY_RE.search(data):
        findings.append(Finding("private-key-content", path, revision))
    if any(pattern.search(data) for pattern in TOKEN_RES):
        findings.append(Finding("token-pattern", path, revision))
    if any(pattern.search(data) for pattern in PRODUCTION_PATH_RES):
        findings.append(Finding("private-home-path", path, revision))

    text = data.decode("utf-8", "replace")
    for match in EMAIL_RE.finditer(text):
        domain = match.group(1).lower()
        if domain in {"example.com", "example.org", "example.net", "users.noreply.github.com"}:
            continue
        if domain.endswith(".example") or domain.endswith(".invalid"):
            continue
        findings.append(Finding("non-example-email", path, revision))
        break

    for match in IPV4_RE.finditer(text):
        try:
            address = ipaddress.ip_address(match.group(0))
        except ValueError:
            continue
        if address.is_private or address.is_loopback or address.is_link_local or address.is_multicast:
            continue
        if address in ipaddress.ip_network("192.0.2.0/24"):
            continue
        if address in ipaddress.ip_network("198.51.100.0/24"):
            continue
        if address in ipaddress.ip_network("203.0.113.0/24"):
            continue
        findings.append(Finding("public-ipv4", path, revision))
        break
    return findings


def scan_repository(root: Path, *, include_history: bool = True) -> list[Finding]:
    root = root.resolve()
    findings: set[Finding] = set()
    for path in tracked_paths(root):
        findings.update(filename_findings(path, "working-tree"))
        findings.update(content_findings(path, (root / path).read_bytes(), "working-tree"))
    if include_history:
        for revision, path, data in history_entries(root):
            findings.update(filename_findings(path, revision))
            findings.update(content_findings(path, data, revision))
    return sorted(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--no-history", action="store_true")
    args = parser.parse_args(argv)
    try:
        findings = scan_repository(args.root, include_history=not args.no_history)
    except (OSError, RuntimeError) as exc:
        print(f"privacy_scan_error={type(exc).__name__}", file=sys.stderr)
        return 2
    if findings:
        for finding in findings:
            print(f"privacy_finding={finding.rule} path={finding.path} revision={finding.revision}")
        print(f"privacy_scan=failed findings={len(findings)}")
        return 1
    print("privacy_scan=ok findings=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
