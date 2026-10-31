#!/usr/bin/env bash
# Compass DSU rehearsal, inert by default.
#
# Without explicit opt-in this script performs NO external write: it does not
# contact Slack, Compass, Docker, or the deployed pilot. The default run only
# prints the safety summary so the command can be linked from docs safely.
#
# To actually send the one-shot rehearsal DM to the pilot participant set:
#   COMPASS_DSU_TRIAL_CONFIRM=YES-SEND-DSU-DM ./send-compass-dsu-trial.sh
# The app must have Compass writes in mock mode (PULSE_COMPASS_WRITE_MODE=mock)
# before sending; see deploy/README.md.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_CONTAINER="${PULSE_APP_CONTAINER:-pulse-techops-app-1}"
REDIS_CONTAINER="${PULSE_REDIS_CONTAINER:-pulse-techops-redis-1}"
SCHEDULE_ID="${PULSE_SCHEDULE_ID:-1}"
SESSION_KEY="${PULSE_SESSION_KEY:-morgenruf:session:TD9UTSD8V:U09GE1J7HDK}"

printf 'Compass DSU rehearsal (dry run) — nothing sent.\n'
printf '  repo root   : %s\n' "$ROOT"
printf '  app         : %s\n' "$APP_CONTAINER"
printf '  schedule id : %s\n' "$SCHEDULE_ID"
if [[ "${COMPASS_DSU_TRIAL_CONFIRM:-}" != 'YES-SEND-DSU-DM' ]]; then
  printf '  opt-in      : not set — no Slack DM, no Compass writes.\n'
  printf 'Re-run with COMPASS_DSU_TRIAL_CONFIRM=YES-SEND-DSU-DM to send the DM (mock Compass writes only).\n'
  exit 0
fi

if [[ "${PULSE_COMPASS_WRITE_MODE:-}" != 'mock' ]]; then
  printf 'Refusing to send: PULSE_COMPASS_WRITE_MODE is not "mock" on the caller.\n' >&2
  exit 2
fi

"$SCRIPT_DIR/check-compass-dsu-endpoints.sh"

docker exec "$REDIS_CONTAINER" redis-cli DEL "$SESSION_KEY" >/dev/null

PULSE_SCHEDULE_ID="$SCHEDULE_ID" docker exec -i \
  -e PULSE_TEAM_ID -e SLACK_BOT_TOKEN -e PULSE_CHANNEL_ID -e PULSE_SCHEDULE_ID \
  "$APP_CONTAINER" python - <<'PY'
import os
import sys
sys.path.insert(0, "/app/src")
from scheduler import _send_standup_to_workspace
_send_standup_to_workspace(
    os.environ["PULSE_TEAM_ID"],
    os.environ["SLACK_BOT_TOKEN"],
    os.environ["PULSE_CHANNEL_ID"],
    schedule_id=int(os.environ["PULSE_SCHEDULE_ID"]),
)
print("Compass DSU test DM sent with Compass writes in mock mode.")
PY
