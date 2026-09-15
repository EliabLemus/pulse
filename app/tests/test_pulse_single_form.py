"""Regression tests for Pulse's one-form TechOps standup capture."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from blocks import standup_dm_message, standup_form_modal


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
    assert ("fill_in_form", "Completar update") in [
        (element["action_id"], element["text"]["text"]) for element in elements
    ]
    assert not any(block.get("block_id") == "first_question" for block in blocks)
    assert "formulario" in blocks[1]["text"]["text"].lower()


def test_pulse_form_has_exactly_the_three_dsu_questions():
    modal = standup_form_modal(QUESTIONS, "Pulse TechOps Pilot")

    assert modal["title"]["text"] == "Pulse — Update diario"
    assert modal["submit"]["text"] == "Enviar update"
    assert [block["label"]["text"] for block in modal["blocks"]] == QUESTIONS
    assert len(modal["blocks"]) == 3
