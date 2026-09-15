"""Regression tests for the Pulse TechOps standup window."""

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))

for _name in ("pytz", "slack_sdk"):
    if isinstance(sys.modules.get(_name), MagicMock):
        del sys.modules[_name]

_prior_session_store = sys.modules.get("session_store")
_ss_mock = MagicMock()
_ss_mock.get_session.return_value = None
_ss_mock.has_session.return_value = False
sys.modules["session_store"] = _ss_mock

_had_scheduler = "scheduler" in sys.modules
import scheduler as sched_mod  # noqa: E402

if _had_scheduler:
    sched_mod = importlib.reload(sched_mod)

if _prior_session_store is not None:
    sys.modules["session_store"] = _prior_session_store
else:
    sys.modules.pop("session_store", None)

from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402


def _schedule(**overrides):
    row = {
        "id": 7,
        "team_id": "T1",
        "bot_token": "xoxb-test",
        "name": "Pulse Daily",
        "channel_id": "C1",
        "schedule_time": "09:15",
        "schedule_tz": "America/Guatemala",
        "schedule_days": "mon,tue,wed,thu",
        "participants": ["U1", "U2", "U3"],
        "questions": ["Yesterday?", "Today?", "Any blockers?"],
        "active": True,
        "reminder_minutes": 0,
        "weekend_reminder": False,
        "report_time": "12:00",
        "pending_reminder_times": "09:45, 10:15,10:45",
        "window_end": "11:00",
        "missing_mention": "UMANAGER",
    }
    row.update(overrides)
    return row


def _db(schedule=None, submissions=None):
    db = MagicMock()
    db.get_standup_schedule.return_value = schedule or _schedule()
    db.get_standups_today_for_schedule.return_value = submissions or []
    db.is_skipped_today.side_effect = lambda _team, uid: uid == "U2"
    db.is_on_vacation.side_effect = lambda _team, uid: uid == "U3"
    db.get_installation.return_value = None
    return db


def test_pending_reminders_only_dm_users_without_a_submission():
    db = _db(submissions=[{"user_id": "U1"}])
    client = MagicMock()
    with (
        patch.dict(sys.modules, {"db": db}),
        patch.object(sched_mod, "WebClient", return_value=client),
    ):
        sched_mod.send_pending_reminders("T1", "xoxb-test", 7)

    db.get_standups_today_for_schedule.assert_called_once_with("T1", 7, "America/Guatemala")
    client.conversations_open.assert_not_called()


def test_pending_reminders_dm_only_the_remaining_participant():
    db = _db(submissions=[])
    client = MagicMock()
    db.is_skipped_today.side_effect = lambda _team, uid: uid == "U2"
    db.is_on_vacation.side_effect = lambda _team, uid: False
    with (
        patch.dict(sys.modules, {"db": db}),
        patch.object(sched_mod, "WebClient", return_value=client),
    ):
        sched_mod.send_pending_reminders("T1", "xoxb-test", 7)

    assert [call.kwargs["users"] for call in client.conversations_open.call_args_list] == ["U1", "U3"]
    texts = [call.kwargs["text"] for call in client.chat_postMessage.call_args_list]
    assert texts == [
        "Recordatorio: falta tu update para *Pulse Daily*. Responde por aquí.",
        "Recordatorio: falta tu update para *Pulse Daily*. Responde por aquí.",
    ]


def test_window_close_posts_nothing_when_everyone_is_exempt_or_submitted():
    db = _db(submissions=[{"user_id": "U1"}])
    client = MagicMock()
    with (
        patch.dict(sys.modules, {"db": db}),
        patch.object(sched_mod, "WebClient", return_value=client),
    ):
        sched_mod.close_window("T1", "xoxb-test", 7)

    client.chat_postMessage.assert_not_called()


def test_window_close_posts_each_remaining_user_to_the_schedule_channel():
    db = _db(submissions=[])
    db.is_skipped_today.side_effect = None
    db.is_skipped_today.return_value = False
    db.is_on_vacation.side_effect = None
    db.is_on_vacation.return_value = False
    client = MagicMock()
    with (
        patch.dict(sys.modules, {"db": db}),
        patch.object(sched_mod, "WebClient", return_value=client),
    ):
        sched_mod.close_window("T1", "xoxb-test", 7)

    call = client.chat_postMessage.call_args.kwargs
    assert call["channel"] == "C1"
    assert call["text"] == "Sin update: <@U1>\nSin update: <@U2>\nSin update: <@U3>"


def test_registering_the_window_jobs_uses_schedule_timezone_and_days():
    scheduler = BackgroundScheduler()
    sched_mod.register_schedule_job(scheduler, _schedule())

    assert scheduler.get_job("pending_reminder_T1_7_0945") is not None
    assert scheduler.get_job("pending_reminder_T1_7_1015") is not None
    assert scheduler.get_job("pending_reminder_T1_7_1045") is not None
    close = scheduler.get_job("window_close_T1_7")
    assert close is not None
    trigger = str(close.trigger)
    assert "hour='11'" in trigger
    assert "day_of_week='mon,tue,wed,thu'" in trigger
    assert str(close.trigger.timezone) == "America/Guatemala"


def test_reregistering_reminder_times_removes_obsolete_dynamic_job():
    scheduler = BackgroundScheduler()
    sched_mod.register_schedule_job(scheduler, _schedule(pending_reminder_times="09:45"))
    assert scheduler.get_job("pending_reminder_T1_7_0945") is not None

    sched_mod._remove_schedule_jobs(scheduler, "T1", 7)
    sched_mod.register_schedule_job(scheduler, _schedule(pending_reminder_times="10:15"))

    assert scheduler.get_job("pending_reminder_T1_7_0945") is None
    assert scheduler.get_job("pending_reminder_T1_7_1015") is not None
