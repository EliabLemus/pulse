"""Tests for Compass read-only task context in Pulse DMs."""

from __future__ import annotations

import os
import sys
from datetime import date
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from compass import CompassClient  # noqa: E402


def test_weekly_assignments_groups_only_matching_assignees_within_monday_to_friday():
    client = CompassClient("cmp_test")
    client._request_json = MagicMock(
        side_effect=[
            {"tickets": [{"key": "TOP-1"}, {"key": "TOP-2"}]},  # todo
            {"tickets": [{"key": "TOP-3"}]},  # active
            {"tickets": []},  # blocked
            {
                "key": "TOP-1",
                "title": "Monday task",
                "status": "todo",
                "assignee": "ALICE@zubale.com",
                "dueDate": "2026-09-14",
            },
            {
                "key": "TOP-2",
                "title": "Other person's task",
                "status": "todo",
                "assignee": "bob@zubale.com",
                "dueDate": "2026-09-16",
            },
            {
                "key": "TOP-3",
                "title": "Friday task",
                "status": "active",
                "assignee": {"email": "alice@zubale.com"},
                "dueDate": "2026-09-18",
            },
        ]
    )

    assignments = client.weekly_assignments(
        ["alice@zubale.com", "carol@zubale.com"],
        team="techops",
        local_day=date(2026, 9, 15),
    )

    assert [task["key"] for task in assignments["alice@zubale.com"]] == ["TOP-1", "TOP-3"]
    assert assignments["carol@zubale.com"] == []
    assert client._request_json.call_count == 6


def test_post_comment_mock_mode_logs_without_touching_the_network(monkeypatch, caplog):
    client = CompassClient("cmp_test")
    client._call_mcp = MagicMock(side_effect=AssertionError("mock mode must not call Compass"))
    monkeypatch.setenv("PULSE_COMPASS_WRITE_MODE", "mock")

    with caplog.at_level("WARNING"):
        result = client.post_comment("TOP-9", "Actualización de Pulse:\nprueba simulada")

    assert result == {"mock": True}
    assert "PULSE_COMPASS_MOCK_COMMENT" in caplog.text
    assert "TOP-9" in caplog.text
    client._call_mcp.assert_not_called()


def test_post_comment_uses_only_the_task_key_and_progress_body():
    client = CompassClient("cmp_test")
    client._call_mcp = MagicMock(return_value={"ok": True})

    client.post_comment("TOP-1", "Actualización de Pulse:\nDesplegué Redis y validé la sesión.")

    client._call_mcp.assert_called_once_with(
        "post_comment",
        {"key": "TOP-1", "body": "Actualización de Pulse:\nDesplegué Redis y validé la sesión."},
    )
