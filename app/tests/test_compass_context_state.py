"""Consistent DSU rendering: an explicit compass_context_state on the session.

Contract:
- ``UserSession`` serializes/deserializes ``compass_context_state``; old
  payloads without it read back as ``unavailable``;
- ``StateStore.start`` accepts an optional ``compass_context_state``;
- the pure helper maps (tasks, snapshot availability) onto exactly three
  states;
- the scheduled path and the manual path both pass the derived state into
  ``state_store.start``;
- empty/unavailable finalization uses the modern durable guided delivery with
  ``comments=[]`` and never posts a direct legacy channel message;
- DM-only sessions (no channel) publish nothing to a channel.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.core.state import StateStore, UserSession, _deserialize, _serialize, context_state  # noqa: E402
from src.modules.standup import handlers  # noqa: E402

from tests.support import patch_modules  # noqa: E402

# ---------------------------------------------------------------- state roundtrip


def test_session_roundtrip_preserves_compass_context_state():
    session = UserSession(cache_key="T1:U1", team_id="T1", channel="C1", compass_context_state="fresh_empty")
    data = _serialize(session)
    assert data["compass_context_state"] == "fresh_empty"
    assert _deserialize(data).compass_context_state == "fresh_empty"


def test_legacy_payload_defaults_to_unavailable():
    session = _deserialize({"cache_key": "T1:U1", "team_id": "T1", "channel": "C1"})
    assert session.compass_context_state == "unavailable"


def test_state_store_start_accepts_compass_context_state():
    store = StateStore()
    store.start("T1:U9", "C1", team_id="T1", compass_context_state="fresh_with_tasks")
    session = store.get("T1:U9")
    assert session.compass_context_state == "fresh_with_tasks"
    store.clear("T1:U9")


def test_state_store_start_defaults_to_unavailable():
    store = StateStore()
    store.start("T1:U8", "C1", team_id="T1")
    assert store.get("T1:U8").compass_context_state == "unavailable"
    store.clear("T1:U8")


# ---------------------------------------------------------------- helper


def test_context_state_helper_three_states():
    assert context_state([{"key": "TECH-1"}]) == "fresh_with_tasks"
    assert context_state([]) == "fresh_empty"
    assert context_state([], unavailable=True) == "unavailable"
    assert context_state([{"key": "TECH-1"}], unavailable=True) == "unavailable"


# ---------------------------------------------------------------- scheduled path


class _FakeStore:
    def __init__(self):
        self.started: list[dict] = []

    def blocks_scheduled_dm(self, cache_key, schedule_id=None):
        return False

    def is_active(self, key):
        return False

    def get(self, key):
        return None

    def start(self, cache_key, channel, **kwargs):
        self.started.append({"cache_key": cache_key, "channel": channel, **kwargs})
        return UserSession(cache_key=cache_key, channel=channel, **kwargs)


def _run_scheduled(compass_tasks, *, stale):
    """Drive _send_standup_to_workspace with every seam faked; return the started session."""
    import src.core.scheduler as sched

    db = MagicMock()
    db.get_today_standups.return_value = []
    db.get_active_members.return_value = members = [{"user_id": "U1", "real_name": "Ana", "email": "ana@zubale.com"}]
    db.is_skipped_today.return_value = False
    db.is_on_vacation.return_value = False
    db.list_holidays.return_value = []
    db.get_standup_schedule.return_value = {
        "id": 1,
        "name": "DSU",
        "channel_id": "C1",
        "sync_with_channel": False,
        "participants": [],
        "questions": [],
        "schedule_tz": "UTC",
        "active": True,
    }
    db.stale_compass_snapshot_teams.return_value = ["T1"] if stale else []
    store = _FakeStore()
    client = MagicMock()
    client.conversations_info.return_value = {"channel": {"id": "C1"}}
    with (
        patch_modules({"src.core.db": db}),
        patch.object(sched, "state_store", store),
        patch.object(sched, "_compass_task_context", return_value={"U1": list(compass_tasks)}),
        patch.object(sched, "_slack_dm_with_retry"),
        patch.object(sched, "fetch_human_users", return_value={m["user_id"]: m for m in members}),
        patch.object(sched, "_fresh_bot_token", side_effect=lambda team, token: token),
        patch.object(sched, "WebClient", return_value=MagicMock()),
    ):
        try:
            sched._send_standup_to_workspace(
                team_id="T1",
                bot_token="xoxb-test",
                channel_id="C1",
                schedule_id=1,
                skip_answered=True,
            )
        except TypeError:
            pytest.fail("scheduler signature changed; update test")
    assert store.started, "scheduler never started a session"
    return store.started[0]


def test_scheduler_passes_fresh_with_tasks_state():
    started = _run_scheduled([{"key": "TECH-1"}], stale=False)
    assert started["compass_context_state"] == "fresh_with_tasks"


def test_scheduler_passes_fresh_empty_state():
    started = _run_scheduled([], stale=False)
    assert started["compass_context_state"] == "fresh_empty"


def test_scheduler_passes_unavailable_state_when_stale():
    started = _run_scheduled([], stale=True)
    assert started["compass_context_state"] == "unavailable"


# ---------------------------------------------------------------- manual path


def _run_manual(db_get=None, tasks=(), *, raises=False):
    db = MagicMock()
    db.get_standup_schedule.return_value = None
    db.get_schedule_for_user.return_value = {"id": 3, "name": "DSU", "channel_id": "C1", "questions": []}
    db.get_member_email.return_value = "ana@zubale.com"
    if db_get:
        db_get(db)
    store = _FakeStore()
    client = MagicMock()
    with (
        patch_modules({"src.core.db": db}),
        patch.object(handlers, "state_store", store),
        patch("src.modules.standup.blocks.standup_dm_message", return_value={"blocks": []}),
    ):
        if raises:
            with patch(
                "src.modules.standup.compass_context.SnapshotCompassClient",
                side_effect=RuntimeError("boom"),
            ):
                handlers._start_standup_session("U1", "T1", client)
        else:
            with patch(
                "src.modules.standup.compass_context.compass_context_for_members",
                return_value={"U1": list(tasks)},
            ):
                handlers._start_standup_session("U1", "T1", client)
    assert store.started, "manual start never began a session"
    return store.started[0]


def test_manual_start_passes_fresh_with_tasks():
    assert _run_manual(tasks=[{"key": "TECH-1"}])["compass_context_state"] == "fresh_with_tasks"


def test_manual_start_passes_fresh_empty():
    assert _run_manual(tasks=[])["compass_context_state"] == "fresh_empty"


def test_manual_start_exception_yields_unavailable():
    assert _run_manual(raises=True)["compass_context_state"] == "unavailable"


# ---------------------------------------------------------------- completion path


def _complete(state, *, channel="C1", tasks=(), editing_standup_id=None):
    db = MagicMock()
    db.get_standup_schedule.return_value = {"id": 7, "name": "DSU TechOps", "channel_id": channel}
    db.get_workspace_config.return_value = {}
    db.get_active_members.return_value = [{"user_id": "U1", "real_name": "Ada"}]
    client = MagicMock()
    client.chat_postMessage.return_value = {"ts": "2.2"}
    session = UserSession(
        cache_key="T1:U1",
        team_id="T1",
        channel=channel,
        schedule_id=7,
        compass_tasks=list(tasks),
        compass_context_state=state,
        editing_standup_id=editing_standup_id,
        answers=["ayer", "hoy", "ninguno"],
    )
    with (
        patch_modules({"src.core.db": db}),
        patch.object(handlers, "_persist_standup", return_value=42),
        patch.object(handlers, "state_store"),
        patch.object(handlers, "fire_webhooks"),
        patch.object(handlers, "edit_rule_text", return_value=""),
        patch.object(handlers, "_daily_thread_parent", return_value="1.1"),
        patch("src.core.scheduler.standup_local_date", return_value=date(2026, 11, 4)),
        patch("src.modules.standup.workflow.evaluate_rules"),
        patch.object(
            handlers,
            "_persist_guided_submission",
            return_value=99,
        ) as persist,
        patch.object(
            handlers,
            "claim_guided_delivery",
            return_value={"channel_id": channel, "channel_text": "x", "channel_blocks": []},
        ),
        patch.object(handlers, "mark_guided_delivery_delivered"),
        patch.object(handlers, "build_guided_channel_message", wraps=handlers.build_guided_channel_message) as renderer,
    ):
        handlers._complete_standup("U1", session, client)
        channel_posts = [c.kwargs for c in client.chat_postMessage.call_args_list if c.kwargs.get("channel") == channel]
        return persist, renderer, channel_posts


def test_fresh_empty_finalizes_modern_without_legacy_post():
    persist, renderer, posts = _complete("fresh_empty")
    assert persist.call_count == 1
    assert persist.call_args.kwargs["comments"] == []
    assert renderer.call_count == 1
    assert len(posts) == 1, "expected exactly the durable guided delivery post"


def test_unavailable_finalizes_modern_without_legacy_post():
    persist, renderer, posts = _complete("unavailable")
    assert persist.call_count == 1
    assert persist.call_args.kwargs["comments"] == []
    assert renderer.call_count == 1
    assert len(posts) == 1


def test_modern_generic_edit_updates_without_duplicate_guided_persistence():
    persist, renderer, posts = _complete("unavailable", editing_standup_id=41)
    assert persist.call_count == 0
    assert renderer.call_count == 1
    assert len(posts) == 1


def test_dm_only_session_publishes_nothing_to_channel():
    persist, renderer, posts = _complete("unavailable", channel="")
    assert persist.call_count == 0
    assert len(posts) == 0, "DM-only session must not group-post"


def test_fresh_with_tasks_keeps_guided_behavior():
    persist, renderer, posts = _complete("fresh_with_tasks", tasks=[{"key": "TECH-1"}])
    # The fresh path never builds the generic guided renderer directly here:
    # it is finalized by the guided wizard modal, not by _complete_standup.
    assert renderer.call_count == 0
