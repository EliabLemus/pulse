"""Handler tests for the Compass-aware guided DSU modal flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from src.core.state import UserSession
from src.modules.standup import handlers

TASKS = [{"key": "TECH-8", "title": "Despliegue Beta", "dueDate": "2026-10-09"}]


class AckRecorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def __call__(self, **kwargs) -> None:
        self.calls.append(kwargs)


class FakeApp:
    """Record the decorators Bolt would register, without Bolt itself."""

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

    def save(self, session: UserSession) -> UserSession:
        self._sessions[session.cache_key] = session
        return session

    def clear(self, cache_key: str) -> None:
        self._sessions.pop(cache_key, None)


@pytest.fixture(autouse=True)
def isolated_handler_state(monkeypatch):
    store = MemoryStateStore()
    monkeypatch.setattr(handlers, "state_store", store)
    return store


def _save(session: UserSession) -> None:
    handlers.state_store.save(session)


def _guided_session(**overrides) -> UserSession:
    defaults: dict = dict(
        cache_key="T1:U1",
        team_id="T1",
        channel="C1",
        standup_name="DSU TechOps",
        compass_tasks=[dict(task) for task in TASKS],
    )
    defaults.update(overrides)
    session = UserSession(**defaults)
    _save(session)
    return session


def _form_body() -> dict:
    return {
        "user": {"id": "U1", "team_id": "T1"},
        "team": {"id": "T1"},
        "trigger_id": "trig-1",
        "actions": [{}],
    }


def _view_body(values: dict) -> dict:
    return {
        "user": {"id": "U1", "team_id": "T1"},
        "team": {"id": "T1"},
        "view": {
            "id": "V-1",
            "callback_id": "guided_standup_modal",
            "private_metadata": "T1:U1",
            "state": {"values": values},
        },
    }


def _has_block(view: dict, block_id: str) -> bool:
    return any(block.get("block_id") == block_id for block in view["blocks"])


def test_fill_in_form_without_compass_tasks_opens_the_legacy_form():
    _guided_session(compass_tasks=[])
    client = MagicMock()

    registered = _registered()
    registered[("action", "fill_in_form")](AckRecorder(), _form_body(), client)

    kwargs = client.views_open.call_args.kwargs
    assert kwargs["view"]["callback_id"] == "standup_form_modal"
    assert kwargs["view"]["private_metadata"] == "T1:U1"


def test_fill_in_form_with_compass_tasks_opens_guided_modal_at_session_step():
    _guided_session(wizard_step=1, wizard_answers={"progress": {"TECH-8": "avance previo"}})
    client = MagicMock()

    registered = _registered()
    registered[("action", "fill_in_form")](AckRecorder(), _form_body(), client)

    view = client.views_open.call_args.kwargs["view"]
    assert view["callback_id"] == "guided_standup_modal"
    assert _has_block(view, "focus_primary_ticket")
    assert view["private_metadata"] == "T1:U1"


def test_step0_key_only_progress_is_rejected_on_the_exact_field():
    _guided_session(wizard_step=0)
    client = MagicMock()
    ack = AckRecorder()

    registered = _registered()
    registered[("view", "guided_standup_modal")](
        ack, _view_body({"progress_TECH-8": {"value": {"value": "TECH-8"}}}), client
    )

    assert len(ack.calls) == 1
    assert ack.calls[0]["response_action"] == "errors"
    assert set(ack.calls[0]["errors"]) == {"progress_TECH-8"}
    client.views_update.assert_not_called()
    session = handlers.state_store.get("T1:U1")
    assert session.wizard_step == 0
    assert "progress" not in session.wizard_answers


def test_step0_identity_only_text_with_no_progress_mark_records_the_mark():
    _guided_session(wizard_step=0)
    client = MagicMock()
    ack = AckRecorder()
    values = {
        "progress_TECH-8": {"value": {"value": "TECH-8"}},
        "sin_avances_TECH-8": {"value": {"selected_options": [{"value": "sin_avances"}]}},
    }

    registered = _registered()
    registered[("view", "guided_standup_modal")](ack, _view_body(values), client)

    assert ack.calls[0]["response_action"] == "update"
    assert _has_block(ack.calls[0]["view"], "focus_primary_ticket")
    client.views_update.assert_not_called()
    session = handlers.state_store.get("T1:U1")
    assert session is not None
    assert session.wizard_answers["progress"] == {}
    assert session.wizard_answers["sin_avances"] == ["TECH-8"]


def test_step0_all_blank_progress_requires_an_explicit_status():
    _guided_session(wizard_step=0)
    client = MagicMock()
    ack = AckRecorder()

    registered = _registered()
    registered[("view", "guided_standup_modal")](ack, _view_body({"progress_TECH-8": {"value": {"value": ""}}}), client)

    assert ack.calls == [
        {"response_action": "errors", "errors": {"progress_TECH-8": "Describe un avance o marca «Sin avances hoy»."}}
    ]
    assert handlers.state_store.get("T1:U1").wizard_step == 0


def test_step0_all_tickets_marked_without_progress_advances_and_persists_marks():
    _guided_session(
        wizard_step=0,
        compass_tasks=[
            {"key": "TECH-8", "title": "Despliegue Beta"},
            {"key": "TECH-9", "title": "Observabilidad"},
        ],
    )
    client = MagicMock()
    ack = AckRecorder()
    values = {
        "progress_TECH-8": {"value": {"value": ""}},
        "sin_avances_TECH-8": {"value": {"selected_options": [{"value": "sin_avances"}]}},
        "progress_TECH-9": {"value": {"value": ""}},
        "sin_avances_TECH-9": {"value": {"selected_options": [{"value": "sin_avances"}]}},
    }

    registered = _registered()
    registered[("view", "guided_standup_modal")](ack, _view_body(values), client)

    assert ack.calls[0]["response_action"] == "update"
    assert _has_block(ack.calls[0]["view"], "focus_primary_ticket")
    client.views_update.assert_not_called()
    session = handlers.state_store.get("T1:U1")
    assert session.wizard_step == 1
    assert session.wizard_answers["progress"] == {}
    assert session.wizard_answers["sin_avances"] == ["TECH-8", "TECH-9"]


def test_step0_requires_an_explicit_status_for_each_ticket():
    _guided_session(
        wizard_step=0,
        compass_tasks=[
            {"key": "TECH-8", "title": "Despliegue Beta"},
            {"key": "TECH-9", "title": "Observabilidad"},
        ],
    )
    client = MagicMock()
    ack = AckRecorder()
    values = {
        "progress_TECH-8": {"value": {"value": ""}},
        "sin_avances_TECH-8": {"value": {"selected_options": [{"value": "sin_avances"}]}},
        "progress_TECH-9": {"value": {"value": ""}},
        "sin_avances_TECH-9": {"value": {"selected_options": []}},
    }

    registered = _registered()
    registered[("view", "guided_standup_modal")](ack, _view_body(values), client)

    assert ack.calls == [
        {"response_action": "errors", "errors": {"progress_TECH-9": "Describe un avance o marca «Sin avances hoy»."}}
    ]
    session = handlers.state_store.get("T1:U1")
    assert session is not None
    assert session.wizard_step == 0


def test_step0_substantive_text_wins_over_the_no_progress_mark():
    _guided_session(
        wizard_step=0,
        compass_tasks=[
            {"key": "TECH-8", "title": "Despliegue Beta"},
            {"key": "TECH-9", "title": "Observabilidad"},
        ],
    )
    client = MagicMock()
    ack = AckRecorder()
    text = "Terminé la validación con Ada y Manuel."
    values = {
        "progress_TECH-8": {"value": {"value": text}},
        "sin_avances_TECH-8": {"value": {"selected_options": [{"value": "sin_avances"}]}},
        "progress_TECH-9": {"value": {"value": ""}},
        "sin_avances_TECH-9": {"value": {"selected_options": [{"value": "sin_avances"}]}},
    }

    registered = _registered()
    registered[("view", "guided_standup_modal")](ack, _view_body(values), client)

    assert ack.calls[0]["response_action"] == "update"
    assert _has_block(ack.calls[0]["view"], "focus_primary_ticket")
    client.views_update.assert_not_called()
    session = handlers.state_store.get("T1:U1")
    assert session is not None
    assert session.wizard_answers["progress"] == {"TECH-8": text}
    assert session.wizard_answers["sin_avances"] == ["TECH-9"]


def test_step0_valid_next_updates_to_step1_and_preserves_values():
    _guided_session(wizard_step=0)
    client = MagicMock()
    ack = AckRecorder()
    text = "TECH-8: terminé la validación del pipeline."

    registered = _registered()
    registered[("view", "guided_standup_modal")](
        ack, _view_body({"progress_TECH-8": {"value": {"value": text}}}), client
    )

    assert len(ack.calls) == 1
    assert ack.calls[0]["response_action"] == "update"
    modal = ack.calls[0]["view"]
    assert modal["callback_id"] == "guided_standup_modal"
    assert _has_block(modal, "focus_primary_ticket")
    client.views_update.assert_not_called()
    session = handlers.state_store.get("T1:U1")
    assert session.wizard_step == 1
    assert session.wizard_answers["progress"]["TECH-8"] == text
    client.chat_postMessage.assert_not_called()


def test_step1_persists_two_focus_items_and_shows_step2():
    from src.modules.standup.compass import CompassClient

    mcp = MagicMock()
    with patch.object(CompassClient, "_call_mcp", mcp):
        _guided_session(wizard_step=1, wizard_answers={"progress": {"TECH-8": "avance previo"}})
        client = MagicMock()
        ack = AckRecorder()
        values = {
            "focus_primary_ticket": {"value": {"selected_option": {"value": "TECH-8"}}},
            "focus_primary_goal": {"value": {"value": "Cerrar el despliegue a producción"}},
            "focus_secondary_ticket": {"value": {"selected_option": {"value": "TECH-9"}}},
            "focus_secondary_goal": {"value": {"value": "Documentar el monitoreo"}},
        }
        session = handlers.state_store.get("T1:U1")
        assert session is not None
        session.compass_tasks.append({"key": "TECH-9", "title": "Observabilidad"})

        registered = _registered()
        registered[("view", "guided_standup_modal")](ack, _view_body(values), client)

    assert len(ack.calls) == 1
    assert ack.calls[0]["response_action"] == "update"
    assert _has_block(ack.calls[0]["view"], "blockers")
    client.views_update.assert_not_called()
    session = handlers.state_store.get("T1:U1")
    assert session is not None
    assert session.wizard_step == 2
    assert session.wizard_answers["focus_items"] == [
        {"key": "TECH-8", "goal": "Cerrar el despliegue a producción"},
        {"key": "TECH-9", "goal": "Documentar el monitoreo"},
    ]
    assert session.wizard_answers["progress"]["TECH-8"] == "avance previo"
    mcp.assert_not_called()
    client.chat_postMessage.assert_not_called()


def test_step2_final_submission_queues_ticket_comments_and_posts_one_root_message():
    with (
        patch.object(handlers, "_persist_guided_submission", return_value=42) as persist,
        patch.object(
            handlers,
            "claim_guided_delivery",
            side_effect=lambda _standup_id: {
                "channel_id": "C1",
                "channel_text": persist.call_args.kwargs["channel_text"],
                "channel_blocks": persist.call_args.kwargs["channel_blocks"],
            },
        ),
        patch.object(handlers, "mark_guided_delivery_delivered") as mark_delivered,
    ):
        _guided_session(
            schedule_id=7,
            wizard_step=2,
            compass_tasks=[
                {"key": "TECH-8", "title": "Despliegue Beta", "url": "https://compass.zubale.com/tickets/TECH-8"},
                {
                    "key": "TECH-9",
                    "title": "Observabilidad",
                    "url": "https://compass.zubale.com/portal/tasks/1e2a76cd-29c7-4747-bebc-3e6474956540",
                },
            ],
            wizard_answers={
                "progress": {"TECH-8": "Terminé la validación del pipeline."},
                "sin_avances": ["TECH-9"],
                "focus_items": [
                    {"key": "TECH-8", "goal": "Cerrar el despliegue a producción"},
                    {"key": "TECH-9", "goal": "Documentar el monitoreo"},
                ],
            },
        )
        client = MagicMock()
        client.chat_postMessage.side_effect = [{"ts": "1791218007.640279"}, {}]
        ack = AckRecorder()

        registered = _registered()
        registered[("view", "guided_standup_modal")](
            ack, _view_body({"blockers": {"value": {"value": "Ninguno"}}}), client
        )

    assert ack.calls == [{}]
    assert persist.call_args.kwargs["answers"] == [
        "TECH-8: Terminé la validación del pipeline.\nTECH-9: Sin avances hoy",
        "TECH-8: Cerrar el despliegue a producción\nTECH-9: Documentar el monitoreo",
        "Ninguno",
    ]
    assert persist.call_args.kwargs["comments"] == [
        {"ticket_key": "TECH-8", "body": "Avance de U1:\nTerminé la validación del pipeline."}
    ]
    channel_post = client.chat_postMessage.call_args_list[0].kwargs
    assert channel_post["channel"] == "C1"
    assert channel_post["unfurl_links"] is False
    assert channel_post["unfurl_media"] is False
    assert channel_post["text"] == (
        "*<@U1>*\n"
        "*Avances*\n\n"
        "• TECH-8 — *Despliegue Beta*\n"
        "  Terminé la validación del pipeline.\n"
        "• <https://compass.zubale.com/portal/tasks/1e2a76cd-29c7-4747-bebc-3e6474956540|TECH-9> — *Observabilidad*\n"
        "  _Sin avances hoy_\n\n"
        "*Foco de hoy*\n"
        "• TECH-8 — *Despliegue Beta*\n"
        "  Cerrar el despliegue a producción\n"
        "• <https://compass.zubale.com/portal/tasks/1e2a76cd-29c7-4747-bebc-3e6474956540|TECH-9> — *Observabilidad*\n"
        "  Documentar el monitoreo"
    )
    assert [block["type"] for block in channel_post["blocks"]] == ["header", "context", "section", "divider", "section"]
    assert "TECH-55" not in str(channel_post["blocks"])
    assert "TECH-8" in str(channel_post["blocks"])
    assert "TECH-9" in str(channel_post["blocks"])
    mark_delivered.assert_called_once_with(42, "1791218007.640279")
    assert client.chat_postMessage.call_args_list[1].kwargs["channel"] == "U1"
    assert handlers.state_store.get("T1:U1") is None


def test_guided_channel_post_never_links_a_non_compass_task_url():
    text = handlers._format_guided_channel_post(
        "U1",
        [{"key": "TECH-8", "title": "Deploy", "url": "https://example.com/keep"}],
        {"progress": {"TECH-8": "Listo"}},
    )

    assert "• TECH-8 — *Deploy*" in text
    assert "https://example.com/keep" not in text


def test_guided_channel_failure_marks_delivery_unknown_and_keeps_the_session():
    delivery = {"channel_id": "C1", "channel_text": "*<@U1>*\nAvance"}
    with (
        patch.object(handlers, "_persist_guided_submission", return_value=42),
        patch.object(handlers, "claim_guided_delivery", return_value=delivery),
        patch.object(handlers, "mark_guided_delivery_unknown") as mark_unknown,
    ):
        _guided_session(
            schedule_id=7,
            wizard_step=2,
            wizard_answers={"progress": {"TECH-8": "Listo"}, "priority_goal": "Cerrar despliegue"},
        )
        client = MagicMock()
        client.chat_postMessage.side_effect = RuntimeError("request outcome unknown")
        ack = AckRecorder()

        registered = _registered()
        registered[("view", "guided_standup_modal")](
            ack, _view_body({"blockers": {"value": {"value": "Ninguno"}}}), client
        )

    mark_unknown.assert_called_once()
    assert mark_unknown.call_args.args[0] == 42
    assert handlers.state_store.get("T1:U1") is not None


def test_step2_final_submission_does_not_call_compass_from_the_daemon():
    from src.modules.standup.compass import CompassClient

    mcp = MagicMock()
    delivery = {"channel_id": "C1", "channel_text": "*<@U1>*\nAvance"}
    with (
        patch.object(CompassClient, "_call_mcp", mcp),
        patch.object(handlers, "_persist_guided_submission", return_value=42),
        patch.object(handlers, "claim_guided_delivery", return_value=delivery),
        patch.object(handlers, "mark_guided_delivery_delivered"),
    ):
        _guided_session(
            schedule_id=7,
            wizard_step=2,
            wizard_answers={
                "progress": {"TECH-8": "Terminé la validación del pipeline."},
                "priority_key": "TECH-8",
                "priority_goal": "Cerrar el despliegue a producción",
            },
        )
        client = MagicMock()
        client.chat_postMessage.side_effect = [{"ts": "1791218007.640279"}, {}]
        ack = AckRecorder()

        registered = _registered()
        registered[("view", "guided_standup_modal")](
            ack, _view_body({"blockers": {"value": {"value": "Necesito acceso a staging"}}}), client
        )

    assert ack.calls == [{}]
    assert [call.kwargs["channel"] for call in client.chat_postMessage.call_args_list] == ["C1", "U1"]
    client.views_update.assert_not_called()
    mcp.assert_not_called()
    assert handlers.state_store.get("T1:U1") is None


def test_step2_persistence_failure_keeps_session_for_retry_and_never_confirms_success():
    _guided_session(
        schedule_id=7,
        wizard_step=2,
        wizard_answers={
            "progress": {"TECH-8": "Terminé la validación del pipeline."},
            "priority_goal": "Cerrar el despliegue a producción",
        },
    )
    client = MagicMock()
    ack = AckRecorder()

    with patch.object(handlers, "_persist_guided_submission", return_value=None):
        registered = _registered()
        registered[("view", "guided_standup_modal")](
            ack, _view_body({"blockers": {"value": {"value": "Necesito acceso a staging"}}}), client
        )

    assert ack.calls == [{}]
    session = handlers.state_store.get("T1:U1")
    assert session is not None
    assert session.wizard_step == 2
    assert session.wizard_answers["blockers"] == "Necesito acceso a staging"
    assert client.chat_postMessage.call_args.kwargs["channel"] == "U1"
    assert "No pude guardar" in client.chat_postMessage.call_args.kwargs["text"]
    assert "✅" not in client.chat_postMessage.call_args.kwargs["text"]


def test_guided_back_restores_no_progress_marks():
    _guided_session(wizard_step=1, wizard_answers={"progress": {}, "sin_avances": ["TECH-8"]})
    client = MagicMock()
    ack = AckRecorder()
    body = _view_body(
        {
            "focus_primary_ticket": {"value": {"selected_option": {"value": "TECH-8"}}},
            "focus_primary_goal": {"value": {"value": "Cerrar el despliegue a producción"}},
        }
    )

    registered = _registered()
    registered[("action", "guided_back")](ack, body, client)

    view = client.views_update.call_args.kwargs["view"]
    marked = next(block for block in view["blocks"] if block.get("block_id") == "sin_avances_TECH-8")
    assert marked["element"]["initial_options"][0]["value"] == "sin_avances"


def test_guided_back_from_priority_preserves_values_and_returns_to_progress():
    _guided_session(wizard_step=1, wizard_answers={"progress": {"TECH-8": "avance previo"}})
    client = MagicMock()
    ack = AckRecorder()
    body = _view_body(
        {
            "focus_primary_ticket": {"value": {"selected_option": {"value": "TECH-8"}}},
            "focus_primary_goal": {"value": {"value": "Cerrar el despliegue a producción"}},
        }
    )

    registered = _registered()
    registered[("action", "guided_back")](ack, body, client)

    assert ack.calls == [{}]
    assert client.views_update.call_args.kwargs["view_id"] == "V-1"
    assert _has_block(client.views_update.call_args.kwargs["view"], "progress_TECH-8")
    session = handlers.state_store.get("T1:U1")
    assert session.wizard_step == 0
    assert session.wizard_answers["focus_items"] == [{"key": "TECH-8", "goal": "Cerrar el despliegue a producción"}]
