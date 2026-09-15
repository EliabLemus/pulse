#!/usr/bin/env bash
# Stop Pulse TechOps pilot services. Data is preserved unless explicit purge is requested.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COMPOSE_FILE="$SCRIPT_DIR/docker-compose.techops.yml"
ENV_FILE="$SCRIPT_DIR/.env.techops"
PROJECT_NAME="pulse-techops"
PURGE_DATA=false

usage() {
  printf 'Usage: %s [--env-file PATH] [--purge-data]\n' "${0##*/}" >&2
}

while (( $# )); do
  case "$1" in
    --env-file)
      [[ -n "${2:-}" ]] || { usage; exit 2; }
      ENV_FILE="$2"
      shift 2
      ;;
    --purge-data)
      PURGE_DATA=true
      shift
      ;;
    *)
      usage
      exit 2
      ;;
  esac
done
[[ -f "$ENV_FILE" ]] || { printf 'Missing environment file: %s\n' "$ENV_FILE" >&2; exit 2; }

compose=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f "$COMPOSE_FILE")
if [[ "$PURGE_DATA" == true ]]; then
  [[ "${PULSE_CONFIRM_PURGE:-}" == "DELETE_PULSE_DATA" ]] || {
    printf 'Refusing data purge. Set PULSE_CONFIRM_PURGE=DELETE_PULSE_DATA for this command only.\n' >&2
    exit 2
  }
  "${compose[@]}" down --remove-orphans --volumes
  printf 'Pulse services and the Pulse database volume were removed.\n'
else
  "${compose[@]}" down --remove-orphans
  printf 'Pulse services stopped. The pulse-techops-postgres volume was preserved.\n'
fi
