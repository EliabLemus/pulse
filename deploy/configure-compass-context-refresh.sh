#!/usr/bin/env bash
# Reconfigure the existing Hermes cron job 0afe4463e25d (Compass context
# refresh) to the staggered 10-minute schedule. Fails loudly when the job is
# absent; never creates a job.
set -euo pipefail

JOB_ID="0afe4463e25d"
SCHEDULE="04,14,24,34,44,54 * * * *"

if ! hermes cron list | grep -q "$JOB_ID"; then
  echo "ERROR: Hermes cron job $JOB_ID not found; refusing to edit or create anything." >&2
  exit 1
fi

hermes cron edit "$JOB_ID" --schedule "$SCHEDULE"
