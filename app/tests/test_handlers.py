"""Tests for handlers.py — Slack event handler logic with mocked dependencies."""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

from blocks import mrkdwn_to_rich_text  # noqa: E402

# Stub heavy third-party deps before any import of handlers
_slack_bolt_mock = MagicMock()
_requests_mock = MagicMock()
_pytz_mock = MagicMock()
sys.modules.setdefault("slack_bolt", _slack_bolt_mock)
sys.modules.setdefault("requests", _requests_mock)
sys.modules.setdefault("pytz", _pytz_mock)

# Stub session_store before importing state (state.py imports it at module level).
# Save the prior value so we can restore it after the import — this prevents
# test_session_store.py from receiving the mock when it imports session_store.
_prior_session_store = sys.modules.get("session_store")
_ss_mock = MagicMock()
_ss_mock.get_session.return_value = None
_ss_mock.has_session.return_value = False
sys.modules["session_store"] = _ss_mock

import state  # noqa: E402 — must come after session_store stub

# Restore session_store so subsequent test modules see the real one
if _prior_session_store is not None:
    sys.modules["session_store"] = _prior_session_store
else:
    sys.modules.pop("session_store", None)


# ---------------------------------------------------------------------------
# _format_standup
# ---------------------------------------------------------------------------


class TestFormatStandup:
    def test_includes_user_mention(self):
        from handlers import _format_standup

        result = _format_standup("U1", ["Yesterday work", "Today work", "None"])
        assert "<@U1>" in result

    def test_includes_date(self):
        from handlers import _format_standup

        result = _format_standup("U1", ["y", "t", "b"])
        assert datetime.utcnow().strftime("%Y") in result

    def test_blockers_none_text(self):
        from handlers import _format_standup

        result = _format_standup("U1", ["y", "t", "none"])
        assert "_None_" in result

    def test_blockers_n_a_text(self):
        from handlers import _format_standup

        result = _format_standup("U1", ["y", "t", "n/a"])
        assert "_None_" in result

    def test_real_blocker_preserved(self):
        from handlers import _format_standup

        result = _format_standup("U1", ["y", "t", "Waiting on PR review"])
        assert "Waiting on PR review" in result

    def test_questions_are_bold_without_trailing_colon(self):
        from handlers import _format_standup

        questions = [
            "¿Qué lograste avanzar o completar ayer?",
            "¿Cuál es tu tarea principal para hoy?",
            "¿Tienes algún bloqueo que te impida avanzar hoy?",
        ]
        result = _format_standup("U1", ["ayer", "hoy", "sin bloqueos"], questions=questions)
        for q in questions:
            assert f"{q}:*" not in result  # colon removed
            assert f"*{q}*\n" in result  # question fully bold, answer below

    def test_clean_style_without_decorative_emojis(self):
        from handlers import _format_standup

        questions = [
            "¿Qué lograste avanzar o completar ayer?",
            "¿Cuál es tu tarea principal para hoy?",
            "¿Tienes algún bloqueo que te impida avanzar hoy?",
        ]
        result = _format_standup("U1", ["ayer", "hoy", "sin bloqueos"], questions=questions)
        assert "📋" not in result
        assert "✅" not in result
        assert re.search(r"\*Avances de <@U1>\* - \d{1,2} de \w+ de \d{4}", result)

    def test_mood_included_when_provided(self):
        from handlers import _format_standup

        result = _format_standup("U1", ["y", "t", "none"], mood="😊 great")
        assert "😊 great" in result

    def test_mood_omitted_when_none(self):
        from handlers import _format_standup

        result = _format_standup("U1", ["y", "t", "none"], mood=None)
        assert "Mood" not in result

    def test_fewer_than_three_answers_handled(self):
        from handlers import _format_standup

        result = _format_standup("U1", ["only one answer"])
        assert "only one answer" in result
        assert "—" in result  # missing answers show —


# ---------------------------------------------------------------------------
# _persist_standup
# ---------------------------------------------------------------------------


class TestPersistStandup:
    def test_calls_db_save_standup(self):
        db_mock = MagicMock()
        with patch.dict(sys.modules, {"db": db_mock}):
            from handlers import _persist_standup

            _persist_standup("T1", "U1", ["y", "t", "b"], mood="😊")

        db_mock.save_standup.assert_called_once()
        call_kwargs = db_mock.save_standup.call_args
        assert call_kwargs.kwargs["team_id"] == "T1"
        assert call_kwargs.kwargs["user_id"] == "U1"

    def test_does_not_raise_on_db_error(self):
        db_mock = MagicMock()
        db_mock.save_standup.side_effect = Exception("DB unavailable")
        with patch.dict(sys.modules, {"db": db_mock}):
            from handlers import _persist_standup

            _persist_standup("T1", "U1", ["y", "t", "b"])  # should not raise


