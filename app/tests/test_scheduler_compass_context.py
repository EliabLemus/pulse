"""Scheduler wiring of the Compass context adapter into scheduled standup DMs.

Contract under test (TASK-COMPASS-DSU-002):
- one batched adapter call for all candidate members, before the member loop;
- each session gets only its own member's task snapshot via
  ``state_store.start(..., compass_tasks=...)``;
- no client / adapter failure may stop the ordinary DMs (fail-open to ``[]``);
- the client comes from an injectable seam — no env credential read, and the
  scheduler never calls Compass write APIs.

Every external seam (Slack, DB, state store, Compass) is monkeypatched, so
these tests need no secrets, no network and no real Slack.
"""

from __future__ import annotations

import contextlib
import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.support import patch_modules

# Earlier test modules leave MagicMock stubs in sys.modules; the scheduler
# needs the real pytz/slack_sdk (same preamble as test_scheduler_channel_sync).
for _name in ("pytz", "slack_sdk"):
    if isinstance(sys.modules.get(_name), MagicMock):
        del sys.modules[_name]

_had_scheduler = "scheduler" in sys.modules
import src.core.scheduler as sched_mod  # noqa: E402

if _had_scheduler:
    sched_mod = importlib.reload(sched_mod)

ADAPTER_MODULE = "src.modules.standup.compass_context"

MEMBERS = [
    {"user_id": "U1", "real_name": "Ana", "email": "ana@zubale.com"},
    {"user_id": "U2", "real_name": "Bo", "email": "bo@zubale.com"},
]

TASK_A = {"key": "TECH-1", "title": "Patch scheduler"}
TASK_B = {"key": "TECH-2", "title": "Ship guided DSU"}


def _schedule(**overrides):
    row = {
        "id": 1,
        "team_id": "T1",
        "name": "Morning Standup",
        "channel_id": "C1",
        "sync_with_channel": False,
        "participants": [],
        "questions": [],
        "active": True,
    }
    row.update(overrides)
    return row


class FakeStateStore:
    """Records started sessions without touching the real in-memory state."""

    def __init__(self):
        self.started: list[dict] = []

    def blocks_scheduled_dm(self, cache_key, schedule_id=None):
        return False

    def start(self, cache_key, channel, **kwargs):
        self.started.append({"cache_key": cache_key, "channel": channel, **kwargs})


class AdapterSpy:
    """Stands in for ``compass_context_for_members`` and records its calls."""

    def __init__(self, result=None, error=None, events=None):
        self.calls: list[dict] = []
        self.result = result if result is not None else {}
        self.error = error
        self.events = events

    def __call__(self, client, members, *, team):
        self.calls.append({"client": client, "members": [dict(m) for m in members], "team": team})
        if self.events is not None:
            self.events.append("compass")
        if self.error is not None:
            raise self.error
        return {uid: [dict(t) for t in tasks] for uid, tasks in self.result.items()}


class CompassClientSpy:
    """Read-only Compass stand-in; write APIs assert if ever touched."""

    def __init__(self):
        self.calls: list[tuple] = []

    def active_sprint_assignments(self, emails, *, team, max_tasks_per_email=5):
        self.calls.append(("active_sprint_assignments", sorted(emails), team))
        return {}

    def get_ticket(self, key):
        raise AssertionError("scheduler must never call get_ticket")

    def post_comment(self, *args, **kwargs):
        raise AssertionError("scheduler must never call post_comment")


@contextlib.contextmanager
def _patch_client_seam(side_effect):
    """Patch the injection seam when it exists; otherwise the default path runs.

    Before the seam exists (RED), the scheduler's no-Compass default must keep
    delivering DMs, which is exactly what the fail-open tests assert.
    """
    if hasattr(sched_mod, "_compass_context_client"):
        with patch.object(sched_mod, "_compass_context_client", side_effect=side_effect):
            yield
    else:
        yield


@contextlib.contextmanager
def _patch_context_loader(adapter):
    """Inject the feature-owned adapter through the core registration seam."""
    if hasattr(sched_mod, "_compass_context_loader"):
        with patch.object(sched_mod, "_compass_context_loader", adapter):
            yield
    else:
        yield


def run_standup(adapter=None, seam=None):
    """Run one minimal scheduled standup with every external seam faked.

    Returns ``(state, adapter, client, events)`` where ``events`` records the
    order of the compass read versus the DMs.
    """
    db = MagicMock()
    db.get_standup_schedule.return_value = _schedule()
    db.get_active_members.return_value = [dict(m) for m in MEMBERS]
    db.is_skipped_today.return_value = False
    db.is_on_vacation.return_value = False

    slack = MagicMock()
    state = FakeStateStore()
    events: list[str] = []
    adapter = adapter if adapter is not None else AdapterSpy(events=events)
    client = CompassClientSpy()
    dm = MagicMock(side_effect=lambda c, uid, **kw: events.append(f"dm:{uid}"))

    if seam is None:
        seam = lambda team_id: client  # noqa: E731

    patches = [
        patch_modules({"src.core.db": db}),
        patch.object(sched_mod, "WebClient", return_value=slack),
        patch.object(sched_mod, "_fresh_bot_token", side_effect=lambda team, token: token),
        patch.object(sched_mod, "state_store", state),
        _patch_client_seam(seam),
        _patch_context_loader(adapter),
        patch.object(sched_mod, "_slack_dm_with_retry", dm),
    ]

    with contextlib.ExitStack() as stack:
        for p in patches:
            stack.enter_context(p)
        sched_mod._send_standup_to_workspace("T1", "xoxb-test", "C1", 1)
    return state, adapter, client, events


