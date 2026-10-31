"""Owner health-check: DM + OK button proving the Slack/Funnel round trip.

The owner's rule: a check message only he receives, whose button press comes
back through the public Funnel exactly like any other interaction, answered
with a confirmation. Guards here pin the three things that would silently
break the purpose: only the owner is messaged, the scheduled send is weekdays
only (weekend silence), and the confirmation is gated to the owner's user id.
"""

from __future__ import annotations

from unittest.mock import MagicMock, call

from src.modules.standup.owner_healthcheck import (
    CHECK_OK_ACTION_ID,
    OWNER_SLACK_USER_ID,
    owner_health_check_message,
    register_health_check_actions,
    send_owner_health_check,
)


class TestTheCheckMessage:
    def test_it_is_one_line_and_one_ok_button(self):
        msg = owner_health_check_message()
        sections = [b for b in msg["blocks"] if b["type"] == "section"]
        actions = [b for b in msg["blocks"] if b["type"] == "actions"]
        assert len(sections) == 1 and len(actions) == 1
        button = actions[0]["elements"][0]
        assert button["action_id"] == CHECK_OK_ACTION_ID
        assert button["text"]["text"] == "OK"

    def test_send_goes_only_to_the_owner(self):
        client = MagicMock()
        assert send_owner_health_check(client) is True
        assert client.chat_postMessage.call_args == call(channel=OWNER_SLACK_USER_ID, **owner_health_check_message())

    def test_send_failure_returns_false_instead_of_raising(self):
        client = MagicMock()
        client.chat_postMessage.side_effect = RuntimeError("no_connection")
        assert send_owner_health_check(client) is False

    def test_owner_id_is_the_documented_user(self):
        assert OWNER_SLACK_USER_ID == "U09GE1J7HDK"


class TestTheOkButton:
    def _wire(self):
        app = MagicMock()
        handlers = {}

        def _action(action_id):
            def _decorator(fn):
                handlers[action_id] = fn
                return fn

            return _decorator

        app.action.side_effect = _action
        register_health_check_actions(app)
        return handlers

    def test_owner_press_gets_a_confirmation(self):
        handlers = self._wire()
        client = MagicMock()
        body = {"user": {"id": OWNER_SLACK_USER_ID}}
        handlers[CHECK_OK_ACTION_ID](ack=MagicMock(), body=body, client=client)
        assert client.chat_postMessage.called
        assert "Conexión verificada" in client.chat_postMessage.call_args.kwargs["text"]

    def test_a_press_from_anyone_else_stays_silent(self):
        handlers = self._wire()
        client = MagicMock()
        body = {"user": {"id": "U-SOMEONE-ELSE"}}
        handlers[CHECK_OK_ACTION_ID](ack=MagicMock(), body=body, client=client)
        client.chat_postMessage.assert_not_called()


class TestSchedulerRegistration:
    def test_the_daily_job_is_weekdays_only(self):
        from apscheduler.triggers.cron import CronTrigger
        from src.modules.standup.owner_healthcheck import register_owner_health_check

        scheduler = MagicMock()
        register_owner_health_check(scheduler, "T1", "xoxb-test", "America/Guatemala")
        kwargs = scheduler.add_job.call_args.kwargs
        trigger = kwargs["trigger"]
        assert isinstance(trigger, CronTrigger)
        days = next(str(f) for f in trigger.fields if getattr(f, "name", "") == "day_of_week")
        assert "sat" not in days and "sun" not in days
        assert kwargs["id"] == "owner_health_check_T1"