# ---------------------------------------------------------------------------
# Single-form submission
# ---------------------------------------------------------------------------


def _standup_form_handler():
    """Register the production callbacks and return the single-form submit handler."""
    import handlers

    captured: dict = {}
    app = MagicMock()
    app.view.side_effect = lambda callback_id: lambda fn: captured.setdefault(callback_id, fn)
    app.action.side_effect = lambda *_args, **_kwargs: lambda fn: fn
    app.event.side_effect = lambda *_args, **_kwargs: lambda fn: fn
    app.command.side_effect = lambda *_args, **_kwargs: lambda fn: fn
    app.options.side_effect = lambda *_args, **_kwargs: lambda fn: fn
    app.shortcut.side_effect = lambda *_args, **_kwargs: lambda fn: fn
    handlers.register_handlers(app)
    return captured["standup_form_modal"]


class TestSingleFormSubmission:
    def test_form_submission_completes_after_three_answers_without_mood(self):
        import handlers

        session = state.UserSession(cache_key="T1:U1", team_id="T1", channel="C1", questions=["Q1", "Q2", "Q3"])
        fresh = state.UserSession(
            cache_key="T1:U1",
            team_id="T1",
            channel="C1",
            questions=["Q1", "Q2", "Q3"],
            answers=["ayer", "hoy", "sin bloqueos"],
            step=3,
        )
        session.answers = ["stale yesterday", "stale today"]
        session.step = 2
        body = {
            "user": {"id": "U1"},
            "team": {"id": "T1"},
            "view": {
                "private_metadata": "T1:U1",
                "state": {
                    "values": {
                        f"question_{index}": {f"answer_{index}": {"value": answer}}
                        for index, answer in enumerate(["ayer", "hoy", "sin bloqueos"])
                    }
                },
            },
        }
        client = MagicMock()

        with (
            patch.object(handlers.state_store, "get", return_value=session),
            patch.object(handlers.state_store, "replace_answers", return_value=fresh) as replace_answers,
            patch.object(handlers, "_complete_standup") as complete,
            patch.object(handlers, "_send_mood_block") as send_mood,
        ):
            _standup_form_handler()(MagicMock(), body, client)

        replace_answers.assert_called_once_with("T1:U1", ["ayer", "hoy", "sin bloqueos"])
        complete.assert_called_once_with("U1", fresh, client)
        send_mood.assert_not_called()

    def test_fill_in_form_renders_progress_inputs_for_the_session_compass_tasks(self):
        import handlers

        session = state.UserSession(
            cache_key="T1:U1",
            team_id="T1",
            channel="C1",
            questions=["Q1", "Q2", "Q3"],
            compass_tasks=[{"key": "TOP-1", "title": "Improve deployment"}],
        )
        body = {"user": {"id": "U1"}, "team": {"id": "T1"}, "trigger_id": "tr-1"}
        client = MagicMock()

        with patch.object(handlers.state_store, "get", return_value=session):
            _action_handler("fill_in_form")(MagicMock(), body, client)

        view = client.views_open.call_args.kwargs["view"]
        context = next(block for block in view["blocks"] if block.get("block_id") == "compass_context")
        assert "<https://compass.zubale.com/tickets/TOP-1|TOP-1>" in context["text"]["text"]
        expected = mrkdwn_to_rich_text("TOP-1: ")
        assert [block["element"]["initial_value"] for block in view["blocks"] if block["type"] == "input"] == [
            expected,
            expected,
            expected,
        ]

    def test_form_submission_syncs_progress_before_completing_the_standup(self):
        import handlers

        session = state.UserSession(
            cache_key="T1:U1",
            team_id="T1",
            channel="C1",
            questions=["Q1", "Q2", "Q3"],
            compass_tasks=[{"key": "TOP-1", "title": "Improve deployment"}],
        )
        fresh = state.UserSession(cache_key="T1:U1", team_id="T1", channel="C1", questions=["Q1", "Q2", "Q3"])
        values = {
            "question_0": {"answer_0": {"value": "ayer"}},
            "question_1": {"answer_1": {"value": "hoy"}},
            "question_2": {"answer_2": {"value": "sin bloqueos"}},
            "compass_progress_0": {"progress_0": {"value": "Listo para revisión."}},
        }
        body = {
            "user": {"id": "U1"},
            "team": {"id": "T1"},
            "view": {"private_metadata": "T1:U1", "state": {"values": values}},
        }
        client = MagicMock()

        with (
            patch.object(handlers.state_store, "get", return_value=session),
            patch.object(handlers.state_store, "replace_answers", return_value=fresh),
            patch.object(handlers, "_sync_compass_progress", return_value=(1, [])) as sync,
            patch.object(handlers, "_complete_standup") as complete,
        ):
            _standup_form_handler()(MagicMock(), body, client)

        sync.assert_called_once_with(fresh, values)
        complete.assert_called_once_with("U1", fresh, client)

    def test_submission_comments_tickets_with_content_after_their_key_line(self, monkeypatch):
        import handlers

        session = state.UserSession(
            cache_key="T1:U1",
            team_id="T1",
            channel="C1",
            compass_tasks=[
                {"key": "TECH-12", "title": "Taxonomia"},
                {"key": "TECH-1", "title": "SigNoz"},
                {"key": "TECH-3", "title": "Onboarding"},
            ],
        )
        compass = MagicMock()
        monkeypatch.setenv("COMPASS_API_KEY", "cmp_test")

        with patch.object(handlers, "CompassClient", return_value=compass):
            synced, failures = handlers._sync_compass_progress(
                session,
                {
                    "question_0": {"answer_0": {"value": "TECH-12: avance a b y c\nTECH-1: \nTECH-3: "}},
                    "question_1": {"answer_1": {"value": "TECH-12: \nTECH-1: sigo dashboards\nTECH-3: "}},
                    "question_2": {"answer_2": {"value": "TECH-3 bloqueado por accesos (sin plantilla)"}},
                },
            )

        assert (synced, failures) == (2, [])
        comments = {call.args[0]: call.args[1] for call in compass.post_comment.call_args_list}
        assert set(comments) == {"TECH-12", "TECH-1"}
        assert comments["TECH-12"] == "Actualización de Pulse:\navance a b y c"
        assert comments["TECH-1"] == "Actualización de Pulse:\nsigo dashboards"

    def test_submission_with_cleared_templates_posts_no_compass_comments(self, monkeypatch):
        import handlers

        session = state.UserSession(
            cache_key="T1:U1",
            team_id="T1",
            channel="C1",
            compass_tasks=[{"key": "TOP-1", "title": "Improve deployment"}],
        )
        compass = MagicMock()
        monkeypatch.setenv("COMPASS_API_KEY", "cmp_test")

        with patch.object(handlers, "CompassClient", return_value=compass):
            synced, failures = handlers._sync_compass_progress(
                session,
                {
                    "question_0": {"answer_0": {"value": "Revisé PRs del equipo"}},
                    "question_1": {"answer_1": {"value": "Documentación interna"}},
                    "question_2": {"answer_2": {"value": "Sin bloqueos"}},
                },
            )

        assert (synced, failures) == (0, [])
        compass.post_comment.assert_not_called()

    def test_form_submission_completes_and_reports_compass_failures(self):
        import handlers

        session = state.UserSession(cache_key="T1:U1", team_id="T1", channel="C1", questions=["Q1", "Q2", "Q3"])
        values = {
            "question_0": {"answer_0": {"value": "ayer"}},
            "question_1": {"answer_1": {"value": "hoy"}},
            "question_2": {"answer_2": {"value": "sin bloqueos"}},
        }
        body = {
            "user": {"id": "U1"},
            "team": {"id": "T1"},
            "view": {"private_metadata": "T1:U1", "state": {"values": values}},
        }
        client = MagicMock()

        with (
            patch.object(handlers.state_store, "get", return_value=session),
            patch.object(handlers.state_store, "replace_answers", return_value=session),
            patch.object(handlers, "_sync_compass_progress", return_value=(0, ["TOP-1"])),
            patch.object(handlers, "_complete_standup") as complete,
        ):
            _standup_form_handler()(MagicMock(), body, client)

        complete.assert_called_once_with("U1", session, client)
        assert (
            client.chat_postMessage.call_args.kwargs["text"]
            == "Tu update se publicó, pero no pude actualizar Compass para: TOP-1"
        )


