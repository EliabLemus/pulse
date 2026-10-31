"""Validation for the timing fields of a standup schedule.

`scheduler.register_schedule_job` parses `schedule_time` and resolves
`schedule_tz` through pytz. When either value is unusable it logs the problem
and gives up, so the cron job is never registered while the dashboard keeps
reporting the schedule as Active (issue #67). These helpers let the API reject
such a row before it is persisted, and let any process ask why a stored row
cannot be registered.
"""

from __future__ import annotations

import re

import pytz

# 24-hour "HH:MM", the shape register_schedule_job splits on.
_TIME_RE = re.compile(r"^([01]?[0-9]|2[0-3]):([0-5][0-9])$")

# The questions a standup starts with when nobody has written their own. The
# same three as the database column default, so the Slack modal, the
# dashboard and the scheduler all agree.
DEFAULT_QUESTIONS = (
    "What did you complete yesterday?",
    "What are you working on today?",
    "Any blockers?",
)

_TZ_HINT = "Use an IANA timezone name such as Asia/Kolkata, Europe/London or America/New_York."
_TIME_HINT = "Use a 24-hour HH:MM time such as 09:30."

# The day list written by the dashboard and the database column default.
DEFAULT_SCHEDULE_DAYS = "mon,tue,wed,thu,fri"

# Every token APScheduler's day_of_week and this app accept, as weekday
# numbers with Monday 0 — the same convention CronTrigger uses.
WEEKDAY_TOKENS = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tues": 1,
    "tuesday": 1,
    "wed": 2,
    "weds": 2,
    "wednesday": 2,
    "thu": 3,
    "thur": 3,
    "thurs": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
    "0": 0,
    "1": 1,
    "2": 2,
    "3": 3,
    "4": 4,
    "5": 5,
    "6": 6,
}

WORKING_WEEK = {0, 1, 2, 3, 4}


def parse_schedule_days(spec: object) -> set[int]:
    """Return the weekday numbers a `schedule_days` value fires on (Monday is 0).

    Accepts the shapes APScheduler's `day_of_week` accepts and this app writes:
    "mon,wed,fri", "mon-fri", "fri-mon", "*" and bare numbers.

    The canonical home of this parser is here, next to the other timing-field
    rules, so the scheduler can clamp day lists without importing the database
    module; `src.core.db` re-exports it for its existing callers.
    """
    if not isinstance(spec, str) or not spec.strip():
        spec = DEFAULT_SCHEDULE_DAYS
    days: set[int] = set()
    for token in spec.lower().replace(" ", "").split(","):
        if not token:
            continue
        if token == "*":
            return set(range(7))
        if "-" in token[1:]:
            start_txt, _, end_txt = token.partition("-")
            start = WEEKDAY_TOKENS.get(start_txt)
            end = WEEKDAY_TOKENS.get(end_txt)
            if start is None or end is None:
                continue
            day = start
            days.add(day)
            while day != end:
                day = (day + 1) % 7
                days.add(day)
            continue
        day = WEEKDAY_TOKENS.get(token)
        if day is not None:
            days.add(day)
    return days or set(WORKING_WEEK)


def schedule_timezone_error(value: object) -> str | None:
    """Return why `value` is unusable as a schedule timezone, or None if it is fine."""
    if not isinstance(value, str) or not value.strip():
        return f"Timezone is required. {_TZ_HINT}"
    try:
        pytz.timezone(value.strip())
    except Exception:
        return f"'{value}' is not a valid timezone. {_TZ_HINT}"
    return None


def schedule_time_error(value: object) -> str | None:
    """Return why `value` is unusable as a schedule time, or None if it is fine."""
    if not isinstance(value, str) or not value.strip():
        return f"Time is required. {_TIME_HINT}"
    if not _TIME_RE.match(value.strip()):
        return f"'{value}' is not a valid time. {_TIME_HINT}"
    return None


def schedule_payload_error(data: dict) -> str | None:
    """Validate the timing fields present in a create/update API payload.

    Only keys the caller actually sent are checked, so a partial update stays
    a partial update. Returns the first problem found, or None.
    """
    if "schedule_tz" in data:
        error = schedule_timezone_error(data.get("schedule_tz"))
        if error:
            return error
    if "schedule_time" in data:
        error = schedule_time_error(data.get("schedule_time"))
        if error:
            return error
    return None


def schedule_config_error(schedule: dict) -> str | None:
    """Return why the scheduler will refuse to register `schedule`, or None.

    Mirrors the defaults register_schedule_job applies, so a stored row that
    passes here is a row the scheduler can turn into a cron job.
    """
    return schedule_time_error(schedule.get("schedule_time") or "09:00") or schedule_timezone_error(
        schedule.get("schedule_tz") or "UTC"
    )
