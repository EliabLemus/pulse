#!/usr/bin/env bash
# Refresh read-only Compass task snapshots in one ephemeral container process.
set -euo pipefail

CONTAINER="${PULSE_APP_CONTAINER:-pulse-techops-app-1}"
COMPASS_API_KEY="$(security find-generic-password -s 'Compass MCP API key' -w)"
[[ "$COMPASS_API_KEY" == cmp_* ]] || {
  printf 'Invalid Compass MCP API key in host Keychain\n' >&2
  exit 2
}

exec docker exec \
  -e "COMPASS_API_KEY=$COMPASS_API_KEY" \
  -e 'PULSE_COMPASS_WRITE_MODE=' \
  -w /app \
  "$CONTAINER" \
  python -m src.modules.standup.context_worker
