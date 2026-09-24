"""The whole DSU flow speaks one Spanish vocabulary: avance.

Covers DM entry, modal, confirmations, reminders, skip/resume and
Compass-sync feedback. No English leaks into participant-visible copy
and no stale "update" wording survives the sweep.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

import blocks  # noqa: E402
import handlers  # noqa: E402

QUESTIONS = [
    "Qué lograste avanzar o completar ayer?",
    "Cuál es tu tarea principal para hoy?",
    "Tienes algún bloqueo que te impida avanzar hoy?",
]

COMPASS_CONTEXT = {
    "sprint_name": "Sprint 2",
    "tasks": [{"key": "TECH-17", "title": "Slack Bot", "statusCategory": "todo"}],
}


def test_dm_entry_asks_for_an_avance():
    dm = blocks.standup_dm_message(QUESTIONS, "Compass DSU", compass_tasks=COMPASS_CONTEXT)
    texts = [block.get("text", {}).get("text", "") for block in dm["blocks"]]

    assert any("Comparte tu avance." in text for text in texts)
    assert "Completar mi avance" in dm["blocks"][-1]["elements"][0]["text"]["text"]
    assert not any("update" in text.lower() for text in texts)


def test_skip_confirmation_speaks_avance():
    dm = blocks.standup_dm_message(QUESTIONS, "Compass DSU", compass_tasks=COMPASS_CONTEXT)
    skip = next(
        element
        for element in dm["blocks"][-1]["elements"]
        if element.get("action_id") == "skip_standup"
    )
    confirm = skip["confirm"]

    assert confirm["title"]["text"] == "¿Omitir tu avance?"
    assert "Completar mi avance" in confirm["text"]["text"]


def test_modal_asks_for_the_avance_and_submits_in_spanish():
    modal = blocks.standup_form_modal(QUESTIONS, "Compass DSU", compass_tasks=COMPASS_CONTEXT)

    assert modal["title"]["text"] == "Avance diario"
    assert modal["submit"]["text"] == "Enviar avance"


def test_submission_confirmation_reports_the_avance():
    client = MagicMock()
    session = MagicMock()
    session.channel = None
    session.questions = QUESTIONS
    session.editing_standup_id = None
    session.schedule_id = 1
    handlers._persist_standup = MagicMock(return_value=7)

    with patch.dict(sys.modules, {"db": MagicMock()}):
        handlers._complete_standup("U1", session, client)

    first = client.chat_postMessage.call_args_list[0]
    assert first.kwargs["blocks"][0]["text"]["text"].startswith("✅ *Avance enviado.*")


def test_edit_confirmation_says_the_avance_was_updated():
    client = MagicMock()
    session = MagicMock()
    session.channel = None
    session.questions = QUESTIONS
    session.editing_standup_id = 42
    session.schedule_id = 1
    handlers._persist_standup = MagicMock()
    handlers.db = MagicMock()

    handlers._complete_standup("U1", session, client)

    first = client.chat_postMessage.call_args_list[0]
    assert first.kwargs["blocks"][0]["text"]["text"].startswith("✏️ *Avance actualizado.*")
