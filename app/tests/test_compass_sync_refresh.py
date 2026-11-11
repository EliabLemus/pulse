"""Synchronous Compass snapshot refresh on standup start.

Contract:
- refresh_snapshots_now is fail-open: missing key or any exception returns
  False without raising;
- _start_standup_session triggers the synchronous refresh BEFORE reading the
  Postgres snapshot, only when an email and COMPASS_API_KEY are present;
- COMPASS_SYNC_REFRESH=0 disables it;
- every seam (Slack, DB, state store, blocks) is monkeypatched.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import src.modules.standup.context_worker as context_worker
import src.modules.standup.handlers as handlers
from src.modules.standup.context_worker import refresh_snapshots_now

# ---------------------------------------------------------------- unit tests


def test_missing_api_key_returns_false_without_raising(monkeypatch):
    monkeypatch.delenv("COMPASS_API_KEY", raising=False)
    called = []

    monkeypatch.setattr(
        context_worker,
        "refresh_compass_task_snapshots",
        lambda *a, **kw: called.append(kw) or (_ for _ in ()).throw(AssertionError("must not be called")),
    )

    assert refresh_snapshots_now("T1") is False
    assert called == []


def test_success_calls_refresh_with_right_args(monkeypatch):
    monkeypatch.setenv("COMPASS_API_KEY", "cmp_test")
    monkeypatch.setenv("COMPASS_TEAM", "techops")
    calls = []

    def fake_refresh(api_key, team_id, *, compass_team):
        calls.append((api_key, team_id, compass_team))
        return {"members": 1, "snapshots": 1}

    monkeypatch.setattr(context_worker, "refresh_compass_task_snapshots", fake_refresh)

    assert refresh_snapshots_now("T1") is True
    assert calls == [("cmp_test", "T1", "techops")]


def test_exception_from_underlying_refresh_returns_false(monkeypatch):
    monkeypatch.setenv("COMPASS_API_KEY", "cmp_test")

    def exploding(api_key, team_id, *, compass_team):
        raise RuntimeError("compass MCP down")

    monkeypatch.setattr(context_worker, "refresh_compass_task_snapshots", exploding)

    assert refresh_snapshots_now("T1") is False


# ------------------------------------------------------------- handler tests


class FakeStateStore:
    def __init__(self):
        self.started: list[dict] = []

    def is_active(self, cache_key):
        return False

    def clear(self, cache_key):
        pass

    def start(self, cache_key, channel, **kwargs):
        session = SimpleNamespace(cache_key=cache_key, channel=channel, **kwargs)
        self.started.append(vars(session))
        return session


def _run_start_standup(monkeypatch, *, refresh_events, email: str | None = "ana@zubale.com"):
    """Drive _start_standup_session with every seam faked; return events."""
    events: list[str] = []
    fake_db = SimpleNamespace(
        get_standup_schedule=lambda team_id, sid: {
            "id": 1,
            "name": "Morning Standup",
            "channel_id": "C1",
            "questions": [],
        },
        get_schedule_for_user=lambda team_id, uid: None,
        get_workspace_config=lambda team_id: {},
        get_member_email=lambda team_id, uid: email,
    )
    import src.core as core_pkg

    monkeypatch.setattr(core_pkg, "db", fake_db, raising=False)
    monkeypatch.setattr(handlers, "state_store", FakeStateStore())

    def fake_context(client, members, *, team):
        events.append("compass")
        return {members[0]["user_id"]: [{"key": "TECH-1"}]}

    import src.modules.standup.blocks as blocks_mod
    import src.modules.standup.compass_context as compass_context_mod

    monkeypatch.setattr(compass_context_mod, "compass_context_for_members", fake_context)
    monkeypatch.setattr(compass_context_mod, "SnapshotCompassClient", lambda team_id: SimpleNamespace(team_id=team_id))
    monkeypatch.setattr(blocks_mod, "standup_dm_message", lambda questions, name: {"blocks": []})

    if refresh_events:
        monkeypatch.setenv("COMPASS_API_KEY", "cmp_test")
        monkeypatch.setattr(
            context_worker, "refresh_snapshots_now", lambda team_id: refresh_events.append("refresh") or True
        )
    else:
        # Any invocation of the refresh is a failure in this mode.
        monkeypatch.setattr(
            context_worker,
            "refresh_snapshots_now",
            lambda team_id: (_ for _ in ()).throw(AssertionError("sync refresh must not be invoked")),
        )

    slack = MagicMock()
    handlers._start_standup_session("U1", "T1", slack, schedule_id=1)
    return events


def test_sync_refresh_runs_before_snapshot_read(monkeypatch):
    events: list[str] = []

    def spy(team_id):
        events.append("refresh")
        return True

    import src.modules.standup.compass_context as compass_context_mod

    monkeypatch.setenv("COMPASS_API_KEY", "cmp_test")
    monkeypatch.setattr(context_worker, "refresh_snapshots_now", spy)
    fake_db = SimpleNamespace(
        get_standup_schedule=lambda team_id, sid: {"id": 1, "name": "S", "channel_id": "C1", "questions": []},
        get_schedule_for_user=lambda team_id, uid: None,
        get_workspace_config=lambda team_id: {},
        get_member_email=lambda team_id, uid: "ana@zubale.com",
    )
    import src.core as core_pkg

    monkeypatch.setattr(core_pkg, "db", fake_db, raising=False)
    monkeypatch.setattr(handlers, "state_store", FakeStateStore())

    def fake_context(client, members, *, team):
        events.append("compass")
        return {members[0]["user_id"]: [{"key": "TECH-1"}]}

    monkeypatch.setattr(compass_context_mod, "compass_context_for_members", fake_context)
    monkeypatch.setattr(compass_context_mod, "SnapshotCompassClient", lambda team_id: SimpleNamespace(team_id=team_id))
    import src.modules.standup.blocks as blocks_mod

    monkeypatch.setattr(blocks_mod, "standup_dm_message", lambda questions, name: {"blocks": []})

    handlers._start_standup_session("U1", "T1", MagicMock(), schedule_id=1)

    assert events == ["refresh", "compass"]


def test_kill_switch_disables_sync_refresh(monkeypatch):
    monkeypatch.setenv("COMPASS_SYNC_REFRESH", "0")
    events = _run_start_standup(monkeypatch, refresh_events=[])

    assert events == ["compass"]


def test_missing_api_key_skips_sync_refresh_but_still_reads_snapshot(monkeypatch):
    monkeypatch.delenv("COMPASS_API_KEY", raising=False)
    events = _run_start_standup(monkeypatch, refresh_events=[])

    assert events == ["compass"]


def test_no_email_skips_sync_refresh(monkeypatch):
    events = _run_start_standup(monkeypatch, refresh_events=[], email=None)
    assert events == []
