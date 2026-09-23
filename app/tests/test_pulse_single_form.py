"""Single-form Pulse flow: DM context, modal shape, and Compass references."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from blocks import mrkdwn_to_rich_text, standup_dm_message, standup_form_modal, standup_resume_message  # noqa: E402

QUESTIONS = [
    "¿Qué lograste avanzar o completar ayer?",
    "¿Cuál es tu tarea principal para hoy?",
    "¿Tienes algún bloqueo que te impida avanzar hoy?",
]

TASKS = [
    {"key": "TOP-1", "title": "Improve deployment"},
    {"key": "TOP-2", "title": "Review incident"},
]


def test_pulse_dm_shows_only_the_recipient_compass_tasks_without_changing_form_entrypoint():
    message = standup_dm_message(
        QUESTIONS,
        "Compass DSU",
        compass_tasks=[
            {"key": "TOP-1", "title": "Improve deployment", "status": "active", "dueDate": "2026-09-15"},
            {"key": "TOP-2", "title": "Review incident", "status": "todo", "dueDate": "2026-09-18"},
        ],
    )

    context = next(block for block in message["blocks"] if block.get("block_id") == "compass_context")
    text = context["text"]["text"]
    assert "Compass · tareas con fecha esta semana" in text
    assert "TOP-1 — Improve deployment" in text
    assert "TOP-2 — Review incident" in text
    assert len(standup_form_modal(QUESTIONS, "Compass DSU")["blocks"]) == 3


def test_pulse_skip_confirm_mentions_the_recovery_path():
    message = standup_dm_message(QUESTIONS, "Compass DSU")
    skip = next(
        element
        for block in message["blocks"]
        if block["type"] == "actions"
        for element in block["elements"]
        if element["action_id"] == "skip_standup"
    )

    confirm_text = skip["confirm"]["text"]["text"]
    assert "Completar mi update" in confirm_text


def test_pulse_skip_confirmation_message_offers_the_resume_button():
    message = standup_resume_message()
    blocks = message["blocks"]

    buttons = [e for b in blocks if b["type"] == "actions" for e in b["elements"]]
    assert ("resume_standup", "Completar mi update") in [(e["action_id"], e["text"]["text"]) for e in buttons]
    assert any(e.get("style") == "primary" for e in buttons)


def test_pulse_form_has_exactly_the_three_dsu_questions():
    modal = standup_form_modal(QUESTIONS, "Compass DSU")

    assert modal["title"]["text"] == "Compass DSU"
    assert modal["submit"]["text"] == "Enviar update"
    assert [block["label"]["text"] for block in modal["blocks"]] == QUESTIONS
    assert len(modal["blocks"]) == 3


def test_compass_dsu_prompt_uses_the_compass_brand_without_pulse_copy():
    message = standup_dm_message(QUESTIONS, "Compass DSU")
    blocks = message["blocks"]

    assert blocks[0]["text"]["text"] == "🧭 Compass DSU"
    assert blocks[1]["text"]["text"] == "Comparte tu update."
    assert "Pulse" not in " ".join(
        block.get("text", {}).get("text", "") for block in blocks
    )


def test_pulse_form_without_tasks_has_no_template():
    modal = standup_form_modal(QUESTIONS, "Compass DSU", compass_tasks=[])

    assert len(modal["blocks"]) == 3
    assert all("initial_value" not in block["element"] for block in modal["blocks"])


def test_pulse_form_templates_the_three_questions_with_ticket_keys():
    modal = standup_form_modal(
        QUESTIONS,
        "Compass DSU",
        compass_tasks=[{"key": "TECH-12", "title": "Taxonomia"}, {"key": "TECH-1", "title": "SigNoz"}],
    )

    context = modal["blocks"][0]
    assert context["type"] == "section"
    assert context.get("block_id") == "compass_context"
    text = context["text"]["text"]
    assert "Tus tickets Compass esta semana" in text
    assert "<https://compass.zubale.com/tickets/TECH-12|TECH-12>" in text
    assert "<https://compass.zubale.com/tickets/TECH-1|TECH-1>" in text
    inputs = [block for block in modal["blocks"] if block["type"] == "input"]
    assert [block["label"]["text"] for block in inputs] == QUESTIONS
    template = mrkdwn_to_rich_text("TECH-12: \nTECH-1: ")
    assert [block["element"]["initial_value"] for block in inputs] == [template, template, template]
