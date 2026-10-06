from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock


@contextmanager
def _db_conn(cursor):
    conn = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    yield conn


def test_replace_compass_task_snapshots_upserts_every_email_in_one_transaction(monkeypatch):
    import src.core.db as db

    cursor = MagicMock()
    monkeypatch.setattr(db, "db_conn", lambda: _db_conn(cursor))

    db.replace_compass_task_snapshots(
        "T1",
        {
            " ELIAB.LEMUS@zubale.com ": [{"key": "TECH-8"}],
            "other@zubale.com": [],
        },
    )

    sql = cursor.executemany.call_args.args[0]
    rows = cursor.executemany.call_args.args[1]
    assert "INSERT INTO compass_task_snapshots" in sql
    assert "ON CONFLICT (team_id, email) DO UPDATE" in sql
    assert rows[0][0:2] == ("T1", "eliab.lemus@zubale.com")
    assert rows[1][0:2] == ("T1", "other@zubale.com")


def test_fresh_compass_task_snapshots_uses_database_now_and_normalized_emails(monkeypatch):
    import src.core.db as db

    cursor = MagicMock()
    cursor.fetchall.return_value = [
        {"email": "eliab.lemus@zubale.com", "tasks": [{"key": "TECH-8"}]},
        {"email": "other@zubale.com", "tasks": [{"key": "TECH-9"}, {"key": "TECH-10"}]},
    ]
    monkeypatch.setattr(db, "db_conn", lambda: _db_conn(cursor))

    result = db.get_fresh_compass_task_snapshots(
        "T1",
        [" ELIAB.LEMUS@zubale.com ", "other@zubale.com", "not-an-email"],
        max_age_minutes=30,
        max_tasks_per_email=1,
    )

    sql = cursor.execute.call_args.args[0]
    params = cursor.execute.call_args.args[1]
    assert "NOW() - (%s * INTERVAL '1 minute')" in sql
    assert params == ("T1", ["eliab.lemus@zubale.com", "other@zubale.com"], 30)
    assert result == {
        "eliab.lemus@zubale.com": [{"key": "TECH-8"}],
        "other@zubale.com": [{"key": "TECH-9"}],
    }
