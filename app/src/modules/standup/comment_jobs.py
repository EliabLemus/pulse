"""Durable, secret-free queue records for guided Compass DSU delivery."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

import src.core.db as db
import src.modules.standup.blockers as blockers

logger = logging.getLogger(__name__)


def save_guided_submission(
    *,
    team_id: str,
    user_id: str,
    schedule_id: int,
    standup_date: date,
    answers: list[str],
    channel_id: str,
    channel_text: str,
    channel_blocks: list[dict[str, Any]],
    comments: list[dict[str, str]],
) -> int:
    """Atomically save a guided DSU, its root delivery, and comment jobs.

    The app process only writes queue records. It never receives the Compass
    credential and therefore cannot post a ticket comment.
    """
    yesterday, today, blocker_text = (answers + ["", "", ""])[:3]
    has_blockers = blockers.reports_a_blocker(blocker_text)
    with db.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO standups
                    (team_id, user_id, yesterday, today, blockers, has_blockers, schedule_id, standup_date)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (team_id, user_id, yesterday, today, blocker_text, has_blockers, schedule_id, standup_date),
            )
            row = cur.fetchone()
            if not row:
                raise RuntimeError("Could not create guided standup")
            standup_id = int(row[0])
            cur.execute(
                """
                INSERT INTO guided_standup_deliveries
                    (standup_id, team_id, user_id, schedule_id, standup_date, channel_id, channel_text, channel_blocks)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    standup_id,
                    team_id,
                    user_id,
                    schedule_id,
                    standup_date,
                    channel_id,
                    channel_text,
                    db.psycopg2.extras.Json(channel_blocks),
                ),
            )
            for comment in comments:
                cur.execute(
                    """
                    INSERT INTO compass_comment_jobs (standup_id, team_id, user_id, ticket_key, body)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (standup_id, team_id, user_id, comment["ticket_key"], comment["body"]),
                )
    logger.info("Queued guided delivery for standup %s with %s comments", standup_id, len(comments))
    return standup_id


def claim_guided_delivery(standup_id: int) -> dict[str, Any] | None:
    """Claim a root post once; processing and unknown states are never replayed."""
    with db.db_conn() as conn:
        with conn.cursor(cursor_factory=db.psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE guided_standup_deliveries
                SET state = 'processing', claimed_at = NOW()
                WHERE standup_id = %s AND state = 'pending'
                RETURNING channel_id, channel_text, channel_blocks
                """,
                (standup_id,),
            )
            row = cur.fetchone()
    return dict(row) if row else None


def mark_guided_delivery_delivered(standup_id: int, message_ts: str | None) -> None:
    """Record the returned Slack timestamp after one root post succeeds."""
    with db.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE guided_standup_deliveries
                SET state = 'delivered', message_ts = %s, delivered_at = NOW()
                WHERE standup_id = %s AND state = 'processing'
                """,
                (message_ts, standup_id),
            )


def mark_guided_delivery_unknown(standup_id: int, detail: str) -> None:
    """Stop rather than risking a second root post after an uncertain outcome."""
    with db.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE guided_standup_deliveries
                SET state = 'unknown'
                WHERE standup_id = %s AND state = 'processing'
                """,
                (standup_id,),
            )
    logger.warning("Guided delivery %s requires reconciliation: %s", standup_id, detail[:500])


def mark_stale_guided_deliveries_unknown() -> int:
    """Surface a crashed root-post attempt without creating a second post."""
    with db.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE guided_standup_deliveries
                SET state = 'unknown'
                WHERE state = 'processing'
                  AND claimed_at < NOW() - INTERVAL '10 minutes'
                """
            )
            return cur.rowcount or 0


def mark_stale_processing_comments_unknown() -> int:
    """Surface a crashed worker's ambiguous jobs without attempting another post."""
    with db.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE compass_comment_jobs
                SET state = 'unknown', detail = 'worker claim expired before delivery was recorded'
                WHERE state = 'processing'
                  AND claimed_at < NOW() - INTERVAL '10 minutes'
                """
            )
            return cur.rowcount or 0


def claim_pending_comment_jobs(limit: int) -> list[dict[str, Any]]:
    """Claim pending jobs before an external call; claimed jobs are never retried."""
    bounded_limit = max(1, min(int(limit), 100))
    sql = """
        WITH selected AS (
            SELECT id
            FROM compass_comment_jobs
            WHERE state = 'pending'
            ORDER BY created_at, id
            FOR UPDATE SKIP LOCKED
            LIMIT %s
        )
        UPDATE compass_comment_jobs AS jobs
        SET state = 'processing', claimed_at = NOW()
        FROM selected
        WHERE jobs.id = selected.id
        RETURNING jobs.id, jobs.user_id, jobs.ticket_key, jobs.body
    """
    with db.db_conn() as conn:
        with conn.cursor(cursor_factory=db.psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (bounded_limit,))
            return [dict(row) for row in cur.fetchall()]


def mark_comment_delivered(job_id: int) -> None:
    """Close a job only after Compass acknowledged the write."""
    with db.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE compass_comment_jobs
                SET state = 'delivered', delivered_at = NOW(), detail = NULL
                WHERE id = %s AND state = 'processing'
                """,
                (job_id,),
            )


def mark_comment_retryable(job_id: int, detail: str) -> None:
    """Return a claimed job to pending after a proven pre-flight failure.

    Only called when the request provably never reached Compass, so a later
    claim cannot duplicate the comment. Ambiguous outcomes keep going to
    :func:`mark_comment_unknown` instead.
    """
    with db.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE compass_comment_jobs
                SET state = 'pending', claimed_at = NULL, detail = %s
                WHERE id = %s AND state = 'processing'
                """,
                (detail[:500], job_id),
            )
    logger.warning("Compass comment job %s returned to pending: %s", job_id, detail[:500])


def mark_comment_unknown(job_id: int, detail: str) -> None:
    """Preserve ambiguous external outcomes instead of risking a duplicate comment."""
    with db.db_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE compass_comment_jobs
                SET state = 'unknown', detail = %s
                WHERE id = %s AND state = 'processing'
                """,
                (detail[:500], job_id),
            )
