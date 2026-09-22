#!/bin/bash
# One-shot 18:00 GT Compass DSU rehearsal; caller enables mock writes in the app.
set -euo pipefail
ROOT='/Users/openjaime/projects/morgenruf'
"$ROOT/deploy/check-compass-dsu-endpoints.sh"
docker exec pulse-techops-redis-1 redis-cli DEL morgenruf:session:TD9UTSD8V:U09GE1J7HDK >/dev/null
docker exec -i pulse-techops-app-1 python - <<'PY'
import os
import sys
sys.path.insert(0, '/app/src')
from scheduler import _send_standup_to_workspace
_send_standup_to_workspace(
    os.environ['PULSE_TEAM_ID'],
    os.environ['SLACK_BOT_TOKEN'],
    os.environ['PULSE_CHANNEL_ID'],
    schedule_id=1,
)
print('Compass DSU 18:00 test DM sent with Compass writes in mock mode.')
PY
