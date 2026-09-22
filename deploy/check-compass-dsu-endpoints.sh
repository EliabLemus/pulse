#!/bin/bash
# External Compass DSU endpoint watchdog. Silent when healthy.
set -euo pipefail

PUBLIC_BASE='https://nexus-2.tailf73d68.ts.net/pulse'
PROBE_BASE='https://r.jina.ai/https://nexus-2.tailf73d68.ts.net/pulse'
CADDYFILE='/Users/openjaime/Caddyfile'

probe() {
  local path=$1 expected=$2 body status
  body=$(curl --noproxy '*' -fsS --max-time 45 "${PROBE_BASE}${path}" 2>/dev/null || true)
  case "$expected" in
    health) [[ "$body" == *'"status":"ok"'* ]] ;;
    method) [[ "$body" == *'405'* || "$body" == *'Method Not Allowed'* ]] ;;
  esac
}

healthy() {
  probe '/healthz' health && probe '/slack/events' method && probe '/slack/interactions' method
}

if healthy; then
  exit 0
fi

# Repair only the service chain that owns these endpoints; do not rebuild or alter data.
tailscale funnel --bg --yes http://localhost:8081 >/dev/null 2>&1 || true
if caddy validate --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1; then
  caddy reload --config "$CADDYFILE" --adapter caddyfile >/dev/null 2>&1 || true
fi
docker start pulse-techops-app-1 pulse-techops-redis-1 pulse-techops-db-1 >/dev/null 2>&1 || true

if healthy; then
  printf 'Compass DSU watchdog repaired the public endpoint chain.\n'
else
  printf 'ALERT: Compass DSU public endpoints remain unavailable after automatic repair. %s\n' "$PUBLIC_BASE"
  exit 1
fi