# ---------------------------------------------------------------------------
# Recoverable skip / resume
# ---------------------------------------------------------------------------


def _action_handler(action_id: str):
    """Register the production callbacks and return one action callback."""
    import handlers

    captured: dict = {}
    app = MagicMock()
    app.view.side_effect = lambda *_a, **_k: lambda fn: fn
    app.event.side_effect = lambda *_a, **_k: lambda fn: fn
    app.command.side_effect = lambda *_a, **_k: lambda fn: fn
    app.options.side_effect = lambda *_a, **_k: lambda fn: fn
    app.shortcut.side_effect = lambda *_a, **_k: lambda fn: fn

    def action(name, *_a, **_k):
        def decorator(fn):
            key = name.pattern if hasattr(name, "pattern") else name
            captured.setdefault(key, fn)
            return fn

        return decorator

    app.action.side_effect = action
    handlers.register_handlers(app)
    return captured[action_id]


class TestRecoverableSkip:
    def _skip_body(self):
        return {
            "user": {"id": "U1", "team_id": "T1"},
            "team": {"id": "T1"},
            "actions": [{"action_id": "skip_standup", "value": "skip_standup"}],
        }

    def test_skip_confirmation_offers_a_recovery_button(self):

        client = MagicMock()
        db_mock = MagicMock()
        with patch.dict(sys.modules, {"db": db_mock}):
            _action_handler("skip_standup")(ack=MagicMock(), body=self._skip_body(), client=client)

        db_mock.skip_today.assert_called_once_with("T1", "U1")
        blocks = client.chat_postMessage.call_args.kwargs["blocks"]
        buttons = [e for b in blocks if b["type"] == "actions" for e in b["elements"]]
        assert any(e["action_id"] == "resume_standup" for e in buttons)

    def test_resume_unskips_and_opens_the_form_directly(self):
        import handlers

        client = MagicMock()
        db_mock = MagicMock()
        db_mock.get_standup_schedule_for_channel.return_value = None
        session = state.UserSession(cache_key="T1:U1", team_id="T1", channel="C1", questions=["Q1", "Q2", "Q3"])
        body = {
            "user": {"id": "U1", "team_id": "T1"},
            "team": {"id": "T1"},
            "trigger_id": "tr-1",
            "actions": [{"action_id": "resume_standup"}],
        }
        with (
            patch.dict(sys.modules, {"db": db_mock}),
            patch.object(handlers, "_start_standup_session") as start,
            patch.object(handlers.state_store, "get", return_value=session),
        ):
            _action_handler("resume_standup")(ack=MagicMock(), body=body, client=client)

        db_mock.unskip_today.assert_called_once_with("T1", "U1")
        start.assert_called_once_with("U1", "T1", client)
        assert client.views_open.call_args.kwargs["trigger_id"] == "tr-1"

    def test_manual_start_clears_todays_skip(self):
        from handlers import _start_standup_session

        client = MagicMock()
        db_mock = MagicMock()
        db_mock.get_schedule_for_user.return_value = None
        db_mock.get_workspace_config.return_value = {"channel_id": "C1", "questions": ["Q1", "Q2", "Q3"]}
        with (
            patch.dict(sys.modules, {"db": db_mock}),
            patch.object(state.state_store, "is_active", return_value=False),
            patch.object(state.state_store, "start"),
        ):
            _start_standup_session("U1", "T1", client)

        db_mock.unskip_today.assert_called_once_with("T1", "U1")

    def test_text_skip_also_offers_the_recovery_button(self):
        import handlers

        captured = {}
        app = MagicMock()
        app.view.side_effect = lambda *_a, **_k: lambda fn: fn
        app.event.side_effect = lambda *_a, **_k: lambda fn: fn
        app.command.side_effect = lambda *_a, **_k: lambda fn: fn
        app.options.side_effect = lambda *_a, **_k: lambda fn: fn
        app.shortcut.side_effect = lambda *_a, **_k: lambda fn: fn

        def register(kind):
            def registration(name=None, *_a, **_k):
                def decorator(fn):
                    key = name.pattern if hasattr(name, "pattern") else name
                    captured[(kind, key)] = fn
                    return fn

                return decorator

            return registration

        app.action.side_effect = register("action")
        app.message.side_effect = register("message")
        handlers.register_handlers(app)
        say = MagicMock()
        db_mock = MagicMock()
        with patch.dict(sys.modules, {"db": db_mock}):
            captured[("message", "skip")]({"channel_type": "im", "user": "U1", "team": "T1"}, say)

        db_mock.skip_today.assert_called_once_with("T1", "U1")
        blocks = say.call_args.kwargs["blocks"]
        buttons = [e for b in blocks if b["type"] == "actions" for e in b["elements"]]
        assert any(e["action_id"] == "resume_standup" for e in buttons)


