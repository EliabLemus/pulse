"""Regression coverage for Compass task context in active Pulse sessions."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../src"))


def test_active_session_round_trips_compass_task_identity(monkeypatch):
    import state

    persisted: dict[str, dict] = {}
    monkeypatch.setattr(state.session_store, "set_session", lambda key, value: persisted.__setitem__(key, value))
    monkeypatch.setattr(state.session_store, "get_session", lambda key: persisted.get(key))

    store = state.StateStore()
    store.start(
        "T1:U1",
        "C1",
        team_id="T1",
        compass_tasks=[{"key": "TOP-1", "title": "Improve deployment"}],
    )

    assert store.get("T1:U1").compass_tasks == [{"key": "TOP-1", "title": "Improve deployment"}]
