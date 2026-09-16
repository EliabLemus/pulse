"""Regression tests for Pulse's one-form TechOps standup capture."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from blocks import standup_dm_message, standup_form_modal, standup_resume_message

QUESTIONS = [
    "¿Qué lograste avanzar o completar ayer?",
    "¿Cuál es tu tarea principal para hoy?",
    "¿Tienes algún bloqueo que te impida avanzar hoy?",
]


def test_pulse_dm_is_a_single_form_entrypoint_not_a_first_question():
    message = standup_dm_message(QUESTIONS, "Pulse TechOps Pilot")
    blocks = message["blocks"]

    action_blocks = [block for block in blocks if block["type"] == "actions"]
    elements = action_blocks[0]["elements"]
    assert ("fill_in_form", "Completar mi update") in [
        (element["action_id"], element["text"]["text"]) for element in elements
    ]
    assert not any(block.get("block_id") == "first_question" for block in blocks)
    assert "formulario" in blocks[1]["text"]["text"].lower()


def test_pulse_dm_shows_only_the_recipient_compass_tasks_without_changing_form_entrypoint():
    message = standup_dm_message(
        QUESTIONS,
        "Pulse TechOps Pilot",
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
    assert len(standup_form_modal(QUESTIONS, "Pulse TechOps Pilot")["blocks"]) == 3


def test_pulse_skip_confirm_mentions_the_recovery_path():
    message = standup_dm_message(QUESTIONS, "Pulse TechOps Pilot")
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
    modal = standup_form_modal(QUESTIONS, "Pulse TechOps Pilot")

    assert modal["title"]["text"] == "Pulse — Update diario"
    assert modal["submit"]["text"] == "Enviar update"
    assert [block["label"]["text"] for block in modal["blocks"]] == QUESTIONS
    assert len(modal["blocks"]) == 3


def test_pulse_form_keeps_compass_tasks_and_adds_optional_progress_inputs():
    modal = standup_form_modal(
        QUESTIONS,
        "Pulse TechOps Pilot",
        compass_tasks=[
            {"key": "TOP-1", "title": "Improve deployment"},
            {"key": "TOP-2", "title": "Review incident"},
        ],
    )

    compass_context = next(block for block in modal["blocks"] if block.get("block_id") == "compass_context")
    assert "Compass · tareas con fecha esta semana" in compass_context["text"]["text"]
    progress_blocks = [block for block in modal["blocks"] if block.get("block_id", "").startswith("compass_progress_")]
    assert [(block["label"]["text"], block["optional"]) for block in progress_blocks] == [
        ("TOP-1 — Improve deployment", True),
        ("TOP-2 — Review incident", True),
    ]
    assert [block["label"]["text"] for block in modal["blocks"][-3:]] == QUESTIONS