class TestSingleFormEdit:
    def test_edit_opens_prefilled_modal_instead_of_step_by_step(self):
        import handlers

        client = MagicMock()
        db_mock = MagicMock()
        db_mock.get_schedule_for_user.return_value = {
            "channel_id": "C1",
            "questions": ["Q1", "Q2", "Q3"],
            "id": 7,
            "name": "Pulse TechOps Pilot",
        }
        db_mock.get_standup_by_id.return_value = {
            "yesterday": "ayer",
            "today": "hoy",
            "blockers": "bloqueo",
        }
        body = {
            "user": {"id": "U1", "team_id": "T1"},
            "team": {"id": "T1"},
            "trigger_id": "tr-2",
            "actions": [{"value": "42"}],
        }
        started = {}
        real_start = state.state_store.start

        def fake_start(cache_key, channel, **kwargs):
            started["kwargs"] = kwargs
            return real_start(cache_key, channel, **kwargs)

        with (
            patch.dict(sys.modules, {"db": db_mock}),
            patch.object(handlers, "can_edit_response", return_value=True),
            patch.object(handlers.state_store, "start", side_effect=fake_start),
            patch.object(handlers, "_send_question_block") as send_question,
        ):
            _action_handler("standup_edit")(ack=MagicMock(), body=body, say=MagicMock(), client=client)

        assert started["kwargs"]["editing_standup_id"] == 42
        send_question.assert_not_called()
        view = client.views_open.call_args.kwargs["view"]
        assert view["private_metadata"] == "T1:U1"
        assert [b["label"]["text"] for b in view["blocks"]] == ["Q1", "Q2", "Q3"]
        assert view["blocks"][0]["element"]["initial_value"]

    def test_edit_submission_updates_instead_of_duplicating(self):
        import handlers

        client = MagicMock()
        db_mock = MagicMock()
        session = state.UserSession(
            cache_key="T1:U1",
            team_id="T1",
            channel="C1",
            questions=["Q1", "Q2", "Q3"],
            answers=["ayer editado", "hoy", "sin bloqueos"],
            editing_standup_id=42,
        )
        with patch.dict(sys.modules, {"db": db_mock}):
            handlers._complete_standup("U1", session, client)

        db_mock.update_standup.assert_called_once_with(
            user_id="U1",
            team_id="T1",
            yesterday="ayer editado",
            today="hoy",
            blockers="sin bloqueos",
        )
        db_mock.save_standup.assert_not_called()

    def _edit_session(self) -> "state.UserSession":
        return state.UserSession(
            cache_key="T1:U1",
            team_id="T1",
            channel="C1",
            questions=["Q1", "Q2", "Q3"],
            answers=["ayer editado", "hoy", "sin bloqueos"],
            editing_standup_id=42,
        )

    def test_edit_updates_the_original_channel_message(self):
        import handlers

        client = MagicMock()
        db_mock = MagicMock()
        db_mock.get_standup_by_id.return_value = {
            "message_channel": "C1",
            "message_ts": "111.222",
        }
        with patch.dict(sys.modules, {"db": db_mock}):
            handlers._complete_standup("U1", self._edit_session(), client)

        update = client.chat_update.call_args.kwargs
        assert update["channel"] == "C1"
        assert update["ts"] == "111.222"
        assert "ayer editado" in update["text"]
        channels_posted = [
            (c.kwargs.get("channel") or (c.args[0].get("channel") if c.args and isinstance(c.args[0], dict) else None))
            for c in client.chat_postMessage.call_args_list
        ]
        assert "C1" not in channels_posted  # no duplicate in the channel

    def test_edit_falls_back_to_thread_reply_without_stored_ts(self):
        import handlers

        client = MagicMock()
        db_mock = MagicMock()
        db_mock.get_standup_by_id.return_value = {}
        db_mock.get_daily_thread_ts.return_value = "999.888"
        with patch.dict(sys.modules, {"db": db_mock}):
            handlers._complete_standup("U1", self._edit_session(), client)

        client.chat_update.assert_not_called()
        thread_reply = next(c for c in client.chat_postMessage.call_args_list if c.kwargs.get("thread_ts") == "999.888")
        assert "✏️" in thread_reply.kwargs["text"]

    def test_edit_falls_back_to_thread_reply_when_update_fails(self):
        import handlers

        client = MagicMock()
        client.chat_update.side_effect = RuntimeError("msg_not_found")
        db_mock = MagicMock()
        db_mock.get_standup_by_id.return_value = {
            "message_channel": "C1",
            "message_ts": "111.222",
        }
        db_mock.get_daily_thread_ts.return_value = "999.888"
        with patch.dict(sys.modules, {"db": db_mock}):
            handlers._complete_standup("U1", self._edit_session(), client)

        thread_reply = next(c for c in client.chat_postMessage.call_args_list if c.kwargs.get("thread_ts") == "999.888")
        assert "✏️" in thread_reply.kwargs["text"]

    def test_blocker_escalation_is_appended_after_the_update(self):
        import handlers

        client = MagicMock()
        client.chat_postMessage.return_value = {"ts": "555.666"}
        db_mock = MagicMock()
        db_mock.save_standup.return_value = 42
        db_mock.get_standup_schedule_for_channel.return_value = {
            "channel_id": "C1",
            "notify_on_report": True,
            "missing_mention": "UMANAGER",
        }
        session = state.UserSession(
            cache_key="T1:U1",
            team_id="T1",
            channel="C1",
            questions=["Ayer", "Hoy", "¿Tienes algún bloqueo?"],
            answers=["avance", "tarea", "Esperando acceso"],
        )
        with patch.dict(sys.modules, {"db": db_mock}):
            handlers._complete_standup("U1", session, client)

        update = next(c.kwargs["text"] for c in client.chat_postMessage.call_args_list if c.kwargs.get("thread_ts"))
        escalation = "<@UMANAGER> — bloqueo reportado por <@U1>"
        assert update.endswith(escalation)
        assert update.index("Esperando acceso") < update.index(escalation)

    def test_first_post_records_its_message_ts(self):
        import handlers

        client = MagicMock()
        client.chat_postMessage.return_value = {"ts": "555.666"}
        db_mock = MagicMock()
        db_mock.save_standup.return_value = 42
        db_mock.get_standup_schedule_for_channel.return_value = {
            "channel_id": "C1",
            "notify_on_report": True,
        }
        session = state.UserSession(
            cache_key="T1:U1",
            team_id="T1",
            channel="C1",
            questions=["Q1", "Q2", "Q3"],
            answers=["ayer", "hoy", "sin bloqueos"],
        )
        with patch.dict(sys.modules, {"db": db_mock}):
            handlers._complete_standup("U1", session, client)

        db_mock.set_standup_message.assert_called_once_with("T1", 42, "C1", "555.666")


