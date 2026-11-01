"""Retry policy and operator alerts for standup DM delivery.

Slack distinguishes failures for us: a 429 asks us to wait, a 5xx will pass,
and a 403/404 (deactivated user, gone channel) will never succeed no matter
how many times we try. The DM retry path now honours that split, and the two
silent dead-ends — a standup abandoned after all retries, and an owner notice
that itself cannot be delivered — raise an operator alert.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock, patch

from tests.support import patch_modules

for _name in ("pytz", "slack_sdk"):
    if isinstance(sys.modules.get(_name), MagicMock):
        del sys.modules[_name]

_had_scheduler = "scheduler" in sys.modules
import src.core.scheduler as sched_mod  # noqa: E402

if _had_scheduler:
    sched_mod = importlib.reload(sched_mod)


class _SlackHttpError(Exception):
    """Mimics slack_sdk SlackApiError: response carries status, headers and error."""

    def __init__(self, code: str, status: int, headers: dict | None = None):
        super().__init__("The request to the Slack API failed. (url: https://slack.com/api/x)")
        self.response = MagicMock()
        self.response.status_code = status
        self.response.headers = headers or {}
        self.response.get.return_value = code


class _SlackApiError(Exception):
    """Mimics slack_sdk SlackApiError whose response is the parsed payload dict."""

    def __init__(self, code: str):
        super().__init__(f"The request to the Slack API failed. The server responded with: {{'error': '{code}'}}")
        self.response = {"ok": False, "error": code}


def _client(open_error=None, post_error=None):
    client = MagicMock()
    dm = MagicMock()
    dm.__getitem__.return_value = {"id": "D123"}
    client.conversations_open.return_value = dm
    if open_error:
        client.conversations_open.side_effect = open_error
    if post_error:
        client.chat_postMessage.side_effect = post_error
    return client


class TestRateLimitHonoursRetryAfter:
    def test_429_waits_exactly_the_retry_after_header(self):
        client = _client(open_error=_SlackHttpError("ratelimited", 429, {"Retry-After": "7"}))
        # First call raises 429, second succeeds.
        client.conversations_open.side_effect = [
            _SlackHttpError("ratelimited", 429, {"Retry-After": "7"}),
            dm_ok(),
        ]
        with patch.object(sched_mod.time, "sleep") as sleep:
            assert sched_mod._slack_dm_with_retry(client, "U1") is True
        sleep.assert_called_once_with(7.0)

    def test_retry_after_is_capped_so_slack_cannot_stall_a_worker(self):
        client = _client()
        client.conversations_open.side_effect = [
            _SlackHttpError("ratelimited", 429, {"Retry-After": "3600"}),
            dm_ok(),
        ]
        with patch.object(sched_mod.time, "sleep") as sleep:
            assert sched_mod._slack_dm_with_retry(client, "U1") is True
        sleep.assert_called_once_with(sched_mod._DM_RETRIES_CAP_SECONDS)

    def test_a_429_without_the_header_still_retries_with_backoff(self):
        client = _client()
        client.conversations_open.side_effect = [
            _SlackHttpError("ratelimited", 429),
            dm_ok(),
        ]
        with patch.object(sched_mod.time, "sleep") as sleep:
            assert sched_mod._slack_dm_with_retry(client, "U1") is True
        assert sleep.call_args.args[0] < 5  # exponential backoff, not the cap


def dm_ok():
    dm = MagicMock()
    dm.__getitem__.return_value = {"id": "D123"}
    return dm


class TestNonRetryableFailsFast:
    def test_403_does_not_burn_retries(self):
        exc = _SlackHttpError("user_deactivated", 403)
        client = _client(open_error=exc)
        with patch.object(sched_mod.time, "sleep") as sleep:
            try:
                sched_mod._slack_dm_with_retry(client, "U1")
                raise AssertionError("should have raised")
            except Exception as raised:
                assert raised is exc
        sleep.assert_not_called()
        assert client.conversations_open.call_count == 1
        client.chat_postMessage.assert_not_called()

    def test_404_does_not_retry(self):
        exc = _SlackHttpError("channel_not_found", 404)
        client = _client(open_error=exc)
        with patch.object(sched_mod.time, "sleep") as sleep:
            try:
                sched_mod._slack_dm_with_retry(client, "U1")
                raise AssertionError("should have raised")
            except Exception:
                pass
        sleep.assert_not_called()

    def test_slack_payload_code_alone_is_enough(self):
        exc = _SlackApiError("user_not_found")
        client = _client(open_error=exc)
        try:
            sched_mod._slack_dm_with_retry(client, "U1")
            raise AssertionError("should have raised")
        except Exception:
            pass
        assert client.conversations_open.call_count == 1


class TestServerErrorsRetry:
    def test_5xx_is_treated_as_transient(self):
        client = _client()
        client.conversations_open.side_effect = [
            _SlackHttpError("internal_error", 503),
            dm_ok(),
        ]
        with patch.object(sched_mod.time, "sleep") as sleep:
            assert sched_mod._slack_dm_with_retry(client, "U1") is True
        sleep.assert_called_once_with(1.0)  # 1.5**0: the first backoff step

    def test_5xx_gives_up_after_max_retries(self):
        exc = _SlackHttpError("internal_error", 500)
        client = _client(open_error=exc)
        with patch.object(sched_mod.time, "sleep"):
            try:
                sched_mod._slack_dm_with_retry(client, "U1", max_retries=2)
                raise AssertionError("should have raised")
            except Exception as raised:
                assert raised is exc
        assert client.conversations_open.call_count == 3  # initial + 2 retries


def _db():
    db = MagicMock()
    db.get_standup_schedule.return_value = {
        "id": 32,
        "active": True,
        "channel_id": "C1",
        "questions": [],
        "participants": [],
        "name": "Daily",
    }
    db.get_active_members.return_value = [{"user_id": "U1"}]
    return db


class TestGivingUpAlertsTheOperator:
    def test_exhausted_retries_post_an_alert_with_team_schedule_and_code(self):
        alerts = MagicMock()
        with (
            patch_modules({"src.core.db": _db()}),
            patch.object(sched_mod, "_fresh_bot_token", side_effect=lambda team, token: token),
            patch.object(sched_mod, "_call_with_auth_retry", side_effect=ConnectionError("network down")),
            patch.object(sched_mod, "_schedule_standup_retry"),
            patch.dict(sys.modules, {"src.core.alerts": alerts}),
        ):
            sched_mod._send_standup_to_workspace("T1", "xoxb-test", "C1", 32, retry_attempt=3)
        text = alerts.notify.call_args.args[0]
        assert "T1" in text
        assert "32" in text
        assert "slack_error" in text


class TestCircularDeliveryFailureAlerts:
    def test_an_undeliverable_owner_notice_posts_an_operator_alert(self):
        client = MagicMock()
        client.chat_postMessage.side_effect = ConnectionError("slack down")
        db = MagicMock()
        db.get_installation.return_value = {"installed_by_user_id": "UOWNER"}
        alerts = MagicMock()
        with (
            patch_modules({"src.core.db": db}),
            patch.dict(sys.modules, {"src.core.alerts": alerts}),
        ):
            sched_mod._notify_delivery_failure(client, "T1", "C1", 2, 5, "Daily")
        client.chat_postMessage.assert_called_once()
        assert alerts.notify.called

    def test_non_retryable_codes_are_spelled_out_to_the_owner(self):
        client = MagicMock()
        db = MagicMock()
        db.get_installation.return_value = {"installed_by_user_id": "UOWNER"}
        with patch_modules({"src.core.db": db}):
            sched_mod._notify_delivery_failure(
                client, "T1", "C1", 2, 5, "Daily", non_retryable_codes=("user_deactivated",)
            )
        text = client.chat_postMessage.call_args.kwargs["text"]
        assert "user_deactivated" in text
        assert "no retry will fix it" in text
