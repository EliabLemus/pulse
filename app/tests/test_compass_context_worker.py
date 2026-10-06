from __future__ import annotations

from types import SimpleNamespace


def test_refresh_worker_persists_normalized_assignments_without_comment_writes(monkeypatch):
    from src.modules.standup import context_worker

    saved = {}

    class CompassReadSpy:
        def __init__(self, api_key):
            assert api_key == "cmp_test"
            self.calls = []

        def active_sprint_assignments(self, emails, *, team):
            self.calls.append((emails, team))
            return {
                "eliab.lemus@zubale.com": [{"key": "TECH-8", "title": "Deploy", "statusCategory": "active"}],
                "other@zubale.com": [],
                "sprint_name": "Sprint 2",
            }

        def post_comment(self, *_args, **_kwargs):
            raise AssertionError("context refresh must never write Compass comments")

    client = CompassReadSpy("cmp_test")
    fake_db = SimpleNamespace(
        get_active_members=lambda team_id: [
            {"user_id": "U1", "email": " ELIAB.LEMUS@zubale.com "},
            {"user_id": "U2", "email": "other@zubale.com"},
            {"user_id": "U3", "email": "not-an-email"},
        ],
        replace_compass_task_snapshots=lambda team_id, assignments: saved.update(
            team_id=team_id, assignments=assignments
        ),
    )
    monkeypatch.setattr(context_worker, "db", fake_db)

    result = context_worker.refresh_compass_task_snapshots(
        "cmp_test", "T1", compass_team="techops", client_factory=lambda _key: client
    )

    assert result == {"members": 2, "snapshots": 2}
    assert client.calls == [(["eliab.lemus@zubale.com", "other@zubale.com"], "techops")]
    assert saved == {
        "team_id": "T1",
        "assignments": {
            "eliab.lemus@zubale.com": [{"key": "TECH-8", "title": "Deploy", "statusCategory": "active"}],
            "other@zubale.com": [],
        },
    }
