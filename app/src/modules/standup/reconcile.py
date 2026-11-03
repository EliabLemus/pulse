"""Reconciliation report for the guided DSU delivery and comment queues.

Lists every ``guided_standup_deliveries`` row and every
``compass_comment_jobs`` row that is not yet delivered, with its state,
detail and timestamps, and alerts the owner by Slack DM when ``unknown``
rows persist across consecutive runs (default 2). Exit code is 0 when
nothing needs attention, 1 when the owner was alerted.

State meanings:

- ``pending``      queued, waiting for a worker claim.
- ``processing``   claimed recently; becomes ``unknown`` after 10 idle minutes.
- ``unknown``      the outcome cannot be proven (post-send failure or a
                   crashed claim). Never retried automatically: check Compass
                   and Slack by hand, then resolve the row (see RUNBOOK).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from typing import Any

import src.core.db as db

logger = logging.getLogger(__name__)

# The owner is alerted only when unknown rows appear in this many consecutive
# runs, so a single transient ambiguity does not page anyone.
UNKNOWN_ALERT_RUNS = 2
_STATE_FILE = os.environ.get(
    "PULSE_RECONCILE_STATE_FILE",
    os.path.join(os.path.expanduser("~"), ".local", "state", "morgenruf", "reconcile_state.json"),
)


def collect_open_queue_rows(*, limit: int = 100) -> dict[str, list[dict[str, Any]]]:
    """Every undelivered delivery and comment job, oldest first, with detail."""
    with db.db_conn() as conn:
        with conn.cursor(cursor_factory=db.psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT standup_id, team_id, user_id, schedule_id, standup_date,
                       state, message_ts, detail, created_at, claimed_at, delivered_at
                FROM guided_standup_deliveries
                WHERE state <> 'delivered'
                ORDER BY created_at, standup_id
                LIMIT %s
                """,
                (limit,),
            )
            deliveries = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT id, standup_id, team_id, user_id, ticket_key, state,
                       detail, created_at, claimed_at, delivered_at
                FROM compass_comment_jobs
                WHERE state <> 'delivered' AND state <> 'skipped'
                ORDER BY created_at, id
                LIMIT %s
                """,
                (limit,),
            )
            comments = [dict(row) for row in cur.fetchall()]
    return {"guided_standup_deliveries": deliveries, "compass_comment_jobs": comments}


def unknown_consecutive_runs(report: dict[str, list[dict[str, Any]]]) -> int:
    """Track how many consecutive runs saw unknown rows; 0 resets the streak."""
    unknown = sum(1 for rows in report.values() for row in rows if row.get("state") == "unknown")
    streak = _load_streak()
    streak = streak + 1 if unknown else 0
    _save_streak(streak)
    return streak


def _load_streak() -> int:
    try:
        with open(_STATE_FILE) as fh:
            value = json.load(fh).get("unknown_streak", 0)
        return int(value) if isinstance(value, int) else 0
    except (OSError, ValueError):
        return 0


def _save_streak(streak: int) -> None:
    try:
        os.makedirs(os.path.dirname(_STATE_FILE), exist_ok=True)
        with open(_STATE_FILE, "w") as fh:
            json.dump({"unknown_streak": streak}, fh)
    except OSError as exc:
        logger.warning("Could not persist reconcile streak to %s: %s", _STATE_FILE, exc)


def format_report(report: dict[str, list[dict[str, Any]]]) -> str:
    lines = []
    for table, rows in report.items():
        lines.append(f"== {table} ({len(rows)} open) ==")
        for row in rows:
            created = _fmt_ts(row.get("created_at"))
            claimed = _fmt_ts(row.get("claimed_at")) or "-"
            delivered = _fmt_ts(row.get("delivered_at")) or "-"
            identity = row.get("standup_id", row.get("id"))
            detail = str(row.get("detail") or "")
            subject = row.get("ticket_key") or row.get("user_id") or ""
            lines.append(
                f"  #{identity} [{row.get('state')}] {subject} created={created} "
                f"claimed={claimed} delivered={delivered}" + (f" detail={detail}" if detail else "")
            )
    return "\n".join(lines) if lines else "All queues clear."


def _fmt_ts(value: object) -> str:
    return str(value) if value else ""


def alert_owner_if_persistent_unknown(report: dict[str, list[dict[str, Any]]]) -> bool:
    """DM the owner when unknown rows persisted for UNKNOWN_ALERT_RUNS runs."""
    unknown_rows = [row for rows in report.values() for row in rows if row.get("state") == "unknown"]
    if not unknown_rows:
        return False
    summary = "\n".join(
        f"• {row.get('ticket_key') or row.get('user_id') or row.get('standup_id')}: {str(row.get('detail') or '')[:120]}"
        for row in unknown_rows[:10]
    )
    team_id = str(unknown_rows[0].get("team_id") or "")
    try:
        from slack_sdk import WebClient  # noqa: PLC0415

        from src.core.scheduler import _fresh_bot_token  # noqa: PLC0415
        from src.modules.standup.owner_healthcheck import send_owner_text

        token = _fresh_bot_token(team_id, "")
        if not token:
            logger.warning("No bot token available for the reconcile owner alert")
            return False
        return send_owner_text(
            WebClient(token=token),
            f"🚨 {len(unknown_rows)} entrega(s)/comentario(s) de DSU en estado *unknown* "
            f"por {UNKNOWN_ALERT_RUNS} corridas seguidas. Revisa RUNBOOK → 'Reconciliación'.\n{summary}",
        )
    except Exception as exc:
        logger.warning("Could not alert the owner about persistent unknown rows: %s", exc)
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Report open guided DSU delivery and comment queue rows")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--team-id", default=os.environ.get("PULSE_TEAM_ID", ""), help="Team for the owner alert DM")
    args = parser.parse_args(argv)

    report = collect_open_queue_rows(limit=args.limit)
    print(format_report(report))
    streak = unknown_consecutive_runs(report)
    if streak >= UNKNOWN_ALERT_RUNS:
        alerted = alert_owner_if_persistent_unknown(report)
        print(f"unknown streak={streak}; owner alerted={alerted}", file=sys.stderr)
        return 1
    if streak:
        print(f"unknown streak={streak}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
