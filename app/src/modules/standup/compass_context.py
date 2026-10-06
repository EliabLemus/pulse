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
import re
from typing import Any

from src.modules.standup.compass import ticket_url

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

TaskList = list[dict[str, Any]]
CompassContext = dict[str, TaskList]


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
            context[user_id] = [_with_url(task) for task in tasks]
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


def _with_url(task: dict[str, Any]) -> dict[str, Any]:
    """Add the ticket URL only when the task has a key and no url yet."""
    key = task.get("key")
    if not isinstance(key, str) or not key.strip() or "url" in task:
        return task
    enriched = dict(task)
    enriched["url"] = ticket_url(key.strip())
    return enriched
