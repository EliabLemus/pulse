#!/bin/bash
# Compass DSU public-ingress watchdog. Silent when external reachability is healthy.
#
# Verification stays external by design: a check-host.net quorum that is healthy
# or inconclusive never triggers any repair. Only a completed failing quorum
# starts the bounded repair chain, each step at most once:
#   1. re-register the Funnel mapping (off/on),
#   2. if ingress is still down externally, one local service-chain repair:
#      a loopback probe decides whether to `docker start` the pilot containers
#      (a no-op when they already run), then Caddy is reloaded — but only after
#      its config passes `caddy validate`.
# Recovery is always proven by a fresh external quorum before reporting success.
#
# This watchdog never restarts or quits Tailscale, never restarts or stops
# containers (docker start is idempotent), never reloads Caddy without a valid
# config, never touches Slack, Compass, or any data, and never restarts GUI apps.
set -euo pipefail

CHECK_HOST_BASE="${CHECK_HOST_BASE:-https://check-host.net}"
# Public health URL is a parameter; the current pilot host is only the default.
HEALTH_URL="${COMPASS_HEALTH_URL:-https://nexus-2.tailf73d68.ts.net/pulse/healthz}"
LOCAL_BACKEND_URL="${COMPASS_LOCAL_BACKEND_URL:-http://127.0.0.1:8081/pulse/healthz}"
LOCAL_CADDYFILE="${COMPASS_CADDYFILE:-$HOME/Caddyfile}"
EXTERNAL_MIN_COMPLETED=2
HEALTH_URL_ENCODED="$(printf '%s' "$HEALTH_URL" | /usr/bin/python3 -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.stdin.read(), safe=""))')"

read -r -a REPAIR_CONTAINERS <<< "${COMPASS_REPAIR_CONTAINERS:-pulse-techops-app-1 pulse-techops-redis-1 pulse-techops-db-1}"

request_id() {
  curl --noproxy '*' -sS --max-time 15 -H 'Accept: application/json' \
    "${CHECK_HOST_BASE}/check-http?host=${HEALTH_URL_ENCODED}&max_nodes=3" 2>/dev/null \
    | /usr/bin/python3 -c 'import json,sys
try:
    value=json.load(sys.stdin).get("request_id", "")
    print(value if isinstance(value, str) else "")
except Exception:
    print("")' 2>/dev/null || true
}

external_state() {
  local request result
  request="$(request_id)"
  if [[ -z "$request" ]]; then
    printf 'inconclusive\n'
    return
  fi

  sleep 12
  result="$(curl --noproxy '*' -sS --max-time 15 -H 'Accept: application/json' \
    "${CHECK_HOST_BASE}/check-result/${request}" 2>/dev/null || true)"
  if [[ -z "$result" ]]; then
    printf 'inconclusive\n'
    return
  fi

  printf '%s' "$result" | /usr/bin/python3 -c "import json,sys
try:
    payload=json.load(sys.stdin)
except Exception:
    print('inconclusive')
    raise SystemExit
if not isinstance(payload, dict):
    print('inconclusive')
    raise SystemExit
completed = healthy = 0
for entries in payload.values():
    if not isinstance(entries, list) or not entries or not isinstance(entries[0], list):
        continue
    entry = entries[0]
    if len(entry) < 4:
        continue
    completed += 1
    if entry[0] == 1 and str(entry[3]) == '200':
        healthy += 1
if healthy:
    print('healthy')
elif completed >= ${EXTERNAL_MIN_COMPLETED}:
    print('down')
else:
    print('inconclusive')" 2>/dev/null || printf 'inconclusive\n'
}

local_backend_ok() {
  curl --noproxy '*' -sS --max-time 5 -o /dev/null "$LOCAL_BACKEND_URL" 2>/dev/null
}

local_repair() {
  # Bounded and non-destructive: `docker start` is a no-op for running
  # containers, and Caddy is only reloaded after `caddy validate` passes.
  if ! local_backend_ok; then
    docker start "${REPAIR_CONTAINERS[@]}" >/dev/null 2>&1 || true
  fi
  if caddy validate --config "$LOCAL_CADDYFILE" --adapter caddyfile >/dev/null 2>&1; then
    caddy reload --config "$LOCAL_CADDYFILE" --adapter caddyfile >/dev/null 2>&1 || true
  fi
}

case "$(external_state)" in
  down)
    ;;
  *)
    # Healthy or inconclusive: stay silent, repair nothing.
    exit 0
    ;;
esac

# A completed external quorum failed. Re-register only the Funnel mapping.
tailscale funnel --https=443 off >/dev/null 2>&1 || true
tailscale funnel --bg --yes http://localhost:8081 >/dev/null 2>&1 || true

if [[ "$(external_state)" == 'healthy' ]]; then
  printf 'Compass DSU watchdog restored public Funnel ingress.\n'
  exit 0
fi

# Funnel re-registration did not restore ingress. One bounded local
# service-chain repair, then a final external proof. Never a second reset.
local_repair

if [[ "$(external_state)" == 'healthy' ]]; then
  printf 'Compass DSU watchdog restored public Funnel ingress after local service-chain repair.\n'
  exit 0
fi

printf 'ALERT: Compass DSU public Funnel ingress remains unavailable after registration reset and local repair. %s\n' "$HEALTH_URL" >&2
exit 1