# ---------------------------------------------------------------------------
# _send_question_block
# ---------------------------------------------------------------------------


class TestSendQuestionBlock:
    def test_calls_chat_post_message_with_blocks(self):
        client = MagicMock()
        from handlers import _send_question_block

        _send_question_block(client, "U1", "What did you do yesterday?", 0)

        client.chat_postMessage.assert_called_once()
        call_kwargs = client.chat_postMessage.call_args.kwargs
        assert call_kwargs["channel"] == "U1"
        assert "blocks" in call_kwargs
        blocks = call_kwargs["blocks"]
        assert any(b.get("block_id") == "answer_0" for b in blocks)

    def test_block_id_uses_step_number(self):
        client = MagicMock()
        from handlers import _send_question_block

        _send_question_block(client, "U2", "What are blockers?", 2)
        call_kwargs = client.chat_postMessage.call_args.kwargs
        blocks = call_kwargs["blocks"]
        assert any(b.get("block_id") == "answer_2" for b in blocks)


# ---------------------------------------------------------------------------
# _start_standup_session
# ---------------------------------------------------------------------------


class TestStartStandupSession:
    def test_already_active_clears_and_starts_fresh(self):
        """If a session is already active, clear it and start a fresh one.

        Previously the handler printed 'You already have an active standup
        session' and bailed — leaving users stuck when a scheduled session
        was never completed or when they belong to multiple schedules.
        """
        client = MagicMock()
        db_mock = MagicMock()
        db_mock.get_schedule_for_user.return_value = None
        db_mock.get_workspace_config.return_value = {"channel_id": "C1", "questions": ["Q1", "Q2", "Q3"]}

        fake_session = state.UserSession(
            cache_key="T1:U1",
            team_id="T1",
            channel="C1",
            questions=["Q1", "Q2", "Q3"],
        )

        with patch.dict(sys.modules, {"db": db_mock}):
            with patch.object(state.state_store, "is_active", return_value=True):
                with patch.object(state.state_store, "clear") as mock_clear:
                    with patch.object(state.state_store, "start", return_value=fake_session):
                        from handlers import _start_standup_session

                        _start_standup_session("U1", "T1", client)

                    mock_clear.assert_called_once_with("T1:U1")

        texts = [c.kwargs.get("text", "") for c in client.chat_postMessage.call_args_list]
        assert not any("already" in t.lower() for t in texts)
        assert any("standup" in t.lower() for t in texts)

    def test_new_session_sends_starting_message(self):
        _ss_mock.has_session.return_value = False
        _ss_mock.get_session.return_value = None
        client = MagicMock()
        db_mock = MagicMock()
        db_mock.get_workspace_config.return_value = {"channel_id": "C1", "questions": ["Q1", "Q2", "Q3"]}

        # Patch state_store.start to return a real UserSession
        fake_session = state.UserSession(
            cache_key="T1:U1",
            team_id="T1",
            channel="C1",
            questions=["Q1", "Q2", "Q3"],
        )

        with patch.dict(sys.modules, {"db": db_mock}):
            with patch.object(state.state_store, "start", return_value=fake_session):
                with patch.object(state.state_store, "is_active", return_value=False):
                    from handlers import _start_standup_session

                    _start_standup_session("U1", "T1", client)

        # Should post the standup-time DM (with Fill in form button)
        texts = [c.kwargs.get("text", "") for c in client.chat_postMessage.call_args_list]
        assert any("standup" in t.lower() for t in texts)


