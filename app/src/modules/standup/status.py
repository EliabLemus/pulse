"""``/pulse status``: one owner-only look at the guided DSU pipelines.

Shows the comment-job queue by state, the guided delivery queue by state,
the oldest Compass snapshot age, and the last run of each host-invoked
worker. Guarded to ``OWNER_SLACK_USER_ID`` exactly like the owner
health-check, so queue contents are never exposed to the workspace.
"""

from __future__ import annotations

import logging
from typing import Any

import src.core.db as db
from src.modules.standup.owner_healthcheck import OWNER_SLACK_USER_ID

logger = logging.getLogger(__name__)

_COMMENT_STATES = ("pending", "processing", "unknown", "delivered")
_DELIVERY_STATES = ("pending", "processing", "unknown", "delivered")


def queue_state_counts() -> dict[str, dict[str, int]]:
    """Count comment jobs and guided deliveries per state, oldest info included."""
    with db.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT state, COUNT(*) FROM compass_comment_jobs GROUP BY state"
            )
            comments = {str(state): int(count) for state, count in cur.fetchall()}
            cur.execute(
                "SELECT state, COUNT(*) FROM guided_standup_deliveries GROUP BY state"
            )
            deliveries = {str(state): int(count) for state, count in cur.fetchall()}
    return {
        "compass_comment_jobs": {state: comments.get(state, 0) for state in _COMMENT_STATES},
        "guided_standup_deliveries": {state: deliveries.get(state, 0) for state in _DELIVERY_STATES},
    }


def snapshot_freshness_line() -> str:
    """The oldest snapshot age, or a plain line when there are none."""
    try:
        freshness: Any = db.compass_snapshot_freshness()
    except Exception as exc:
        logger.warning("Could not read snapshot freshness: %s", exc)
        return "snapshot age: unavailable"
    if not freshness.get("oldest"):
        return "snapshot age: no snapshots yet"
    stale = freshness.get("stale_teams") or []
    suffix = f" · stale teams: {', '.join(stale)}" if stale else ""
    return f"snapshot age (oldest): {freshness['oldest']}{suffix}"


def _last_queue_touch() -> str:
    """Most recent queue activity, as a proxy for the last comment worker run."""
    try:
        with db.db_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT GREATEST(
                        (SELECT MAX(delivered_at) FROM compass_comment_jobs),
                        (SELECT MAX(claimed_at) FROM compass_comment_jobs)
                    )
                    """
                )
                row = cur.fetchone()
        return f"comment worker last delivery/claim: {row[0]}" if row and row[0] else "comment worker: no runs recorded"
    except Exception as exc:
        logger.warning("Could not read last comment worker touch: %s", exc)
        return "comment worker last run: unavailable"


def status_text() -> str:
    """The full /pulse status message body."""
    try:
        counts = queue_state_counts()
        comment_line = ", ".join(
            f"{state}={count}" for state, count in counts["compass_comment_jobs"].items()
        )
        delivery_line = ", ".join(
            f"{state}={count}" for state, count in counts["guided_standup_deliveries"].items()
        )
    except Exception as exc:
        logger.warning("Could not read queue counts for /pulse status: %s", exc)
        comment_line = delivery_line = "unavailable"
    lines = [
        "*Compass DSU status*",
        f"comment jobs: {comment_line}",
        f"guided deliveries: {delivery_line}",
        snapshot_freshness_line(),
        _last_queue_touch(),
    ]
    return "\n".join(lines)


def is_status_allowed(user_id: str) -> bool:
    """Only the owner may read pipeline state."""
    return user_id == OWNER_SLACK_USER_ID


def register_status_command(app) -> None:  # noqa: ANN001
    """Wire /pulse status with the owner guard, following the health-check pattern."""

    @app.command("/pulse")
    def handle_pulse_command(ack, body, client):  # noqa: ANN001
        ack()
        user_id = body.get("user_id", "")
        text = (body.get("text") or "").strip()
        if text != "status":
            return
        if not is_status_allowed(user_id):
            client.chat_postEphemeral(
                channel=body.get("channel_id", ""), user=user_id, text="Solo el owner puede usar /pulse status."
            )
            return
        client.chat_postMessage(channel=user_id, text=status_text())
