"""Navigation affordances for the guided DSU modal (Back controls per step)."""

from __future__ import annotations

from src.modules.standup.blocks import guided_standup_modal

_TASKS = [
    {
        "key": "TECH-8",
        "title": "Despliegue Beta",
        "dueDate": "2026-10-05",
        "url": "https://compass.zubale.com/tickets/TECH-8",
    },
    {
        "key": "TECH-9",
        "title": "Migración a Cloud Run",
    },
]


def _action_ids(modal: dict) -> list[str]:
    return [
        element["action_id"]
        for block in modal["blocks"]
        for element in block.get("elements", [])
        if isinstance(element, dict) and "action_id" in element
    ]


def test_step_one_renders_a_per_ticket_no_progress_checkbox_without_repeating_the_title():
    answers = {"sin_avances": ["TECH-8"]}
    modal = guided_standup_modal("Mi DSU", _TASKS, step=0, answers=answers, today="2026-10-06")

    progress = next(block for block in modal["blocks"] if block.get("block_id") == "progress_TECH-8")
    no_progress = next(block for block in modal["blocks"] if block.get("block_id") == "sin_avances_TECH-8")

    assert progress["label"]["text"] == "Avance"
    assert no_progress["label"]["text"] == "¿Hubo avance hoy en TECH-8?"
    assert no_progress["element"]["type"] == "checkboxes"
    assert no_progress["element"]["options"][0]["text"]["text"] == "Sin avances hoy"
    assert no_progress["element"]["initial_options"][0]["value"] == "sin_avances"


def test_step_one_no_progress_checks_are_scoped_to_their_own_ticket():
    """Each checkbox must name its ticket so it cannot read as the next one's.

    Slack renders a label's input block with generous spacing above and below,
    so with two tickets the bare `¿Hubo avance hoy?` label floated directly
    under the previous ticket's Avance box and immediately above the NEXT
    ticket's title — its association was visually ambiguous.
    """
    answers = {"sin_avances": ["TECH-8"]}
    modal = guided_standup_modal("Mi DSU", _TASKS, step=0, answers=answers, today="2026-10-06")

    checks = {
        block["block_id"]: block
        for block in modal["blocks"]
        if str(block.get("block_id", "")).startswith("sin_avances_")
    }
    per_ticket = {c for c in checks if c != "sin_avances_resto"}
    assert per_ticket == {"sin_avances_TECH-8", "sin_avances_TECH-9"}
    assert "sin_avances_resto" in checks  # R4: global no-progress checkbox
    for key in ("TECH-8", "TECH-9"):
        assert checks[f"sin_avances_{key}"]["label"]["text"] == f"¿Hubo avance hoy en {key}?"
        # The visible option copy stays the approved vocabulary.
        assert checks[f"sin_avances_{key}"]["element"]["options"][0]["text"]["text"] == "Sin avances hoy"

    # The checked state still follows only its own ticket's saved answer.
    assert "initial_options" not in checks["sin_avances_TECH-9"]["element"]
    assert checks["sin_avances_TECH-8"]["element"]["initial_options"][0]["value"] == "sin_avances"

    # Per-ticket grouping order is stable: each check block follows its own
    # ticket's title and Avance input, before the next ticket's title.
    ids = [block.get("block_id") for block in modal["blocks"]]
    assert ids.index("ticket_TECH-8") < ids.index("progress_TECH-8") < ids.index("sin_avances_TECH-8")
    assert ids.index("sin_avances_TECH-8") < ids.index("ticket_TECH-9")
    assert ids.index("ticket_TECH-9") < ids.index("progress_TECH-9") < ids.index("sin_avances_TECH-9")


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
    assert modal["blocks"][-1]["block_id"] == "guided_nav"


def test_step_one_of_three_has_no_back_control():
    modal = guided_standup_modal("Mi DSU", _TASKS, step=0, answers={}, today="2026-10-06")

    assert "guided_back" not in _action_ids(modal)
    assert not any(block.get("block_id") == "guided_nav" for block in modal["blocks"])


def test_step_three_of_three_keeps_back_and_final_submit_text():
    modal = guided_standup_modal("Mi DSU", _TASKS, step=2, answers={}, today="2026-10-06")

    assert "guided_back" in _action_ids(modal)
    assert modal["blocks"][-1]["block_id"] == "guided_nav"
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
    assert "TECH-8 — Despliegue Beta" in text
    assert "<https://compass.zubale.com/tickets/TECH-8|TECH-8>" not in text
    assert "🔴 Vencido" in text
    # The wizard still ends through the modal's own submit, never a Next action.
    assert "guided_next" not in _action_ids(modal)


def test_legacy_standup_form_modal_has_no_guided_back():
    from src.modules.standup.blocks import standup_form_modal

    legacy = standup_form_modal(["Ayer", "Hoy", "Bloqueos"], "Team Standup")

    assert "guided_back" not in _action_ids(legacy)
    assert legacy["callback_id"] == "standup_form_modal"
