"""Tests for Compass read-only task context in Pulse DMs."""

from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from compass import CompassClient  # noqa: E402


def test_active_sprint_assignments_groups_only_matching_open_assignees():
    client = CompassClient("cmp_test")
    client._call_mcp = MagicMock(
        return_value={
            "content": [
                {
                    "type": "text",
                    "text": '{"active":true,"tasks":[{"key":"TOP-1","title":"Sprint task","statusCategory":"todo","assigneeEmail":"ALICE@zubale.com","dueDate":"2026-09-29"},{"key":"TOP-2","statusCategory":"done","assigneeEmail":"alice@zubale.com"},{"key":"TOP-3","statusCategory":"active","assigneeEmail":"bob@zubale.com"}]}',
                }
            ]
        }
    )

    assignments = client.active_sprint_assignments(
        ["alice@zubale.com", "carol@zubale.com"],
        team="techops",
    )

    assert [task["key"] for task in assignments["alice@zubale.com"]] == ["TOP-1"]
    assert assignments["carol@zubale.com"] == []
    client._call_mcp.assert_called_once_with("get_active_sprint", {"team": "techops"})


def test_active_sprint_assignments_returns_empty_context_when_no_sprint_is_active():
    client = CompassClient("cmp_test")
    client._call_mcp = MagicMock(return_value={"content": [{"type": "text", "text": '{"active":false}'}]})

    assert client.active_sprint_assignments(["alice@zubale.com"], team="techops") == {"alice@zubale.com": []}


def test_active_sprint_assignments_caps_each_member_at_five_tasks():
    client = CompassClient("cmp_test")
    tasks = [
        {"key": f"TOP-{number}", "statusCategory": "todo", "assigneeEmail": "alice@zubale.com"}
        for number in range(7, 0, -1)
    ]
    client._call_mcp = MagicMock(return_value={"content": [{"type": "text", "text": json.dumps({"active": True, "tasks": tasks})}]})

    assignments = client.active_sprint_assignments(["alice@zubale.com"], team="techops")

    assert [task["key"] for task in assignments["alice@zubale.com"]] == ["TOP-1", "TOP-2", "TOP-3", "TOP-4", "TOP-5"]


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
