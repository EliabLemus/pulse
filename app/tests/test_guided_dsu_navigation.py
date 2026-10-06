"""Navigation affordances for the guided DSU modal (Back controls per step)."""

from __future__ import annotations

from src.modules.standup.blocks import guided_standup_modal

_TASKS = [
    {
        "key": "TECH-8",
        "title": "Despliegue Beta",
        "dueDate": "2026-10-05",
        "url": "https://compass.zubale.com/tickets/TECH-8",
    }
]


def _action_ids(modal: dict) -> list[str]:
    return [
        element["action_id"]
        for block in modal["blocks"]
        for element in block.get("elements", [])
        if isinstance(element, dict) and "action_id" in element
    ]


def test_step_two_of_three_has_back_button_with_stable_action_id():
    modal = guided_standup_modal("Mi DSU", _TASKS, step=1, answers={}, today="2026-10-06")

    back = next(
        (
            element
            for block in modal["blocks"]
            if block.get("type") == "actions"
            for element in block.get("elements", [])
            if isinstance(element, dict) and element.get("action_id") == "guided_back"
        ),
        None,
    )
    assert back is not None
    assert back["type"] == "button"
    assert back["text"]["type"] == "plain_text"


def test_step_one_of_three_has_no_back_control():
    modal = guided_standup_modal("Mi DSU", _TASKS, step=0, answers={}, today="2026-10-06")

    assert "guided_back" not in _action_ids(modal)
    assert not any(block.get("block_id") == "guided_nav" for block in modal["blocks"])


def test_step_three_of_three_keeps_back_and_final_submit_text():
    modal = guided_standup_modal("Mi DSU", _TASKS, step=2, answers={}, today="2026-10-06")

    assert "guided_back" in _action_ids(modal)
    assert modal["submit"]["text"] == "Enviar"


def test_back_control_does_not_replace_ticket_title_link_or_overdue_output():
    modal = guided_standup_modal("Mi DSU", _TASKS, step=1, answers={}, today="2026-10-06")

    text = "\n".join(
        [block.get("text", {}).get("text", "") for block in modal["blocks"]]
        + [
            element_text
            for block in modal["blocks"]
            for element in block.get("elements", [])
            if isinstance(element, dict)
            for element_text in ([element["text"]] if isinstance(element.get("text"), str) else [])
        ]
    )
    assert "<https://compass.zubale.com/tickets/TECH-8|TECH-8> — Despliegue Beta" in text
    assert "🔴 Vencido" in text
    # The wizard still ends through the modal's own submit, never a Next action.
    assert "guided_next" not in _action_ids(modal)


def test_legacy_standup_form_modal_has_no_guided_back():
    from src.modules.standup.blocks import standup_form_modal

    legacy = standup_form_modal(["Ayer", "Hoy", "Bloqueos"], "Team Standup")

    assert "guided_back" not in _action_ids(legacy)
    assert legacy["callback_id"] == "standup_form_modal"
