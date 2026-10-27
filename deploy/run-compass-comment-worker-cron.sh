#!/usr/bin/env bash
# Silent successful Compass comment delivery; surface only failures/unknowns.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if output="$("$SCRIPT_DIR/run-compass-comment-worker.sh" --limit 25 2>&1)"; then
  exit 0
else
  status=$?
  printf 'Compass comment worker failed; manual review required:\n%s\n' "$output" >&2
  exit "$status"
fi
