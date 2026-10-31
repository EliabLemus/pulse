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
import logging
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


class TestWeekdayClampKeepsSupportedDayForms:
    """The clamp goes through db.parse_schedule_days, so every day form the
    app documents must survive it. The regression: token-splitting on commas
    turned "mon-fri", "*" and "0-4" into an empty day list, CronTrigger then
    raised on day_of_week="", and _register_schedule_safely silently skipped
    the whole schedule.
    """

    def test_the_canonical_parser_survives_the_clamp(self):
        from src.core.db import parse_schedule_days  # noqa: PLC0415 - real parser, deliberately

        cases = {
            "mon-fri": {"mon", "tue", "wed", "thu", "fri"},
            "*": {"mon", "tue", "wed", "thu", "fri"},
            "0-4": {"mon", "tue", "wed", "thu", "fri"},
            "1,3,5": {"tue", "thu"},  # 5 = sat is clamped away
            "mon,sat": {"mon"},
            "fri-mon": {"mon", "fri"},  # wraps sat/sun, both clamped
            "mon,tue,wed,thu,fri": {"mon", "tue", "wed", "thu", "fri"},
            "": {"mon", "tue", "wed", "thu", "fri"},  # parser default
        }
        for spec, expected in cases.items():
            clamped = sched_mod._enforce_weekday_days(spec)
            assert clamped is not None, spec
            names = {name for name in clamped.split(",")}
            assert names == expected, (spec, clamped)
            # The clamped value is exactly what parse_schedule_days resolved:
            # no day invented or dropped beyond the weekend clamp itself.
            assert names == {sched_mod._WEEKDAY_NAMES[d] for d in parse_schedule_days(spec) if d <= 4}, spec

    def test_a_weekend_only_schedule_registers_nothing(self, caplog):
        """sat/sun has no weekday left, so the schedule is deliberately not
        registered — with a clear log, never a CronTrigger crash."""
        scheduler = BackgroundScheduler()
        db = MagicMock()
        db.get_installation.return_value = None
        with patch_modules({"src.core.db": db}), caplog.at_level(logging.ERROR):
            sched_mod.register_schedule_job(
                scheduler,
                self._row(schedule_days="sat,sun"),
            )
        assert scheduler.get_jobs() == []
        assert any("weekend silence" in rec.message for rec in caplog.records)

    def test_ranges_that_cross_the_weekend_clamp_to_their_weekdays(self):
        for spec in ("fri-mon", "sat-wed", "sun-fri", "0-6", "*"):
            for job in self._registered_jobs(schedule_days=spec):
                days = _job_days(job)
                assert days.isdisjoint(_WEEKEND), f"{job.id} can fire on {days & _WEEKEND} (from {spec!r})"

    def test_every_outgoing_job_kind_is_registered_for_a_range_form(self):
        """A weekday-bearing range ("mon-fri") must produce the full job set —
        standup, reminder, report and window close — not just survive."""
        jobs = self._registered_jobs(schedule_days="mon-fri", reminder_minutes=15)
        ids = {job.id for job in jobs}
        assert "schedule_T1_1" in ids
        assert "reminder_schedule_T1_1" in ids
        assert "report_schedule_T1_1" in ids
        assert "window_close_T1_1" in ids
        assert "pending_reminder_T1_1_0945" in ids
        for job in jobs:
            days = _job_days(job)
            assert days.isdisjoint(_WEEKEND), f"{job.id} can fire on {days & _WEEKEND}"

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _row(**overrides):
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
            "pending_reminder_times": "09:45",
            "window_end": "11:00",
            "weekend_reminder": False,
            "report_time": None,
            "active": True,
        }
        row.update(overrides)
        return row

    def _registered_jobs(self, **overrides):
        scheduler = BackgroundScheduler()
        db = MagicMock()
        db.get_installation.return_value = None
        with patch_modules({"src.core.db": db}):
            sched_mod.register_schedule_job(scheduler, self._row(**overrides))
        return scheduler.get_jobs()