# ---------------------------------------------------------------------------
# Incoming DM dispatch
# ---------------------------------------------------------------------------


class TestIncomingDMDispatch:
    def test_manual_standup_starts_a_live_session_when_none_exists(self):
        """The generic message listener owns manual DM dispatch in Bolt."""
        import handlers

        client = MagicMock()
        logger = MagicMock()
        event = {"channel_type": "im", "user": "U1", "team": "T1", "text": "standup"}
        with (
            patch.object(handlers.state_store, "get", return_value=None),
            patch.object(handlers, "_start_standup_session") as start,
        ):
            handlers._handle_dm_message(event, client, logger)

        start.assert_called_once_with("U1", "T1", client)

    def test_real_slack_event_body_supplies_workspace_for_manual_standup(self):
        import handlers

        client = MagicMock()
        event = {"channel_type": "im", "user": "U1", "text": "standup"}
        body = {"team_id": "T1", "event": event, "type": "event_callback"}
        with (
            patch.object(handlers.state_store, "get", return_value=None),
            patch.object(handlers, "_start_standup_session") as start,
        ):
            handlers._handle_slack_dm_event(event, body, client, MagicMock())

        start.assert_called_once_with("U1", "T1", client)

    def test_active_session_text_redirects_to_the_single_form_without_recording(self):
        import handlers

        client = MagicMock()
        logger = MagicMock()
        active = MagicMock()
        event = {"channel_type": "im", "user": "U1", "team": "T1", "text": "answer"}
        with (
            patch.object(handlers.state_store, "get", return_value=active),
            patch.object(handlers.state_store, "record_answer") as record_answer,
            patch.object(handlers, "_start_standup_session") as start,
        ):
            handlers._handle_dm_message(event, client, logger)

        record_answer.assert_not_called()
        client.chat_postMessage.assert_called_once()
        assert "Completar update" in client.chat_postMessage.call_args.kwargs["text"]
        start.assert_not_called()

    def test_non_dm_message_is_ignored(self):
        import handlers

        with patch.object(handlers, "_start_standup_session") as start:
            handlers._handle_dm_message({"channel_type": "channel", "text": "standup"}, MagicMock(), MagicMock())

        start.assert_not_called()


