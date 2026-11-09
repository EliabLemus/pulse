"""Guided edit mode: reopen the per-ticket wizard within the edit window."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from src.core.state import UserSession
from src.modules.standup import comment_jobs, handlers
from src.modules.standup.guided_edit import (
    changed_guided_comments,
    parse_focus_lines,
    parse_progress_lines,
    rebuild_guided_edit,
)

TASKS = [
    {"key": "TECH-8", "title": "Despliegue Beta"},
    {"key": "TECH-9", "title": "Observabilidad"},
]


class AckRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> None:
        self.calls.append(kwargs)


class FakeApp:
    def __init__(self) -> None:
        self.handlers: dict[tuple, object] = {}

    def __getattr__(self, name: str):  # noqa: ANN001
        def factory(*args, **kwargs):  # noqa: ANN002, ANN003
            def deco(fn):
                self.handlers[(name, args[0] if args else None)] = fn
                return fn

            return deco

        return factory


def _registered() -> dict:
    import src.modules.standup.quickstart as quickstart

    with patch.object(quickstart, "register", lambda *a, **k: None):
        app = FakeApp()
        handlers.register_handlers(app)
    return app.handlers


class MemoryStateStore:
    def __init__(self) -> None:
        self._sessions: dict[str, UserSession] = {}

    def get(self, cache_key: str) -> UserSession | None:
        return self._sessions.get(cache_key)

    def start(self, cache_key, channel, **kwargs):  # noqa: ANN001, ANN003, ANN201
        session = UserSession(cache_key=cache_key, channel=channel, **kwargs)
        self._sessions[cache_key] = session
        return session

    def save(self, session: UserSession) -> UserSession:
        self._sessions[session.cache_key] = session
        return session

    def clear(self, cache_key: str) -> None:
        self._sessions.pop(cache_key, None)

    def guided_wizard_expired(self, cache_key: str, now=None) -> bool:
        return False

    def clear_guided_wizard_if_expired(self, cache_key: str, now=None) -> bool:
        return False


@pytest.fixture(autouse=True)
def isolated_handler_state(monkeypatch):
    store = MemoryStateStore()
    monkeypatch.setattr(handlers, "state_store", store)
    return store


def _view_body(values: dict) -> dict:
    return {
        "user": {"id": "U1", "team_id": "T1"},
        "team": {"id": "T1"},
        "trigger_id": "trig-1",
        "view": {
            "id": "V-1",
            "callback_id": "guided_standup_modal",
            "private_metadata": "T1:U1",
            "state": {"values": values},
        },
    }


def _edit_action_body(value: str = "42") -> dict:
    return {
        "user": {"id": "U1", "team_id": "T1"},
        "team": {"id": "T1"},
        "trigger_id": "trig-edit-1",
        "actions": [{"value": value}],
    }


def _edit_session(**overrides) -> UserSession:
    defaults: dict = dict(
        cache_key="T1:U1",
        team_id="T1",
        channel="C1",
        standup_name="DSU",
        schedule_id=7,
        compass_tasks=[dict(task) for task in TASKS],
        wizard_step=2,
        guided_edit=True,
        guided_submission_id=42,
        guided_answers=[
            {"ticket_key": "TECH-8", "ticket_title": "Despliegue Beta", "answer": "Texto previo del avance", "blocked": False},
            {"ticket_key": "TECH-9", "ticket_title": "Observabilidad", "answer": "", "blocked": True},
        ],
        wizard_answers={
            "progress": {"TECH-8": "Texto previo del avance"},
            "sin_avances": ["TECH-9"],
            "focus_items": [{"key": "TECH-8", "goal": "Cerrar el despliegue"}],
            "blockers": "Ninguno",
        },
    )
    defaults.update(overrides)
    session = UserSession(**defaults)
    handlers.state_store.save(session)
    return session


# ----- (a) confirmation DM carries the edit button with the standup id -----


def test_confirmation_dm_includes_guided_edit_button_with_standup_id():
    with (
        patch.object(handlers, "_persist_guided_submission", return_value=42),
        patch.object(
            handlers,
            "claim_guided_delivery",
            return_value={"channel_id": "C1", "channel_text": "t", "channel_blocks": []},
        ),
        patch.object(handlers, "mark_guided_delivery_delivered"),
        patch.object(handlers, "can_edit_response", return_value=True),
    ):
        _edit_session(guided_edit=False, guided_submission_id=None, wizard_step=2)
        client = MagicMock()
        client.chat_postMessage.side_effect = [{"ts": "1.1"}, {}]
        registered = _registered()
        registered[("view", "guided_standup_modal")](AckRecorder(), _view_body({"blockers": {"value": {"value": "Ninguno"}}}), client)

    dm_calls = [call.kwargs for call in client.chat_postMessage.call_args_list if call.kwargs.get("channel") == "U1"]
    assert dm_calls and dm_calls[-1]["text"] == "✅ Avance enviado."
    actions = [b for b in dm_calls[-1]["blocks"] if b["type"] == "actions"]
    assert actions and actions[0]["elements"][0]["action_id"] == "guided_edit"
    assert actions[0]["elements"][0]["value"] == "42"


# ----- (b) the click-time gate refuses outside the edit window -----


def test_guided_edit_refuses_outside_edit_window(monkeypatch):
    monkeypatch.setattr(handlers, "can_edit_response", lambda *a, **k: False)
    client = MagicMock()
    registered = _registered()
    registered[("action", "guided_edit")](AckRecorder(), _edit_action_body(), client)

    text = client.chat_postMessage.call_args.kwargs["text"]
    assert text.startswith("⏰")
    assert "no longer be changed" in text
    client.views_open.assert_not_called()


# ----- (c) the wizard reopens pre-filled from the stored session answers -----


def test_guided_edit_prefills_from_stored_session_answers(monkeypatch):
    monkeypatch.setattr(handlers, "can_edit_response", lambda *a, **k: True)
    _edit_session()
    client = MagicMock()
    registered = _registered()
    registered[("action", "guided_edit")](AckRecorder(), _edit_action_body("42"), client)

    view = client.views_open.call_args.kwargs["view"]
    assert view["callback_id"] == "guided_standup_modal"
    assert view["private_metadata"] == "T1:U1"
    progress_blocks = [b for b in view["blocks"] if b.get("block_id") == "progress_TECH-8"]
    assert progress_blocks
    assert any(key.startswith("initial") for key in progress_blocks[0]["element"])
    sin_blocks = [b for b in view["blocks"] if b.get("block_id") == "sin_avances_TECH-9"]
    assert sin_blocks
    assert any(opt["value"] == "sin_avances" for opt in sin_blocks[0]["element"].get("initial_options", []))
    session = handlers.state_store.get("T1:U1")
    assert session.guided_edit is True
    assert session.guided_submission_id == 42
    assert session.wizard_step == 0


# ----- (d) the parser handles "TICKET-KEY: text" and tolerates free text -----


def test_parser_reads_ticket_rows_and_sin_avances():
    entries = parse_progress_lines("TECH-8: Terminé la validación\nTECH-9: Sin avances hoy")
    assert entries[0] == {"ticket_key": "TECH-8", "ticket_title": "", "answer": "Terminé la validación", "blocked": False}
    assert entries[1]["ticket_key"] == "TECH-9"
    assert entries[1]["blocked"] is True


def test_parser_tolerates_free_text_rows():
    entries = parse_progress_lines("Una línea sin formato de ticket\notra libre")
    assert all(entry["ticket_key"] is None for entry in entries)
    assert entries[0]["answer"] == "Una línea sin formato de ticket"


def test_rebuild_guided_edit_recovers_wizard_answers():
    row = {
        "yesterday": "TECH-8: Terminé la validación\nTECH-99: Sin avances hoy",
        "today": "TECH-8: Cerrar el despliegue",
        "blockers": "Ninguno",
    }
    rebuilt = rebuild_guided_edit(row, [dict(task) for task in TASKS])
    assert rebuilt is not None
    assert rebuilt["wizard_answers"]["progress"] == {"TECH-8": "Terminé la validación"}
    assert rebuilt["wizard_answers"]["sin_avances"] == ["TECH-99"]
    # TECH-99 is absent from the snapshot but still gets a rendered field.
    assert {"key": "TECH-99", "title": ""} in rebuilt["compass_tasks"]
    assert rebuilt["wizard_answers"]["focus_items"] == [{"key": "TECH-8", "goal": "Cerrar el despliegue"}]
    assert rebuilt["wizard_answers"]["blockers"] == "Ninguno"


def test_rebuild_guided_edit_without_anything_recoverable_returns_none():
    assert rebuild_guided_edit({"yesterday": "", "today": "", "blockers": ""}, []) is None


def test_changed_guided_comments_only_keeps_text_that_changed():
    previous = [
        {"ticket_key": "TECH-8", "answer": "Texto previo del avance", "blocked": False},
        {"ticket_key": "TECH-9", "answer": "", "blocked": True},
    ]
    changed = changed_guided_comments(
        previous,
        [
            {"ticket_key": "TECH-8", "body": "Avance de U1:\nTexto nuevo"},
            {"ticket_key": "TECH-9", "body": "Avance de U1:\nSin avances hoy"},
        ],
    )
    assert [c["ticket_key"] for c in changed] == ["TECH-8"]


# ----- (e) resubmission updates the same row and syncs only changed tickets -----


def test_resubmit_updates_same_row_and_enqueues_changed_comments_only(monkeypatch):
    monkeypatch.setattr(handlers, "can_edit_response", lambda *a, **k: True)
    updates: list[dict] = []

    def fake_update(**kwargs):
        updates.append(kwargs)
        return True

    monkeypatch.setattr(comment_jobs, "update_guided_submission", fake_update)
    with (
        patch.object(handlers, "claim_guided_delivery", return_value={"channel_id": "C1", "channel_text": "t", "channel_blocks": []}) as claim,
        patch.object(handlers, "mark_guided_delivery_delivered") as mark_delivered,
    ):
        _edit_session(wizard_step=0)
        client = MagicMock()
        client.chat_postMessage.side_effect = [{"ts": "2.2"}, {}, {}]
        registered = _registered()
        ack = AckRecorder()
        submit = registered[("view", "guided_standup_modal")]
        # Walk the three wizard steps: progress, focus, blockers.
        submit(
            ack,
            _view_body(
                {
                    "progress_TECH-8": {"value": {"value": "Texto nuevo del avance"}},
                    "sin_avances_TECH-9": {"value": {"selected_options": [{"value": "sin_avances"}]}},
                }
            ),
            client,
        )
        submit(
            ack,
            _view_body(
                {
                    "focus_primary_ticket": {"value": {"selected_option": {"value": "TECH-8"}}},
                    "focus_primary_goal": {"value": {"value": "Cerrar el despliegue"}},
                    "focus_secondary_ticket": {"value": {"selected_option": {"value": "none"}}},
                }
            ),
            client,
        )
        submit(ack, _view_body({"blockers": {"value": {"value": "Ninguno"}}}), client)

    assert len(updates) == 1
    assert updates[0]["standup_id"] == 42
    # Only TECH-8 changed; TECH-9 stays "Sin avances hoy" and gets no new job.
    assert [c["ticket_key"] for c in updates[0]["comments"]] == ["TECH-8"]
    claim.assert_called_once_with(42)
    mark_delivered.assert_called_once_with(42, "2.2")
    confirmation = [call.kwargs for call in client.chat_postMessage.call_args_list if call.kwargs.get("channel") == "U1"]
    assert confirmation[-1]["text"] == "✅ Avance actualizado."
    assert handlers.state_store.get("T1:U1") is None


def test_resubmit_refuses_outside_edit_window(monkeypatch):
    monkeypatch.setattr(handlers, "can_edit_response", lambda *a, **k: False)
    updates: list[dict] = []
    monkeypatch.setattr(comment_jobs, "update_guided_submission", lambda **kwargs: updates.append(kwargs) or True)
    _edit_session()
    client = MagicMock()
    registered = _registered()
    registered[("view", "guided_standup_modal")](
        AckRecorder(),
        _view_body({"blockers": {"value": {"value": "Ninguno"}}}),
        client,
    )

    assert updates == []
    assert client.chat_postMessage.call_args.kwargs["text"].startswith("⏰")


# ----- (f) the legacy editor redirects guided submissions to the guided flow -----


def test_handle_standup_edit_redirects_guided_submission(monkeypatch):
    monkeypatch.setattr(handlers, "can_edit_response", lambda *a, **k: True)
    monkeypatch.setattr(handlers, "_get_guided_delivery_row", lambda standup_id: {"standup_id": standup_id, "state": "delivered"})
    opener = MagicMock(return_value=True)
    monkeypatch.setattr(handlers, "_open_guided_edit_session", opener)
    client = MagicMock()
    registered = _registered()
    registered[("action", "standup_edit")](AckRecorder(), _edit_action_body("42"), MagicMock(), client)

    opener.assert_called_once()
    assert opener.call_args.kwargs["standup_id"] == 42
    assert opener.call_args.kwargs["trigger_id"] == "trig-edit-1"
    posted = client.chat_postMessage.call_args_list
    assert all("Let's update your standup" not in str(call.kwargs) for call in posted)


def test_handle_standup_edit_keeps_legacy_editor_for_legacy_submissions(monkeypatch):
    monkeypatch.setattr(handlers, "can_edit_response", lambda *a, **k: True)
    monkeypatch.setattr(handlers, "_get_guided_delivery_row", lambda standup_id: None)

    class FakeDb:
        def get_schedule_for_user(self, team_id, user_id):
            return {"channel_id": "C1", "questions": ["q1", "q2", "q3"], "id": 7, "name": "DSU"}

        def get_standup_by_id(self, standup_id):
            return {"yesterday": "a", "today": "b", "blockers": "c"}

    import src.core.db as db

    monkeypatch.setattr(db, "get_schedule_for_user", FakeDb().get_schedule_for_user)
    monkeypatch.setattr(db, "get_standup_by_id", FakeDb().get_standup_by_id)

    client = MagicMock()
    registered = _registered()
    registered[("action", "standup_edit")](AckRecorder(), _edit_action_body("42"), MagicMock(), client)

    assert any("Let's update your standup" in str(call.kwargs) for call in client.chat_postMessage.call_args_list)
    session = handlers.state_store.get("T1:U1")
    assert session.editing_standup_id == 42


# ----- comment_jobs.update_guided_submission persistence shape -----


def test_update_guided_submission_rewrites_row_and_rearms_delivery(monkeypatch):
    from contextlib import contextmanager
    from unittest.mock import MagicMock as _M

    cursor = _M()
    cursor.rowcount = 1
    conn = _M()
    conn.cursor.return_value.__enter__.return_value = cursor

    @contextmanager
    def transaction():
        yield conn

    monkeypatch.setattr(comment_jobs.db, "db_conn", transaction)

    re_armed = comment_jobs.update_guided_submission(
        standup_id=42,
        answers=["TECH-8: Texto nuevo", "TECH-8: Meta nueva", "Ninguno"],
        channel_text="summary",
        channel_blocks=[{"type": "section"}],
        comments=[{"ticket_key": "TECH-8", "body": "Avance de U1:\nTexto nuevo"}],
    )

    assert re_armed is True
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert any("UPDATE standups" in s and "WHERE id = %s" in s for s in statements)
    assert any("UPDATE guided_standup_deliveries" in s and "state = 'pending'" in s for s in statements)
    assert any("DELETE FROM compass_comment_jobs" in s for s in statements)
    assert any("INSERT INTO compass_comment_jobs" in s for s in statements)
