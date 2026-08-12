#!/usr/bin/env bash
set -euo pipefail

umask 077
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd)"
PYTHON="${DAILY_BRIEF_PYTHON:-$BASE_DIR/.venv/bin/python}"
STATE_DIR="${DAILY_BRIEF_STATE_DIR:-$BASE_DIR/state}"
MARKER="${DAILY_BRIEF_SUBSCRIPTION_MARKER:-$STATE_DIR/subscription-preflight.ok}"
MANAGER_MODULE="${BRIEF_SUBSCRIPTION_MODULE:-daily_brief_agent.gmail_subscription_manager}"
started="$(date +%s)"

export PYTHONPATH="$BASE_DIR/src${PYTHONPATH:+:$PYTHONPATH}"
if [[ ! -x "$PYTHON" ]]; then
  echo "subscription_preflight_error=python_missing" >&2
  exit 1
fi

mkdir -p "$STATE_DIR"
rm -f "$MARKER"
marker_tmp="$(mktemp "$STATE_DIR/.subscription-preflight.XXXXXX")"
trap 'rm -f "$marker_tmp"' EXIT

if ! "$PYTHON" -m "$MANAGER_MODULE"; then
  echo "subscription_preflight_error=manager_failed" >&2
  exit 1
fi

printf '%s\n' "$(date +%s)" > "$marker_tmp"
chmod 600 "$marker_tmp"
mv -f "$marker_tmp" "$MARKER"
echo "subscription_preflight=ok"
echo "subscription_preflight_seconds=$(( $(date +%s) - started ))"