# ---------------------------------------------------------------------------
# fire_webhooks
# ---------------------------------------------------------------------------


class TestFireWebhooks:
    def test_posts_to_registered_hooks(self):
        import handlers

        db_mock = MagicMock()
        db_mock.get_webhooks.return_value = [
            {"webhook_url": "https://hooks.example.com/standup", "events": ["standup.completed"], "secret": None}
        ]
        requests_mock = MagicMock()
        requests_mock.post.return_value = MagicMock(status_code=200)

        with patch.dict(sys.modules, {"db": db_mock}):
            with patch.object(handlers, "requests", requests_mock):
                handlers.fire_webhooks("T1", "standup.completed", {"user": "U1"})

        requests_mock.post.assert_called_once()
        call_kwargs = requests_mock.post.call_args.kwargs
        assert call_kwargs["headers"]["X-Morgenruf-Event"] == "standup.completed"

    def test_skips_hooks_for_different_event(self):
        import handlers

        db_mock = MagicMock()
        db_mock.get_webhooks.return_value = [
            {"webhook_url": "https://hooks.example.com/other", "events": ["member.joined"], "secret": None}
        ]
        requests_mock = MagicMock()

        with patch.dict(sys.modules, {"db": db_mock}):
            with patch.object(handlers, "requests", requests_mock):
                handlers.fire_webhooks("T1", "standup.completed", {"user": "U1"})

        requests_mock.post.assert_not_called()

    def test_no_webhooks_no_requests(self):
        import handlers

        db_mock = MagicMock()
        db_mock.get_webhooks.return_value = []
        requests_mock = MagicMock()

        with patch.dict(sys.modules, {"db": db_mock}):
            with patch.object(handlers, "requests", requests_mock):
                handlers.fire_webhooks("T1", "standup.completed", {})

        requests_mock.post.assert_not_called()

    def test_request_failure_does_not_raise(self):
        import handlers

        db_mock = MagicMock()
        db_mock.get_webhooks.return_value = [
            {"webhook_url": "https://hooks.example.com/standup", "events": ["standup.completed"], "secret": None}
        ]
        requests_mock = MagicMock()
        requests_mock.post.side_effect = Exception("Connection error")

        with patch.dict(sys.modules, {"db": db_mock}):
            with patch.object(handlers, "requests", requests_mock):
                handlers.fire_webhooks("T1", "standup.completed", {})  # should not raise

    def test_adds_hmac_signature_when_secret_set(self):
        import handlers

        db_mock = MagicMock()
        db_mock.get_webhooks.return_value = [
            {
                "webhook_url": "https://hooks.example.com/secret",
                "events": ["standup.completed"],
                "secret": "mysecret",
            }
        ]
        requests_mock = MagicMock()
        requests_mock.post.return_value = MagicMock(status_code=200)

        with patch.dict(sys.modules, {"db": db_mock}):
            with patch.object(handlers, "requests", requests_mock):
                handlers.fire_webhooks("T1", "standup.completed", {"user": "U1"})

        headers = requests_mock.post.call_args.kwargs["headers"]
        assert "X-Morgenruf-Signature" in headers
        assert headers["X-Morgenruf-Signature"].startswith("sha256=")


