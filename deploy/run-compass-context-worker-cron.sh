#!/usr/bin/env bash
# Successful snapshot refreshes are silent; failures need an owner decision.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if output="$("$SCRIPT_DIR/run-compass-context-worker.sh" 2>&1)"; then
  exit 0
else
  status=$?
  printf 'Compass task snapshot refresh failed; guided DSU will fail open without ticket context:\n%s\n' "$output" >&2
  exit "$status"
fi
