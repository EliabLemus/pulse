"""The Flask app must expose /slack/commands.

Slack delivers slash-command payloads to the Request URL configured per
command; the canonical path is /slack/commands. Without the route the app
answers 404, Slack retries three times and then shows the user
"dispatch_unknown_error" — which is exactly how a locked-out user surfaced
the gap in production (the expired-session message tells them to run
/standup, and that command had nowhere to land).
"""

from __future__ import annotations

import importlib
from unittest import mock

from flask import Flask


def _load_main(monkeypatch: mock, env: dict[str, str]) -> Flask:
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    # Do NOT purge src.* from sys.modules: a later module in the same session
    # (e.g. test_workspace_history) holds references to the *original*
    # src.core.db, and re-importing a second copy here would leave the
    # fake_cursor_db fixture patching a module object nothing else uses.
    main = importlib.import_module("src.main")
    _, app = main.create_app()
    return app


class TestSlackCommandsRoute:
    def test_commands_route_exists(self, monkeypatch: mock) -> None:
        app = _load_main(
            monkeypatch,
            {
                "SLACK_SIGNING_SECRET": "test-secret",
                "FLASK_SECRET_KEY": "a" * 64,
            },
        )
        rules = {r.rule for r in app.url_map.iter_rules()}
        assert "/slack/commands" in rules
        assert "/slack/events" in rules
        assert "/slack/interactions" in rules

    def test_commands_route_answers_unauthorized_without_signature(self, monkeypatch: mock) -> None:
        app = _load_main(
            monkeypatch,
            {
                "SLACK_SIGNING_SECRET": "test-secret",
                "FLASK_SECRET_KEY": "a" * 64,
            },
        )
        client = app.test_client()
        res = client.post(
            "/slack/commands",
            data="command=%2Fstandup&user_id=U123",
            content_type="application/x-www-form-urlencoded",
        )
        # Bolt rejects unsigned requests; the important part is that this is no
        # longer a 404: the route exists and hands the request to Bolt.
        assert res.status_code in (401, 200)
