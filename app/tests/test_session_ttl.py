"""Sessions must not die on the user mid-day, and the expired notice must
offer a working escape.

Two production incidents (2026-11-02) motivated this:
1. GUIDED_WIZARD_TTL was 30 minutes: a 09:15 session expired before someone
   back from a meeting at 10:30 could answer, losing everything typed.
2. The expired notice said "Run /standup" while slash dispatch was 404ing,
   so users were locked out with no working path forward.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest import mock

from src.core.state import GUIDED_WIZARD_TTL, StateStore, UserSession


def _store_with_session(age: timedelta) -> tuple[StateStore, mock.MagicMock]:
    """A StateStore whose backing store returns a session started `age` ago."""
    session = UserSession(
        cache_key="T1:U1",
        team_id="T1",
        channel="C1",
        started_at=datetime.now(timezone.utc) - age,
        compass_tasks=[{"key": "TECH-1"}],
    )
    fake = mock.MagicMock()
    fake.get_session.return_value = {
        "cache_key": session.cache_key,
        "team_id": session.team_id,
        "channel": session.channel,
        "step": 0,
        "answers": [],
        "questions": [],
        "standup_name": "S",
        "schedule_id": None,
        "editing_standup_id": None,
        "edit_initial_answers": [],
        "compass_tasks": [{"key": "TECH-1"}],
        "wizard_step": 0,
        "wizard_answers": {},
        "guided_submission_id": None,
        "started_at": session.started_at.isoformat(),
    }
    with mock.patch("src.core.state.session_store", fake):
        store = StateStore()
    return store, fake


def test_guided_wizard_ttl_is_a_working_day():
    """20h covers open-at-09:15 answered-after-lunch, and still expires
    before the next day's standup fires."""
    assert GUIDED_WIZARD_TTL >= timedelta(hours=19)
    assert GUIDED_WIZARD_TTL < timedelta(hours=24)


def test_wizard_survives_two_hours(monkeypatch: mock) -> None:
    """A session opened at 09:15 and touched at 11:15 is NOT expired."""
    store, fake = _store_with_session(timedelta(hours=2))
    monkeypatch.setattr("src.core.state.session_store", fake)
    assert store.guided_wizard_expired("T1:U1") is False
    assert store.clear_guided_wizard_if_expired("T1:U1") is False


def test_wizard_expires_before_next_day(monkeypatch: mock) -> None:
    """A session from yesterday is expired, so stale sprint snapshots die."""
    store, fake = _store_with_session(timedelta(hours=21))
    monkeypatch.setattr("src.core.state.session_store", fake)
    assert store.guided_wizard_expired("T1:U1") is True
