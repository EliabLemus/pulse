"""The expired-session notice must carry a restart button.

Saying only "Run /standup" made the escape hatch a single point of failure:
when slash dispatch 404'd (2026-11-02), users had no working path forward.
"""

from __future__ import annotations

import importlib
from unittest import mock


def _client() -> mock.MagicMock:
    return mock.MagicMock()


def test_expired_notice_has_restart_button():
    handlers = importlib.import_module("src.modules.standup.handlers")
    client = _client()
    handlers._say_session_expired(client, "U1")
    assert client.chat_postMessage.call_count == 1
    kwargs = client.chat_postMessage.call_args.kwargs
    blocks = kwargs.get("blocks") or []
    actions = [b for b in blocks if b.get("type") == "actions"]
    assert actions, "notice must include an actions block"
    buttons = [e for e in actions[0]["elements"] if e.get("action_id") == "start_standup_now"]
    assert buttons, "notice must include a start_standup_now button"
    # Slack rejects empty button values; a non-numeric sentinel still triggers
    # the handler's schedule heuristic lookup.
    assert buttons[0].get("value") == "restart"


def test_expired_notice_mentions_no_slash_command():
    """The text must not depend on /standup reaching the server."""
    handlers = importlib.import_module("src.modules.standup.handlers")
    client = _client()
    handlers._say_session_expired(client, "U1")
    text = client.chat_postMessage.call_args.kwargs.get("text", "")
    assert "/standup" not in text
