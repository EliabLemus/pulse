#!/usr/bin/env python3
"""Idempotently seed the single-user Pulse TechOps pilot into PostgreSQL.

This script intentionally uses only environment variables and PostgreSQL. It
never calls Slack and never prints credentials. Run it through the Compose
``seed`` profile after migrations finish.
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from typing import Any

SCHEDULE_NAME = "Compass DSU"
QUESTIONS = [
    "¿Qué lograste avanzar o completar ayer?",
    "¿Cuál es tu tarea principal para hoy?",
    "¿Tienes algún bloqueo que te impida avanzar hoy?",
]
_REQUIRED = (
    "DATABASE_URL",
    "SLACK_BOT_TOKEN",
    "PULSE_TEAM_ID",
    "PULSE_TEAM_NAME",
    "PULSE_BOT_USER_ID",
    "PULSE_APP_ID",
    "PULSE_PARTICIPANT_ID",
    "PULSE_CHANNEL_ID",
    "PULSE_MANAGER_ID",
)
_ID_PATTERNS = {
    "PULSE_TEAM_ID": re.compile(r"^T[A-Z0-9]+$"),
    "PULSE_BOT_USER_ID": re.compile(r"^U[A-Z0-9]+$"),
    "PULSE_APP_ID": re.compile(r"^A[A-Z0-9]+$"),
    "PULSE_PARTICIPANT_ID": re.compile(r"^U[A-Z0-9]+$"),
    "PULSE_CHANNEL_ID": re.compile(r"^[CG][A-Z0-9]+$"),
    "PULSE_MANAGER_ID": re.compile(r"^U[A-Z0-9]+$"),
}


def validate(env: Mapping[str, str]) -> list[str]:
    """Return safe field names for missing or malformed configuration."""
    errors = [name for name in _REQUIRED if not env.get(name, "").strip()]
    token = env.get("SLACK_BOT_TOKEN", "").strip()
    if token and not token.startswith("xoxb-"):
        errors.append("SLACK_BOT_TOKEN")
    for name, pattern in _ID_PATTERNS.items():
        value = env.get(name, "").strip()
        if value and not pattern.fullmatch(value):
            errors.append(name)
    return sorted(set(errors))


def _seed(cursor: Any, env: Mapping[str, str]) -> None:
    team_id = env["PULSE_TEAM_ID"].strip()
    participant_id = env["PULSE_PARTICIPANT_ID"].strip()
    schedule_values = (
        team_id,
        SCHEDULE_NAME,
        "09:15",
        "America/Guatemala",
        "mon,tue,wed,thu,fri",
        json.dumps(QUESTIONS),
        [participant_id],
        env["PULSE_CHANNEL_ID"].strip(),
        "09:45,10:15,10:45",
        "11:00",
        env["PULSE_MANAGER_ID"].strip(),
    )

    cursor.execute(
        """
        INSERT INTO installations (team_id, team_name, bot_token, bot_user_id, app_id, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (team_id) DO UPDATE SET
            team_name = EXCLUDED.team_name,
            bot_token = EXCLUDED.bot_token,
            bot_user_id = EXCLUDED.bot_user_id,
            app_id = EXCLUDED.app_id,
            updated_at = NOW()
        """,
        (
            team_id,
            env["PULSE_TEAM_NAME"].strip(),
            env["SLACK_BOT_TOKEN"].strip(),
            env["PULSE_BOT_USER_ID"].strip(),
            env["PULSE_APP_ID"].strip(),
        ),
    )
    cursor.execute(
        """
        INSERT INTO members (team_id, user_id, real_name, active)
        VALUES (%s, %s, %s, TRUE)
        ON CONFLICT (team_id, user_id) DO UPDATE SET
            real_name = EXCLUDED.real_name,
            active = TRUE
        """,
        (team_id, participant_id, env.get("PULSE_PARTICIPANT_NAME", "Eliab").strip() or "Eliab"),
    )
    cursor.execute(
        "SELECT id FROM standup_schedules WHERE team_id = %s AND name = %s FOR UPDATE",
        (team_id, SCHEDULE_NAME),
    )
    existing = cursor.fetchone()
    if existing:
        cursor.execute(
            """
            UPDATE standup_schedules
            SET schedule_time = %s, schedule_tz = %s, schedule_days = %s,
                questions = %s::jsonb,
                active = TRUE,
                pending_reminder_times = %s, window_end = %s, missing_mention = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (
                schedule_values[2],  # schedule_time
                schedule_values[3],  # schedule_tz
                schedule_values[4],  # schedule_days
                schedule_values[5],  # questions
                schedule_values[8],  # pending_reminder_times
                schedule_values[9],  # window_end
                schedule_values[10],  # missing_mention
                existing["id"] if isinstance(existing, dict) else existing[0],
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO standup_schedules (
                team_id, name, schedule_time, schedule_tz, schedule_days, questions,
                participants, channel_id, reminder_minutes, active, post_to_thread,
                notify_on_report, post_summary, pending_reminder_times, window_end, missing_mention,
                updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s::jsonb, %s, %s, 0, TRUE, TRUE, TRUE, TRUE,
                %s, %s, %s, NOW()
            )
            RETURNING id
            """,
            schedule_values,
        )
        cursor.fetchone()


def main(
    env: Mapping[str, str] | None = None,
    connect: Callable[[str], Any] | None = None,
) -> int:
    env = env if env is not None else os.environ
    errors = validate(env)
    if errors:
        print("[seed] invalid or missing configuration: " + ", ".join(errors), file=sys.stderr)
        return 2

    if connect is None:
        import psycopg2

        connect = psycopg2.connect

    try:
        connection = connect(env["DATABASE_URL"])
        with connection:
            with connection.cursor() as cursor:
                _seed(cursor, env)
        connection.close()
    except Exception as exc:  # noqa: BLE001
        print(f"[seed] database operation failed: {type(exc).__name__}", file=sys.stderr)
        return 1

    print("[seed] TechOps pilot installation and schedule are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
