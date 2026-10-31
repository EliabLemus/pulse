"""Pure adapter from Compass sprint assignments to a Slack user_id task map.

The guided DSU flow asks Compass for one member's open sprint tasks before
composing the standup DM. This module is deliberately side-effect free: it
performs exactly one read-only ``active_sprint_assignments`` call for the
unique normalized member emails and reshapes the result into
``{slack_user_id: [task, ...]}`` for the caller. Any Compass failure fails
open to an empty mapping so scheduled DM delivery is never aborted.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

TaskList = list[dict[str, Any]]
CompassContext = dict[str, TaskList]
# How old a snapshot may be before the guided DSU drops the ticket context.
SNAPSHOT_MAX_AGE_MINUTES = max(1, int(os.environ.get("SNAPSHOT_MAX_AGE_MINUTES", "30")))


class SnapshotCompassClient:
    """Read Compass task context from Postgres, never from a credential or MCP."""

    def __init__(self, team_id: str) -> None:
        self._team_id = team_id

    def active_sprint_assignments(
        self,
        emails: list[str],
        *,
        team: str,
        max_tasks_per_email: int = 5,
    ) -> dict[str, TaskList]:
        import src.core.db as db  # noqa: PLC0415

        return db.get_fresh_compass_task_snapshots(
            self._team_id,
            emails,
            max_age_minutes=SNAPSHOT_MAX_AGE_MINUTES,
            max_tasks_per_email=max_tasks_per_email,
        )


def compass_context_for_members(
    client: Any,
    slack_members: list[dict[str, Any]],
    *,
    team: str,
) -> CompassContext:
    """Map Slack user_id -> open Compass sprint tasks for each member.

    ``client`` only needs the read-only ``active_sprint_assignments`` method
    (any CompassClient-compatible object). ``slack_members`` entries carry at
    least ``user_id`` and ``email``; members without a usable email are
    skipped. Raises from the client are swallowed and logged: the caller gets
    ``{}`` instead of a failed DM delivery.
    """
    email_to_user_ids: dict[str, list[str]] = {}
    for member in slack_members:
        user_id = str(member.get("user_id") or "").strip()
        email = _normalize_email(member.get("email"))
        if not user_id or not email:
            continue
        email_to_user_ids.setdefault(email, []).append(user_id)

    if not email_to_user_ids:
        return {}

    try:
        assignments = client.active_sprint_assignments(sorted(email_to_user_ids), team=team)
    except Exception:  # noqa: BLE001 - fail open; DSU delivery must not abort
        logger.exception("compass context unavailable; continuing without ticket context")
        return {}

    context: CompassContext = {}
    for email, user_ids in email_to_user_ids.items():
        tasks = _task_list(assignments.get(email) if isinstance(assignments, dict) else None)
        for user_id in user_ids:
            context[user_id] = list(tasks)
    return context


def _normalize_email(value: object) -> str:
    """Return a lowercased, trimmed email or '' when malformed/absent."""
    if not isinstance(value, str):
        return ""
    email = value.strip().lower()
    return email if _EMAIL_RE.fullmatch(email) else ""


def _task_list(value: object) -> TaskList:
    if not isinstance(value, list):
        return []
    return [task for task in value if isinstance(task, dict)]
