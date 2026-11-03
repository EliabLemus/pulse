"""Tests for the Compass DSU MCP boundary and ticket-text validation."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from src.modules.standup.compass import CompassClient, is_substantive_ticket_text, portal_task_url


def test_get_ticket_reads_only_the_requested_ticket():
    client = CompassClient("cmp_test")
    client._call_mcp = MagicMock(
        return_value={
            "content": [
                {
                    "type": "text",
                    "text": json.dumps({"key": "TECH-8", "title": "Deploy", "statusCategory": "active"}),
                }
            ]
        }
    )

    assert client.get_ticket("TECH-8") == {"key": "TECH-8", "title": "Deploy", "statusCategory": "active"}
    client._call_mcp.assert_called_once_with("get_ticket", {"key": "TECH-8"})


def test_active_sprint_assignments_filters_done_and_other_assignees_case_insensitively():
    client = CompassClient("cmp_test")
    client._call_mcp = MagicMock(
        return_value={
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "active": True,
                            "sprint": {"name": "Sprint 2"},
                            "tasks": [
                                {
                                    "key": "TECH-8",
                                    "title": "Deploy",
                                    "statusCategory": "active",
                                    "assigneeEmail": "ELIAB.LEMUS@zubale.com",
                                },
                                {
                                    "key": "TECH-9",
                                    "title": "Done",
                                    "statusCategory": "done",
                                    "assigneeEmail": "eliab.lemus@zubale.com",
                                },
                                {
                                    "key": "TECH-10",
                                    "title": "Other",
                                    "statusCategory": "todo",
                                    "assigneeEmail": "other@zubale.com",
                                },
                            ],
                        }
                    ),
                }
            ]
        }
    )

    context = client.active_sprint_assignments(["eliab.lemus@zubale.com"], team="techops")

    assert context["sprint_name"] == "Sprint 2"
    assert [task["key"] for task in context["eliab.lemus@zubale.com"]] == ["TECH-8"]


def test_portal_task_url_accepts_only_exact_compass_task_routes():
    uuid = "1E2A76CD-29C7-4747-BEBC-3E6474956540"
    assert portal_task_url({"url": f"https://compass.zubale.com/portal/tasks/{uuid}"}) == (
        f"https://compass.zubale.com/portal/tasks/{uuid}"
    )
    assert portal_task_url({"url": f"https://compass.zubale.com/v2/portal/tasks/{uuid}"}) == (
        f"https://compass.zubale.com/v2/portal/tasks/{uuid}"
    )
    for invalid in (
        "https://compass.zubale.com/PORTAL/TASKS/1e2a76cd-29c7-4747-bebc-3e6474956540",
        "https://compass.zubale.com/tickets/TECH-99",
        "https://compass.zubale.com/portal/tasks/1e2a76cd-29c7-4747-bebc-3e6474956540/",
        "https://compass.zubale.com/portal/tasks/1e2a76cd-29c7-4747-bebc-3e6474956540?tab=comments",
        "https://compass.zubale.com.evil.io/portal/tasks/1e2a76cd-29c7-4747-bebc-3e6474956540",
        None,
        42,
    ):
        assert portal_task_url({"url": invalid}) == ""


def test_title_or_key_only_is_not_substantive_ticket_text():
    task = {"key": "TECH-8", "title": "Despliegue Beta en TechOps ZARM Space"}

    assert not is_substantive_ticket_text("TECH-8", task)
    assert not is_substantive_ticket_text("Despliegue Beta en TechOps ZARM Space", task)
    assert not is_substantive_ticket_text("TECH-8 — Despliegue Beta en TechOps ZARM Space", task)
    assert not is_substantive_ticket_text("— ✨", task)


def test_ticket_text_with_actual_content_is_substantive():
    task = {"key": "TECH-8", "title": "Despliegue Beta en TechOps ZARM Space"}

    assert is_substantive_ticket_text("TECH-8: terminé la validación del pipeline.", task)
    assert is_substantive_ticket_text("Listo para QA.", task)


def test_state_round_trip_preserves_compass_context_and_wizard_values():
    from src.core.state import UserSession, _deserialize, _serialize

    session = UserSession(
        cache_key="T1:U1",
        team_id="T1",
        channel="C1",
        compass_tasks=[{"key": "TECH-8", "title": "Deploy"}],
        wizard_step=2,
        wizard_answers={
            "progress": {"TECH-8": "Listo para QA."},
            "sin_avances": ["TECH-9"],
            "priority_key": "TECH-8",
        },
    )

    restored = _deserialize(_serialize(session))

    assert restored.compass_tasks == [{"key": "TECH-8", "title": "Deploy"}]
    assert restored.wizard_step == 2
    assert restored.wizard_answers["sin_avances"] == ["TECH-9"]
    assert restored.wizard_answers["priority_key"] == "TECH-8"


def test_state_reads_existing_session_without_compass_fields():
    from src.core.state import _deserialize

    restored = _deserialize({"cache_key": "T1:U1", "team_id": "T1", "channel": "C1"})

    assert restored.compass_tasks == []
    assert restored.wizard_step == 0
    assert restored.wizard_answers == {}


def test_guided_modal_renders_ticket_title_link_and_overdue_marker():
    from src.modules.standup.blocks import guided_standup_modal

    modal = guided_standup_modal(
        "Mi DSU",
        [
            {
                "key": "TECH-8",
                "title": "Despliegue Beta",
                "dueDate": "2026-10-05",
                "url": "https://compass.zubale.com/portal/tasks/1e2a76cd-29c7-4747-bebc-3e6474956540",
            }
        ],
        step=0,
        answers={},
        today="2026-10-06",
    )

    text = "\n".join(
        [block.get("text", {}).get("text", "") for block in modal["blocks"]]
        + [
            element.get("text", "")
            for block in modal["blocks"]
            for element in block.get("elements", [])
            if isinstance(element, dict)
        ]
    )
    assert modal["callback_id"] == "guided_standup_modal"
    assert "1/3" in text
    assert (
        "<https://compass.zubale.com/portal/tasks/1e2a76cd-29c7-4747-bebc-3e6474956540|TECH-8> — Despliegue Beta"
        in text
    )
    assert "🔴 Vencido" in text


def test_guided_focus_step_offers_required_primary_and_optional_secondary_controls():
    from src.modules.standup.blocks import guided_standup_modal

    modal = guided_standup_modal(
        "Mi DSU",
        [{"key": "TECH-8", "title": "Despliegue Beta", "dueDate": "2026-10-09"}],
        step=1,
        answers={},
        today="2026-10-06",
    )

    blocks = {block.get("block_id"): block for block in modal["blocks"]}
    primary_ticket = blocks["focus_primary_ticket"]
    secondary_ticket = blocks["focus_secondary_ticket"]
    secondary_goal = blocks["focus_secondary_goal"]

    assert [option["value"] for option in primary_ticket["element"]["options"]] == ["TECH-8", "other"]
    assert [option["value"] for option in secondary_ticket["element"]["options"]] == ["none", "TECH-8"]
    assert secondary_ticket["optional"] is True
    assert secondary_goal["optional"] is True
    assert any("Despliegue Beta" in str(block) for block in modal["blocks"])


def test_state_store_save_persists_guided_session(monkeypatch):
    from src.core import state as state_module

    persisted: dict[str, dict] = {}
    monkeypatch.setattr(state_module.session_store, "set_session", lambda key, value: persisted.__setitem__(key, value))
    monkeypatch.setattr(state_module.session_store, "get_session", lambda key: persisted.get(key))

    store = state_module.StateStore()
    session = state_module.UserSession(
        cache_key="T1:U1",
        team_id="T1",
        channel="C1",
        compass_tasks=[{"key": "TECH-8"}],
        wizard_step=1,
        wizard_answers={"progress": {"TECH-8": "Listo para QA."}},
    )
    store.save(session)

    restored = store.get("T1:U1")
    assert restored is not None
    assert restored.wizard_step == 1
    assert restored.wizard_answers["progress"]["TECH-8"] == "Listo para QA."


def test_state_store_start_accepts_compass_tasks(monkeypatch):
    from src.core import state as state_module

    persisted: dict[str, dict] = {}
    monkeypatch.setattr(state_module.session_store, "set_session", lambda key, value: persisted.__setitem__(key, value))
    store = state_module.StateStore()

    session = store.start(
        "T1:U1",
        "C1",
        team_id="T1",
        compass_tasks=[{"key": "TECH-8", "title": "Deploy"}],
    )

    assert session.compass_tasks == [{"key": "TECH-8", "title": "Deploy"}]
    assert persisted["T1:U1"]["compass_tasks"] == [{"key": "TECH-8", "title": "Deploy"}]


def test_portal_task_url_for_key_builds_link_for_well_formed_keys():
    from src.modules.standup.compass import portal_task_url_for_key

    assert portal_task_url_for_key("TECH-127") == "https://compass.zubale.com/portal/tasks/TECH-127"
    assert portal_task_url_for_key("  TECH-1  ") == ("https://compass.zubale.com/portal/tasks/TECH-1")


def test_portal_task_url_for_key_rejects_malformed_keys():
    from src.modules.standup.compass import portal_task_url_for_key

    for bad in ("", "TECH", "127", "TECH-", "TECH 127", "x <script>", "../../etc/passwd"):
        assert portal_task_url_for_key(bad) == ""
