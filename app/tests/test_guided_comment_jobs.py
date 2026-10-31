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
        channel_text="*<@U1>*\n• TECH-8 — Validé el pipeline.",
        channel_blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "*Avances*"}}],
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
        channel_blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": "*Avances*"}}],
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

    assert result == {"delivered": 1, "unknown": 0, "impersonated": 0}
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

    assert result == {"delivered": 0, "unknown": 1, "impersonated": 0}
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

    assert result == {"delivered": 0, "unknown": 1, "impersonated": 0}


def test_worker_impersonates_user_with_own_key(monkeypatch):
    """A job whose user has a stored key is posted through that user's client."""
    from src.modules.standup import comment_worker

    claimed = [{"id": 9, "user_id": "U7", "ticket_key": "TECH-8", "body": "Listo."}]
    user_client = MagicMock()
    monkeypatch.setattr(comment_worker, "claim_pending_comment_jobs", lambda limit: claimed)
    monkeypatch.setattr(comment_worker, "mark_stale_processing_comments_unknown", lambda: 0)
    monkeypatch.setattr(comment_worker, "mark_stale_guided_deliveries_unknown", lambda: 0)
    monkeypatch.setattr(comment_worker, "mark_comment_delivered", MagicMock())
    monkeypatch.setattr(comment_worker, "mark_comment_unknown", MagicMock())
    monkeypatch.setattr(comment_worker, "CompassClient", lambda api_key: MagicMock() if api_key == "cmp_global" else user_client)

    import src.modules.standup.user_keys as user_keys

    monkeypatch.setattr(user_keys, "active_key_for_user", lambda user: "cmp_user7" if user == "U7" else None)

    result = comment_worker.run_pending_comments("cmp_global", limit=5)

    assert result == {"delivered": 1, "unknown": 0, "impersonated": 1}
    user_client.post_comment.assert_called_once_with("TECH-8", "Listo.")


def test_worker_falls_back_to_global_key_when_user_has_none(monkeypatch):
    """Without a stored user key the global client posts; nobody is blocked."""
    from src.modules.standup import comment_worker

    claimed = [{"id": 9, "user_id": "U7", "ticket_key": "TECH-8", "body": "Listo."}]
    global_client = MagicMock()
    monkeypatch.setattr(comment_worker, "claim_pending_comment_jobs", lambda limit: claimed)
    monkeypatch.setattr(comment_worker, "mark_stale_processing_comments_unknown", lambda: 0)
    monkeypatch.setattr(comment_worker, "mark_stale_guided_deliveries_unknown", lambda: 0)
    monkeypatch.setattr(comment_worker, "mark_comment_delivered", MagicMock())
    monkeypatch.setattr(comment_worker, "mark_comment_unknown", MagicMock())
    clients = {"cmp_global": global_client}
    monkeypatch.setattr(comment_worker, "CompassClient", lambda api_key: clients[api_key])

    import src.modules.standup.user_keys as user_keys

    monkeypatch.setattr(user_keys, "active_key_for_user", lambda user: None)

    result = comment_worker.run_pending_comments("cmp_global", limit=5)

    assert result == {"delivered": 1, "unknown": 0, "impersonated": 0}
    global_client.post_comment.assert_called_once_with("TECH-8", "Listo.")


def test_worker_marks_failed_user_key_post_unknown_without_retry(monkeypatch):
    """A user-key 4xx is an ambiguous durable outcome, never retried."""
    from src.modules.standup import comment_worker

    claimed = [{"id": 9, "user_id": "U7", "ticket_key": "TECH-8", "body": "Listo."}]
    mark_unknown = MagicMock()
    user_client = MagicMock()
    user_client.post_comment.side_effect = ValueError("Compass rejected the MCP tool call")
    monkeypatch.setattr(comment_worker, "claim_pending_comment_jobs", lambda limit: claimed)
    monkeypatch.setattr(comment_worker, "mark_stale_processing_comments_unknown", lambda: 0)
    monkeypatch.setattr(comment_worker, "mark_stale_guided_deliveries_unknown", lambda: 0)
    monkeypatch.setattr(comment_worker, "mark_comment_delivered", MagicMock())
    monkeypatch.setattr(comment_worker, "mark_comment_unknown", mark_unknown)
    monkeypatch.setattr(comment_worker, "CompassClient", lambda api_key: MagicMock() if api_key == "cmp_global" else user_client)

    import src.modules.standup.user_keys as user_keys

    monkeypatch.setattr(user_keys, "active_key_for_user", lambda user: "cmp_user7")

    result = comment_worker.run_pending_comments("cmp_global", limit=5)

    assert result == {"delivered": 0, "unknown": 1, "impersonated": 0}
    mark_unknown.assert_called_once()


def test_compass_client_post_comment_uses_only_key_and_body():
    """The only Compass mutation is the narrow post_comment MCP call."""
    from src.modules.standup.compass import CompassClient

    client = CompassClient("cmp_test")
    client._call_mcp = MagicMock(return_value={})

    client.post_comment(" TECH-8 ", " Avance de Ana:\\nListo. ")

    client._call_mcp.assert_called_once_with("post_comment", {"key": "TECH-8", "body": "Avance de Ana:\\nListo."})


def test_compass_client_mock_mode_never_calls_compass(monkeypatch):
    """The release rehearsal switch is opt-in and has zero remote write effect."""
    from src.modules.standup.compass import CompassClient

    monkeypatch.setenv("PULSE_COMPASS_WRITE_MODE", "mock")
    client = CompassClient("cmp_test")
    client._call_mcp = MagicMock()

    client.post_comment(" TECH-8 ", " Avance de Ana: Listo. ")

    client._call_mcp.assert_not_called()
