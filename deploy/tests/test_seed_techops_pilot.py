"""Behavioral tests for the secret-safe TechOps pilot database seed."""
from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

MODULE_PATH = Path(__file__).parents[1] / "seed-techops-pilot.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("seed_techops_pilot", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _env(**overrides):
    values = {
        "DATABASE_URL": "postgresql://pulse:correct-horse@db:5432/pulse",
        "SLACK_BOT_TOKEN": "xoxb-test-token",
        "PULSE_TEAM_ID": "T12345678",
        "PULSE_TEAM_NAME": "TechOps",
        "PULSE_BOT_USER_ID": "U12345678",
        "PULSE_APP_ID": "A12345678",
        "PULSE_PARTICIPANT_ID": "U87654321",
        "PULSE_PARTICIPANT_NAME": "Eliab",
        "PULSE_CHANNEL_ID": "G12345678",
        "PULSE_MANAGER_ID": "U87654321",
    }
    values.update(overrides)
    return values


def test_seed_upserts_installation_member_and_one_named_schedule_without_logging_secrets(capsys):
    module = _load_module()
    cursor = MagicMock()
    cursor.fetchone.side_effect = [None, {"id": 42}]
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    connect = MagicMock(return_value=connection)

    assert module.main(env=_env(), connect=connect) == 0

    rendered_sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
    assert "INSERT INTO installations" in rendered_sql
    assert "ON CONFLICT (team_id) DO UPDATE" in rendered_sql
    assert "INSERT INTO members" in rendered_sql
    assert "ON CONFLICT (team_id, user_id) DO UPDATE" in rendered_sql
    assert "INSERT INTO standup_schedules" in rendered_sql
    assert "UPDATE standup_schedules" not in rendered_sql

    schedule_params = cursor.execute.call_args_list[-1].args[1]
    assert schedule_params[2:5] == ("09:15", "America/Guatemala", "mon,tue,wed,thu")
    assert schedule_params[8:11] == ("09:45,10:15,10:45", "11:00", "U87654321")
    assert "xoxb-test-token" not in capsys.readouterr().out


def test_seed_updates_existing_named_schedule_instead_of_creating_another():
    module = _load_module()
    cursor = MagicMock()
    cursor.fetchone.side_effect = [{"id": 42}]
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    connect = MagicMock(return_value=connection)

    assert module.main(env=_env(), connect=connect) == 0

    rendered_sql = "\n".join(call.args[0] for call in cursor.execute.call_args_list)
    assert "UPDATE standup_schedules" in rendered_sql
    assert "INSERT INTO standup_schedules" not in rendered_sql


def test_seed_rejects_missing_or_malformed_required_values_without_connecting(capsys):
    module = _load_module()
    connect = MagicMock()

    assert module.main(env=_env(PULSE_CHANNEL_ID="not-a-slack-id"), connect=connect) == 2
    assert not connect.called
    assert "not-a-slack-id" not in capsys.readouterr().out

    assert module.main(env=_env(SLACK_BOT_TOKEN=""), connect=connect) == 2
    assert not connect.called
