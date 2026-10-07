"""Tests for the pure Compass-to-Slack context adapter."""

from __future__ import annotations

from typing import Any

from src.modules.standup.compass_context import compass_context_for_members


class SpyCompassClient:
    """Read-only Compass stand-in that records every method call."""

    def __init__(self, assignments: dict[str, Any] | Exception | None = None) -> None:
        self._assignments = assignments
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def active_sprint_assignments(
        self,
        emails: list[str],
        *,
        team: str,
        max_tasks_per_email: int = 5,
    ) -> dict[str, Any]:
        self.calls.append(
            (
                "active_sprint_assignments",
                {"emails": list(emails), "team": team, "max_tasks_per_email": max_tasks_per_email},
            )
        )
        if isinstance(self._assignments, Exception):
            raise self._assignments
        assert self._assignments is not None
        return self._assignments

    def get_ticket(self, key: str) -> dict[str, Any]:
        raise AssertionError("compass_context must never call get_ticket")


def members(*entries: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(entry) for entry in entries]


def test_single_batch_read_for_unique_normalized_emails():
    client = SpyCompassClient({"eliab.lemus@zubale.com": [{"key": "TECH-8"}]})
    roster = members(
        {"user_id": "U1", "email": "ELIAB.LEMUS@zubale.com"},
        {"user_id": "U2", "email": "  eliab.lemus@zubale.com  "},
        {"user_id": "U3", "email": "other@zubale.com"},
    )

    context = compass_context_for_members(client, roster, team="techops")

    assert len(client.calls) == 1
    name, kwargs = client.calls[0]
    assert name == "active_sprint_assignments"
    assert set(kwargs["emails"]) == {"eliab.lemus@zubale.com", "other@zubale.com"}
    assert len(kwargs["emails"]) == 2
    assert kwargs["team"] == "techops"
    assert [task["key"] for task in context["U1"]] == ["TECH-8"]
    assert [task["key"] for task in context["U2"]] == ["TECH-8"]


def test_blank_or_malformed_emails_are_never_queried_or_mapped():
    client = SpyCompassClient({"ok@zubale.com": []})
    roster = members(
        {"user_id": "U1", "email": "ok@zubale.com"},
        {"user_id": "UBLANK", "email": "   "},
        {"user_id": "UEMPTY", "email": ""},
        {"user_id": "UNONE", "email": None},
        {"user_id": "UMISSING"},
        {"user_id": "UMALFORMED", "email": "not-an-email"},
        {"user_id": "USPACEY", "email": "a b@zubale.com"},
        {"user_id": "UNOLOCAL", "email": "@zubale.com"},
        {"user_id": "UNODOMAIN", "email": "eliab@"},
        {"user_id": "UNUMERIC", "email": 42},
    )

    context = compass_context_for_members(client, roster, team="techops")

    assert [kwargs["emails"] for _, kwargs in client.calls] == [["ok@zubale.com"]]
    assert set(context) == {"U1"}
    assert context["U1"] == []


def test_no_valid_emails_skips_client_entirely():
    client = SpyCompassClient({})
    roster = members({"user_id": "U1", "email": "   "}, {"user_id": "U2"})

    context = compass_context_for_members(client, roster, team="techops")

    assert client.calls == []
    assert context == {}


def test_no_cross_user_task_leakage():
    client = SpyCompassClient(
        {
            "a@zubale.com": [{"key": "TECH-1", "title": "A1"}, {"key": "TECH-2", "title": "A2"}],
            "b@zubale.com": [{"key": "TECH-3", "title": "B1"}],
            "stranger@zubale.com": [{"key": "TECH-4", "title": "S1"}],
            "sprint_name": "Sprint 2",
        }
    )
    roster = members({"user_id": "UA", "email": "a@zubale.com"}, {"user_id": "UB", "email": "b@zubale.com"})

    context = compass_context_for_members(client, roster, team="techops")

    assert [task["key"] for task in context["UA"]] == ["TECH-1", "TECH-2"]
    assert [task["key"] for task in context["UB"]] == ["TECH-3"]
    leaked = {task["key"] for tasks in context.values() for task in tasks}
    assert "TECH-4" not in leaked


def test_taskless_member_gets_empty_list_not_absence():
    client = SpyCompassClient({"a@zubale.com": [{"key": "TECH-1"}]})
    roster = members({"user_id": "UA", "email": "a@zubale.com"}, {"user_id": "UZ", "email": "z@zubale.com"})

    context = compass_context_for_members(client, roster, team="techops")

    assert context["UZ"] == []


def test_client_failure_fails_open_to_empty_mapping():
    client = SpyCompassClient(RuntimeError("compass down"))
    roster = members({"user_id": "U1", "email": "a@zubale.com"})

    context = compass_context_for_members(client, roster, team="techops")

    assert context == {}
    assert len(client.calls) == 1


def test_never_calls_write_tools_or_get_ticket():
    client = SpyCompassClient({"a@zubale.com": [{"key": "TECH-1"}]})
    roster = members({"user_id": "U1", "email": "a@zubale.com"})

    compass_context_for_members(client, roster, team="techops")

    assert [name for name, _ in client.calls] == ["active_sprint_assignments"]


def test_tasks_preserve_mcp_urls_without_inventing_a_ticket_key_route():
    received = [
        {"key": "TECH-8", "title": "Deploy", "statusCategory": "active"},
        {
            "key": "TECH-9",
            "title": "Has portal link",
            "url": "https://compass.zubale.com/portal/tasks/12345678-1234-1234-1234-123456789abc",
        },
        {"title": "No key task"},
    ]
    client = SpyCompassClient({"a@zubale.com": received})
    roster = members({"user_id": "U1", "email": "a@zubale.com"})

    context = compass_context_for_members(client, roster, team="techops")

    tasks = context["U1"]
    assert tasks[0] == {"key": "TECH-8", "title": "Deploy", "statusCategory": "active"}
    assert tasks[1] == received[1]
    assert tasks[2] == {"title": "No key task"}
    # The client-owned task dicts are never mutated in place.
    assert "url" not in received[0]
    # Untouched tasks are passed through as the very objects received.
    assert tasks[0] is received[0]
    assert tasks[1] is received[1]
    assert tasks[2] is received[2]


def test_result_mapping_is_independent_of_client_dict():
    source = {"a@zubale.com": [{"key": "TECH-1"}]}
    client = SpyCompassClient(source)
    roster = members({"user_id": "U1", "email": "a@zubale.com"})

    context = compass_context_for_members(client, roster, team="techops")
    source["a@zubale.com"].append({"key": "TECH-2"})

    assert [task["key"] for task in context["U1"]] == ["TECH-1"]


def test_empty_member_list_returns_empty_mapping_without_call():
    client = SpyCompassClient({})

    context = compass_context_for_members(client, [], team="techops")

    assert context == {}
    assert client.calls == []
