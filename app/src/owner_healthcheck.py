"""Owner health-check: a DM with an OK button that proves the full round trip.

Owner rule (2026-09-23): verify with Eliab alone that Tailscale/Funnel and the
Slack round trip work. Pulse DMs the owner a single block-button message; the
button's interactive payload arrives back over the public Funnel path exactly
like every other interaction, and the handler replies confirming the
connection. Nobody else is ever messaged, and the daily check runs weekdays
only — weekend silence applies to this too.

Failure semantics: the outgoing DM exercises Pulse → Slack; the incoming button
payload exercises Funnel → Caddy → Pulse. If either half fails, silence on the
owner's phone is the alert signal (plus the endpoint watchdog contract).
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

CHECK_OK_ACTION_ID = "owner_health_check_ok"

# Only this Slack user is ever messaged. U09GE1J7HDK = Eliab Lemus.
OWNER_SLACK_USER_ID = os.environ.get("PULSE_HEALTHCHECK_OWNER_ID", "U09GE1J7HDK")


def owner_health_check_message() -> dict:
    """The check DM: one line plus one OK button, minimal by copy rules."""
    return {
        "blocks": [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "🔧 Verificación de conexión. Pulsa OK:"},
            },
            {
                "type": "actions",
                "block_id": "health_check_actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": CHECK_OK_ACTION_ID,
                        "text": {"type": "plain_text", "text": "OK", "emoji": True},
                        "style": "primary",
                        "value": "health_check",
                    }
                ],
            },
        ]
    }


def send_owner_health_check(client) -> bool:
    """DM the owner the check message. True when Slack accepted it."""
    try:
        client.chat_postMessage(channel=OWNER_SLACK_USER_ID, **owner_health_check_message())
        return True
    except Exception as exc:
        logger.warning("Owner health-check DM failed: %s", exc)
        return False


def send_scheduled_owner_check(team_id: str, bot_token: str) -> None:
    """Scheduler job body: resolve the current token, then DM the owner."""
    try:
        from scheduler import _fresh_bot_token  # noqa: PLC0415
        from slack_sdk import WebClient  # noqa: PLC0415

        client = WebClient(token=_fresh_bot_token(team_id, bot_token))
        if send_owner_health_check(client):
            logger.info("Owner health-check sent for %s", team_id)
    except Exception as exc:
        logger.warning("Owner health-check job failed for %s: %s", team_id, exc)


def register_owner_health_check(scheduler, team_id: str, bot_token: str, tz_name: str = "America/Guatemala") -> None:
    """Register the daily 09:00 weekday check DM (before the standup DMs)."""
    import pytz  # noqa: PLC0415
    from apscheduler.triggers.cron import CronTrigger  # noqa: PLC0415

    scheduler.add_job(
        send_scheduled_owner_check,
        trigger=CronTrigger(hour=9, minute=0, day_of_week="mon,tue,wed,thu,fri", timezone=pytz.timezone(tz_name)),
        args=[team_id, bot_token],
        id=f"owner_health_check_{team_id}",
        name="Owner health check",
        replace_existing=True,
    )


def register_health_check_actions(app) -> None:
    """Wire the OK-button handler. Only the owner gets a confirmation."""

    @app.action(CHECK_OK_ACTION_ID)
    def handle_owner_health_check_ok(ack, body, client):  # noqa: ANN001
        ack()
        user_id = body["user"]["id"]
        if user_id != OWNER_SLACK_USER_ID:
            return
        try:
            client.chat_postMessage(channel=user_id, text="✅ Conexión verificada: Tailscale y Slack responden.")
        except Exception as exc:
            logger.warning("Owner health-check confirmation failed: %s", exc)
