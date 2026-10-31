"""Weekend silence is an owner-level product rule (2026-09-23):

Pulse must register NO outgoing message job on Saturday or Sunday for anyone —
no DMs, no reminders, no window-close posts, no reports, no digests. The only
calendar the bot talks to is its APScheduler triggers, so pinning every
registered job's `day_of_week` to weekdays here is the regression guard: if a
future job type is registered with a weekend day (the Sunday weekly digest was
exactly that before this rule), this module fails before it ships.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

from tests.support import patch_modules

# Earlier test modules leave MagicMock stubs in sys.modules (test_handlers stubs
# pytz, test_dashboard stubs slack_sdk). The scheduler needs the real pytz for
# CronTrigger timezones, so drop leaked stubs before importing it.
for _name in ("pytz", "slack_sdk"):
    if isinstance(sys.modules.get(_name), MagicMock):
        del sys.modules[_name]

# Stub session_store before importing state (state.py imports it at module level).
_prior_session_store = sys.modules.get("src.core.session_store")
_ss_mock = MagicMock()
_ss_mock.get_session.return_value = None
_ss_mock.has_session.return_value = False
sys.modules["src.core.session_store"] = _ss_mock

_had_scheduler = "src.core.scheduler" in sys.modules
import src.core.scheduler as sched_mod  # noqa: E402

if _had_scheduler:
    sched_mod = importlib.reload(sched_mod)

if _prior_session_store is not None:
    sys.modules["src.core.session_store"] = _prior_session_store
else:
    sys.modules.pop("src.core.session_store", None)

from apscheduler.schedulers.background import BackgroundScheduler  # noqa: E402

_WEEKEND = {"sat", "sun"}


def _job_days(job) -> set[str]:
    """The weekday names a job's trigger can fire on."""
    field = next((f for f in job.trigger.fields if getattr(f, "name", "") == "day_of_week"), None)
    assert field is not None, f"job {job.id} has no day_of_week field"
    return {str(expr).strip().lower() for expr in field.expressions}


class TestNoWeekendJobs:
    """register_schedule_job is the only path that creates outgoing jobs."""

    def _registered_jobs(self, **overrides):
        row = {
            "id": 1,
            "team_id": "T1",
            "bot_token": "xoxb-test",
            "name": "Compass DSU",
            "channel_id": "C1",
            "schedule_time": "09:15",
            "schedule_tz": "America/Guatemala",
            "schedule_days": "mon,tue,wed,thu,fri",
            "questions": [],
            "participants": ["U1", "U2"],
            "reminder_minutes": 0,
            "pending_reminder_times": "09:45,10:15,10:45",
            "window_end": "11:00",
            "weekend_reminder": False,
            "report_time": None,
            "active": True,
        }
        row.update(overrides)
        scheduler = BackgroundScheduler()
        # The owner health-check import inside register_schedule_job touches
        # src.* lazily; keep it from hitting real dependencies during the scan.
        db = MagicMock()
        db.get_installation.return_value = None
        with patch_modules({"src.core.db": db}):
            sched_mod.register_schedule_job(scheduler, row)
        return scheduler.get_jobs()

    def test_every_job_for_a_weekday_schedule_fires_on_weekdays_only(self):
        for job in self._registered_jobs():
            days = _job_days(job)
            assert days.isdisjoint(_WEEKEND), f"{job.id} can fire on {days & _WEEKEND}"

    def test_the_full_production_shape_is_weekdays_only(self):
        jobs = self._registered_jobs()
        kinds = {job.id.split("_")[0] for job in jobs}
        assert {"schedule", "pending", "window", "report"} <= kinds, kinds
        for job in jobs:
            days = _job_days(job)
            assert days.isdisjoint(_WEEKEND), f"{job.id} can fire on {days & _WEEKEND}"

    def test_the_weekend_reminder_flag_cannot_create_a_weekend_job(self):
        """The 'weekend reminder' posts on Friday evening — a weekday — never
        on Saturday or Sunday, even when the owner turns the flag on."""
        for job in self._registered_jobs(weekend_reminder=True, reminder_minutes=-1):
            days = _job_days(job)
            assert days.isdisjoint(_WEEKEND), f"{job.id} can fire on {days & _WEEKEND}"

    def test_a_schedule_day_list_cannot_introduce_a_weekend_job(self):
        """Even a misconfigured sat/sun day list must yield zero jobs that can
        fire on a weekend: silence wins over configuration."""
        for job in self._registered_jobs(schedule_days="mon,sat"):
            days = _job_days(job)
            assert days.isdisjoint(_WEEKEND), f"{job.id} can fire on {days & _WEEKEND}"
