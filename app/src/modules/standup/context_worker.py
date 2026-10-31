"""Refresh read-only Compass sprint-task snapshots for guided standup DMs."""

from __future__ import annotations

import logging
import os

import src.core.db as db
from src.modules.standup.compass import CompassClient
from src.modules.standup.compass_context import _normalize_email

logger = logging.getLogger(__name__)


def refresh_compass_task_snapshots(
    api_key: str,
    team_id: str,
    *,
    compass_team: str,
    client_factory=CompassClient,
) -> dict[str, int]:
    """Fetch one active-sprint view and atomically replace this team's snapshots."""
    if not api_key.startswith("cmp_"):
        raise ValueError("Compass API key is unavailable")

    emails = sorted(
        {email for member in db.get_active_members(team_id) if (email := _normalize_email(member.get("email")))}
    )
    assignments = client_factory(api_key).active_sprint_assignments(emails, team=compass_team)
    snapshots = {email: list(assignments.get(email) or []) for email in emails}
    db.replace_compass_task_snapshots(team_id, snapshots)
    return {"members": len(emails), "snapshots": len(snapshots)}


def main() -> int:
    api_key = os.environ.get("COMPASS_API_KEY", "")
    team_id = os.environ.get("PULSE_TEAM_ID", "")
    compass_team = os.environ.get("COMPASS_TEAM", "techops")
    if not team_id:
        raise ValueError("PULSE_TEAM_ID is unavailable")
    try:
        result = refresh_compass_task_snapshots(api_key, team_id, compass_team=compass_team)
    except Exception:
        logger.exception("Compass context refresh failed for %s", team_id)
        _alert_owner_of_failed_refresh(team_id)
        return 1
    print(f"members={result['members']} snapshots={result['snapshots']}")
    return 0


def _alert_owner_of_failed_refresh(team_id: str) -> None:
    """DM the owner that snapshots are stale; guided DMs degrade without dying."""
    try:
        from slack_sdk import WebClient  # noqa: PLC0415

        from src.core.scheduler import _fresh_bot_token  # noqa: PLC0415
        from src.modules.standup.owner_healthcheck import send_owner_text

        token = _fresh_bot_token(team_id, "")
        if not token:
            logger.warning("No bot token available for the context-refresh owner alert")
            return
        send_owner_text(
            WebClient(token=token),
            "⚠️ El refresh de snapshots Compass falló. El DSU guiado seguirá en modo simple sin contexto.",
        )
    except Exception as exc:
        logger.warning("Could not alert the owner about the failed context refresh: %s", exc)


if __name__ == "__main__":
    raise SystemExit(main())
