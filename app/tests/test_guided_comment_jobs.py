"""Atomic persistence for guided channel delivery and Compass comments."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock


def test_save_guided_submission_persists_standup_delivery_and_comments_together(monkeypatch):
    """A committed guided submission has its delivery and every ticket comment job."""
    from src.modules.standup import comment_jobs

    cursor = MagicMock()
    cursor.fetchone.return_value = (42,)
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def transaction():
        yield conn

    monkeypatch.setattr(comment_jobs.db, "db_conn", transaction)

    submission_id = comment_jobs.save_guided_submission(
        team_id="T1",
        user_id="U1",
        schedule_id=7,
        standup_date=date(2026, 10, 6),
        answers=["TECH-8: Validé el pipeline.", "Terminar despliegue", "Ninguno"],
        channel_id="C1",
        channel_text="*<@U1>*\n• <https://compass.zubale.com/tickets/TECH-8|TECH-8> — Validé el pipeline.",
        comments=[{"ticket_key": "TECH-8", "body": "Avance de Ana:\nValidé el pipeline."}],
    )

    assert submission_id == 42
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("INSERT INTO standups" in statement for statement in statements)
    assert any("INSERT INTO guided_standup_deliveries" in statement for statement in statements)
    assert any("INSERT INTO compass_comment_jobs" in statement for statement in statements)
    assert cursor.execute.call_count == 3


def test_guided_submission_detects_a_spanish_blocker(monkeypatch):
    """Guided persistence keeps the canonical blocker flag for downstream alerts."""
    from src.modules.standup import comment_jobs

    cursor = MagicMock()
    cursor.fetchone.return_value = (43,)
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def transaction():
        yield conn

    monkeypatch.setattr(comment_jobs.db, "db_conn", transaction)

    comment_jobs.save_guided_submission(
        team_id="T1",
        user_id="U1",
        schedule_id=7,
        standup_date=date(2026, 10, 6),
        answers=["TECH-8: Validé el pipeline.", "Terminar despliegue", "Necesito acceso a staging"],
        channel_id="C1",
        channel_text="*<@U1>*",
        comments=[],
    )

    assert cursor.execute.call_args_list[0].args[1][5] is True


def test_worker_posts_claimed_job_then_marks_it_delivered(monkeypatch):
    """A worker posts the queued body exactly once and closes its durable job."""
    from src.modules.standup import comment_worker

    claimed = [{"id": 9, "ticket_key": "TECH-8", "body": "Avance de Ana:\\nListo."}]
    post_comment = MagicMock()
    monkeypatch.setattr(comment_worker, "claim_pending_comment_jobs", lambda limit: claimed)
    monkeypatch.setattr(comment_worker, "mark_stale_processing_comments_unknown", lambda: 0)
    monkeypatch.setattr(comment_worker, "mark_stale_guided_deliveries_unknown", lambda: 0)
    monkeypatch.setattr(comment_worker, "mark_comment_delivered", MagicMock())
    monkeypatch.setattr(comment_worker, "mark_comment_unknown", MagicMock())
    monkeypatch.setattr(comment_worker, "CompassClient", lambda api_key: MagicMock(post_comment=post_comment))

    result = comment_worker.run_pending_comments("cmp_test", limit=5)

    assert result == {"delivered": 1, "unknown": 0}
    post_comment.assert_called_once_with("TECH-8", "Avance de Ana:\\nListo.")
    comment_worker.mark_comment_delivered.assert_called_once_with(9)
    comment_worker.mark_comment_unknown.assert_not_called()


def test_worker_marks_failed_write_unknown_without_retry(monkeypatch):
    """An uncertain Compass result is durable but never placed back in pending."""
    from src.modules.standup import comment_worker

    claimed = [{"id": 9, "ticket_key": "TECH-8", "body": "Avance de Ana:\\nListo."}]
    mark_unknown = MagicMock()
    failing_client = MagicMock()
    failing_client.post_comment.side_effect = TimeoutError("connection dropped")
    monkeypatch.setattr(comment_worker, "claim_pending_comment_jobs", lambda limit: claimed)
    monkeypatch.setattr(comment_worker, "mark_stale_processing_comments_unknown", lambda: 0)
    monkeypatch.setattr(comment_worker, "mark_stale_guided_deliveries_unknown", lambda: 0)
    monkeypatch.setattr(comment_worker, "mark_comment_delivered", MagicMock())
    monkeypatch.setattr(comment_worker, "mark_comment_unknown", mark_unknown)
    monkeypatch.setattr(comment_worker, "CompassClient", lambda api_key: failing_client)

    result = comment_worker.run_pending_comments("cmp_test", limit=5)

    assert result == {"delivered": 0, "unknown": 1}
    mark_unknown.assert_called_once()
    assert mark_unknown.call_args.args[0] == 9
    assert "connection dropped" in mark_unknown.call_args.args[1]


def test_worker_marks_stale_processing_jobs_unknown_for_alerting(monkeypatch):
    """A worker crash after claiming cannot silently strand a comment forever."""
    from src.modules.standup import comment_worker

    monkeypatch.setattr(comment_worker, "mark_stale_processing_comments_unknown", lambda: 0)
    monkeypatch.setattr(comment_worker, "mark_stale_guided_deliveries_unknown", lambda: 1)
    monkeypatch.setattr(comment_worker, "claim_pending_comment_jobs", lambda limit: [])
    monkeypatch.setattr(comment_worker, "CompassClient", MagicMock())

    result = comment_worker.run_pending_comments("cmp_test", limit=5)

    assert result == {"delivered": 0, "unknown": 1}


def test_compass_client_post_comment_uses_only_key_and_body():
    """The only Compass mutation is the narrow post_comment MCP call."""
    from src.modules.standup.compass import CompassClient

    client = CompassClient("cmp_test")
    client._call_mcp = MagicMock(return_value={})

    client.post_comment(" TECH-8 ", " Avance de Ana:\\nListo. ")

    client._call_mcp.assert_called_once_with("post_comment", {"key": "TECH-8", "body": "Avance de Ana:\\nListo."})
