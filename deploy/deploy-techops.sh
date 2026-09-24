#!/usr/bin/env bash
# Deploy the Pulse TechOps pilot without printing secrets or deleting data.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.techops.yml"
ENV_FILE="$SCRIPT_DIR/.env.techops"
PROJECT_NAME="pulse-techops"

usage() {
  printf 'Usage: %s [--env-file PATH]\n' "${0##*/}" >&2
}

if [[ "${1:-}" == "--env-file" ]]; then
  [[ -n "${2:-}" ]] || { usage; exit 2; }
  ENV_FILE="$2"
  shift 2
fi
[[ $# -eq 0 ]] || { usage; exit 2; }
[[ -f "$ENV_FILE" ]] || { printf 'Missing environment file: %s\n' "$ENV_FILE" >&2; exit 2; }

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

required=(PULSE_DB_PASSWORD DATABASE_URL SLACK_BOT_TOKEN SLACK_SIGNING_SECRET FLASK_SECRET_KEY APP_URL PULSE_PORT PULSE_TEAM_ID PULSE_TEAM_NAME PULSE_BOT_USER_ID PULSE_APP_ID PULSE_PARTICIPANT_ID PULSE_CHANNEL_ID PULSE_MANAGER_ID)
missing=()
for key in "${required[@]}"; do
  value="${!key:-}"
  if [[ -z "$value" || "$value" == *REPLACE_ME* || "$value" == *CHANGE_TO_* || "$value" == *PULSE_PUBLIC_HOST* ]]; then
    missing+=("$key")
  fi
done
if (( ${#missing[@]} )); then
  printf 'Invalid or missing configuration keys: %s\n' "${missing[*]}" >&2
  exit 2
fi
[[ "$SLACK_BOT_TOKEN" == xoxb-* ]] || { printf 'Invalid configuration key: SLACK_BOT_TOKEN\n' >&2; exit 2; }
[[ ${#FLASK_SECRET_KEY} -ge 32 ]] || { printf 'Invalid configuration key: FLASK_SECRET_KEY\n' >&2; exit 2; }
[[ "$APP_URL" == https://* && "$APP_URL" != */ ]] || { printf 'APP_URL must be an HTTPS base URL without a trailing slash\n' >&2; exit 2; }
[[ "$DATABASE_URL" != *'***'* && "$DATABASE_URL" != *"$PULSE_DB_PASSWORD"* ]] && { printf 'DATABASE_URL does not contain the configured database password\n' >&2; exit 2; }

COMPASS_API_KEY="$(security find-generic-password -s 'Compass MCP API key' -w)"
[[ "$COMPASS_API_KEY" == cmp_* ]] || { printf 'Invalid Compass MCP API key in host Keychain\n' >&2; exit 2; }
export COMPASS_API_KEY
export COMPASS_TEAM="${COMPASS_TEAM:-techops}"

compose=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")

# A leftover "mock" exported in the caller's shell silently overrides the
# env-file through compose interpolation and would ship mock Compass writes
# to production. Mock mode is rehearsal-only; strip it from this process.
if [[ "${PULSE_COMPASS_WRITE_MODE:-}" == "mock" ]]; then
  unset PULSE_COMPASS_WRITE_MODE
fi

"${compose[@]}" config --quiet
"${compose[@]}" up -d --build db
"${compose[@]}" run --rm --no-deps migrate
"${compose[@]}" run --rm --no-deps seed
"${compose[@]}" up -d --build app

for _ in {1..20}; do
  if curl --fail --silent --show-error "http://127.0.0.1:${PULSE_PORT}/healthz" >/dev/null; then
    printf 'Pulse is healthy on 127.0.0.1:%s.\n' "$PULSE_PORT"
    exit 0
  fi
  sleep 2
done

printf 'Pulse did not become healthy; inspect with:\n  %s logs app\n' "${compose[*]}" >&2
exit 1