# ---------------------------------------------------------------------------
# can_edit_response
# ---------------------------------------------------------------------------


class TestCanEditResponse:
    def _standup(self, user_id="U1", team_id="T1", hours_ago=1):
        from datetime import timedelta

        return {
            "user_id": user_id,
            "team_id": team_id,
            "submitted_at": datetime.now(tz=timezone.utc) - timedelta(hours=hours_ago),
        }

    def test_within_window_returns_true(self):
        db_mock = MagicMock()
        db_mock.get_standup_by_id.return_value = self._standup(hours_ago=1)
        db_mock.get_workspace_config.return_value = {"edit_window_hours": 4}

        with patch.dict(sys.modules, {"db": db_mock}):
            from handlers import can_edit_response

            assert can_edit_response("T1", "U1", 1) is True

    def test_outside_window_returns_false(self):
        db_mock = MagicMock()
        db_mock.get_standup_by_id.return_value = self._standup(hours_ago=5)
        db_mock.get_workspace_config.return_value = {"edit_window_hours": 4}

        with patch.dict(sys.modules, {"db": db_mock}):
            from handlers import can_edit_response

            assert can_edit_response("T1", "U1", 1) is False

    def test_standup_not_found_returns_false(self):
        db_mock = MagicMock()
        db_mock.get_standup_by_id.return_value = None

        with patch.dict(sys.modules, {"db": db_mock}):
            from handlers import can_edit_response

            assert can_edit_response("T1", "U1", 999) is False

    def test_wrong_user_returns_false(self):
        db_mock = MagicMock()
        db_mock.get_standup_by_id.return_value = self._standup(user_id="U2")
        db_mock.get_workspace_config.return_value = {"edit_window_hours": 4}

        with patch.dict(sys.modules, {"db": db_mock}):
            from handlers import can_edit_response

            assert can_edit_response("T1", "U1", 1) is False

    def test_none_edit_window_returns_true(self):
        db_mock = MagicMock()
        db_mock.get_standup_by_id.return_value = self._standup(hours_ago=100)
        db_mock.get_workspace_config.return_value = {"edit_window_hours": None}

        with patch.dict(sys.modules, {"db": db_mock}):
            from handlers import can_edit_response

            assert can_edit_response("T1", "U1", 1) is True

    def test_zero_edit_window_returns_true(self):
        db_mock = MagicMock()
        db_mock.get_standup_by_id.return_value = self._standup(hours_ago=100)
        db_mock.get_workspace_config.return_value = {"edit_window_hours": 0}

        with patch.dict(sys.modules, {"db": db_mock}):
            from handlers import can_edit_response

            assert can_edit_response("T1", "U1", 1) is True

    def test_db_exception_returns_false(self):
        db_mock = MagicMock()
        db_mock.get_standup_by_id.side_effect = Exception("DB down")

        with patch.dict(sys.modules, {"db": db_mock}):
            from handlers import can_edit_response

            assert can_edit_response("T1", "U1", 1) is False
