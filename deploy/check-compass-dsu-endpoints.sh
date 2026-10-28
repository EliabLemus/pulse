#!/bin/bash
# Compass DSU public-ingress watchdog. Silent when external reachability is healthy.
set -euo pipefail

CHECK_HOST_BASE="${CHECK_HOST_BASE:-https://check-host.net}"
HEALTH_URL='https://nexus-2.tailf73d68.ts.net/pulse/healthz'
HEALTH_URL_ENCODED='https%3A%2F%2Fnexus-2.tailf73d68.ts.net%2Fpulse%2Fhealthz'
EXTERNAL_MIN_COMPLETED=2

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

case "$(external_state)" in
  healthy|inconclusive)
    exit 0
    ;;
  down)
    ;;
  *)
    exit 0
    ;;
esac

# A completed external quorum failed. Re-register only the Funnel mapping;
# never restart Tailscale, Caddy, Docker, Slack, or Compass from this watchdog.
tailscale funnel --https=443 off >/dev/null 2>&1 || true
tailscale funnel --bg --yes http://localhost:8081 >/dev/null 2>&1 || true

if [[ "$(external_state)" == 'healthy' ]]; then
  printf 'Compass DSU watchdog restored public Funnel ingress.\n'
  exit 0
fi

printf 'ALERT: Compass DSU public Funnel ingress remains unavailable after registration reset. %s\n' "$HEALTH_URL" >&2
exit 1
