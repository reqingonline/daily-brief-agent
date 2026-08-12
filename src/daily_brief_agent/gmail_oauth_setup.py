"""One-time Gmail OAuth authorization for the VPS subscription worker."""

from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path

from .subscriber_store import write_atomic


SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    base = Path(__file__).resolve().parents[2] / "secrets" / "gmail-oauth"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--owner",
        default=os.environ.get("GMAIL_OWNER"),
        help="Expected Gmail account (or set GMAIL_OWNER)",
    )
    parser.add_argument("--client-secret", type=Path, default=base / "client_secret.json")
    parser.add_argument("--token-file", type=Path, default=base / "token.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.owner:
        print("oauth_setup_error=owner_missing", file=sys.stderr)
        return 2
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        print("oauth_setup_error=refuse_root", file=sys.stderr)
        return 2
    if not args.client_secret.is_file():
        print("oauth_setup_error=client_secret_missing", file=sys.stderr)
        return 2
    if stat.S_IMODE(args.client_secret.stat().st_mode) & 0o077:
        print("oauth_setup_error=client_secret_permissions", file=sys.stderr)
        return 2
    if args.token_file.exists() and stat.S_IMODE(args.token_file.stat().st_mode) & 0o077:
        print("oauth_setup_error=token_permissions", file=sys.stderr)
        return 2
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("oauth_setup_error=dependency_missing", file=sys.stderr)
        return 2

    os.umask(0o077)
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(args.client_secret), SCOPES)
        credentials = flow.run_local_server(
            host="127.0.0.1",
            bind_addr="127.0.0.1",
            port=8765,
            open_browser=False,
            timeout_seconds=600,
            prompt="consent",
            login_hint=args.owner,
            authorization_prompt_message=(
                "Open this URL in your local browser through the SSH tunnel:\n{url}"
            ),
            success_message="Gmail authorization completed. You may close this tab.",
        )
        profile = build(
            "gmail", "v1", credentials=credentials, cache_discovery=False
        ).users().getProfile(userId="me").execute()
        from subscriber_store import normalize_sender

        authorized_owner = normalize_sender(str(profile.get("emailAddress", "")))
        expected_owner = normalize_sender(args.owner)
    except Exception:
        print("oauth_setup_error=authorization_failed", file=sys.stderr)
        return 1
    if authorized_owner != expected_owner:
        print("oauth_setup_error=account_mismatch", file=sys.stderr)
        return 1
    try:
        write_atomic(args.token_file, json.loads(credentials.to_json()))
        os.chmod(args.token_file, 0o600)
    except Exception:
        print("oauth_setup_error=token_write_failed", file=sys.stderr)
        return 1
    print("oauth_setup=complete token_permissions=0600")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