def _started_for(state, user_id):
    matches = [s for s in state.started if s["cache_key"] == f"T1:{user_id}"]
    assert len(matches) == 1, f"expected exactly one session for {user_id}, got {len(matches)}"
    return matches[0]


class TestBatchedReadBeforeMemberLoop:
    def test_one_adapter_call_covers_every_candidate_member(self):
        _, adapter, _, _ = run_standup()

        assert len(adapter.calls) == 1
        call = adapter.calls[0]
        assert [m["user_id"] for m in call["members"]] == ["U1", "U2"]
        assert call["team"] == getattr(sched_mod, "_COMPASS_CONTEXT_TEAM", "techops")

    def test_the_read_happens_before_any_dm(self):
        _, _, _, events = run_standup()

        assert events.index("compass") < events.index("dm:U1")
        assert events.index("compass") < events.index("dm:U2")

    def test_scheduler_passes_the_injected_client_to_the_adapter(self):
        _, adapter, client, _ = run_standup()

        assert adapter.calls[0]["client"] is client


class TestPerMemberSnapshot:
    def test_each_session_receives_only_its_own_tasks(self):
        adapter = AdapterSpy(result={"U1": [TASK_A], "U2": [TASK_B]})
        state, _, _, _ = run_standup(adapter=adapter)

        assert _started_for(state, "U1")["compass_tasks"] == [TASK_A]
        assert _started_for(state, "U2")["compass_tasks"] == [TASK_B]

    def test_a_member_without_tasks_gets_an_empty_list(self):
        adapter = AdapterSpy(result={"U1": [TASK_A]})
        state, _, _, _ = run_standup(adapter=adapter)

        assert _started_for(state, "U2")["compass_tasks"] == []


class TestFailOpen:
    def test_no_client_configured_still_dms_and_starts_empty_sessions(self):
        state, adapter, _, events = run_standup(seam=lambda team_id: None)

        assert adapter.calls == []
        assert [e for e in events if e.startswith("dm:")] == ["dm:U1", "dm:U2"]
        assert len(state.started) == 2
        assert all(s["compass_tasks"] == [] for s in state.started)

    def test_adapter_failure_fails_open(self):
        adapter = AdapterSpy(error=RuntimeError("compass down"))
        state, spy, _, events = run_standup(adapter=adapter)

        assert [e for e in events if e.startswith("dm:")] == ["dm:U1", "dm:U2"]
        assert len(state.started) == 2
        assert all(s["compass_tasks"] == [] for s in state.started)
        assert len(spy.calls) == 1

    def test_seam_failure_fails_open(self):
        def exploding_seam(team_id):
            raise RuntimeError("no compass wiring")

        state, _, _, events = run_standup(seam=exploding_seam)

        assert [e for e in events if e.startswith("dm:")] == ["dm:U1", "dm:U2"]
        assert len(state.started) == 2
        assert all(s["compass_tasks"] == [] for s in state.started)

    def test_missing_context_loader_fails_open(self):
        with patch.object(sched_mod, "_compass_context_loader", None):
            state, _, _, events = run_standup()

        assert [e for e in events if e.startswith("dm:")] == ["dm:U1", "dm:U2"]
        assert len(state.started) == 2
        assert all(s["compass_tasks"] == [] for s in state.started)


def test_standup_registers_snapshot_context_without_daemon_credentials(monkeypatch):
    import src.modules.standup as standup

    monkeypatch.setattr(sched_mod, "_compass_context_loader", None)
    monkeypatch.setattr(sched_mod, "_compass_context_client", lambda _team_id: None)

    standup.configure_compass_context()

    client = sched_mod._compass_context_client("T1")
    assert client.__class__.__name__ == "SnapshotCompassClient"
    assert sched_mod._compass_context_loader.__name__ == "compass_context_for_members"


class TestNoCredentialOrWriteWiring:
    SOURCE = Path(__file__).resolve().parents[1] / "src" / "core" / "scheduler.py"

    def test_scheduler_never_reads_compass_credentials_or_write_apis(self):
        source = self.SOURCE.read_text(encoding="utf-8")

        for forbidden in ("COMPASS_API_KEY", "get_ticket", "post_comment"):
            assert forbidden not in source, f"scheduler must not reference {forbidden}"

    def test_scheduler_has_no_direct_feature_context_import(self):
        source = self.SOURCE.read_text(encoding="utf-8")

        assert "src.core.compass_context" not in source
        assert "src.modules.standup.compass_context" not in source
        assert "_compass_context_loader" in source
