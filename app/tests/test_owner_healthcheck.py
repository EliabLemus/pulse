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

    def test_the_module_registers_its_builder_on_core_seam(self):
        """Standup's wiring attaches its builder to core's seam, so core
        registers the job without ever importing the module. Other test
        modules reload src.core.scheduler at collection time, which resets
        module globals, so the wiring is exercised directly here."""
        import src.core.scheduler as sched_mod
        from src.modules.standup import configure_owner_health_check
        from src.modules.standup.owner_healthcheck import register_owner_health_check

        previous = sched_mod._owner_health_check_builder
        try:
            sched_mod._owner_health_check_builder = None
            configure_owner_health_check()
            assert sched_mod._owner_health_check_builder is register_owner_health_check
        finally:
            sched_mod._owner_health_check_builder = previous

    def test_schedule_registration_uses_the_injected_builder(self):
        """register_schedule_job delegates to the seam: with a builder present
        the health-check job is added, and a raising builder only logs."""
        import src.core.scheduler as sched_mod

        scheduler = MagicMock()
        calls = []

        def builder(sched, team_id, bot_token, tz_name):
            calls.append((team_id, tz_name))

        previous = sched_mod._owner_health_check_builder
        try:
            sched_mod._owner_health_check_builder = builder
            sched_mod.register_schedule_job(
                scheduler,
                {
                    "team_id": "T1",
                    "bot_token": "xoxb-test",
                    "id": 1,
                    "schedule_time": "09:00",
                    "schedule_tz": "America/Guatemala",
                    "schedule_days": "mon,tue,wed,thu,fri",
                    "channel_id": "C1",
                    "reminder_minutes": 0,
                },
            )
            assert calls == [("T1", "America/Guatemala")]

            def boom(sched, team_id, bot_token, tz_name):
                raise RuntimeError("no health check today")

            sched_mod._owner_health_check_builder = boom
            sched_mod.register_schedule_job(
                scheduler,
                {
                    "team_id": "T2",
                    "bot_token": "xoxb-test",
                    "id": 2,
                    "schedule_time": "09:00",
                    "schedule_tz": "UTC",
                    "schedule_days": "mon,tue,wed,thu,fri",
                    "channel_id": "C2",
                    "reminder_minutes": 0,
                },
            )
        finally:
            sched_mod._owner_health_check_builder = previous
        # The T2 standup job itself survived the builder's failure.
        assert scheduler.add_job.called
        assert any(
            "schedule_T2_2" in str(c) or c.kwargs.get("id") == "schedule_T2_2" for c in scheduler.add_job.call_args_list
        )

    def test_no_builder_means_no_health_check_and_no_error(self):
        import src.core.scheduler as sched_mod

        scheduler = MagicMock()
        previous = sched_mod._owner_health_check_builder
        try:
            sched_mod._owner_health_check_builder = None
            sched_mod.register_schedule_job(
                scheduler,
                {
                    "team_id": "T1",
                    "bot_token": "xoxb-test",
                    "id": 1,
                    "schedule_time": "09:00",
                    "schedule_tz": "UTC",
                    "schedule_days": "mon,tue,wed,thu,fri",
                    "channel_id": "C1",
                    "reminder_minutes": 0,
                },
            )
        finally:
            sched_mod._owner_health_check_builder = previous
        assert not any("owner_health_check" in str(c) for c in scheduler.add_job.call_args_list)
