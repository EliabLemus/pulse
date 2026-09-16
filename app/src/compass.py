"""Read-only Compass REST client for optional Pulse DM context."""

from __future__ import annotations

import json
import logging
import os
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

COMPASS_WEB_BASE_URL = "https://compass.zubale.com"


def ticket_url(key: str) -> str:
    """Return the Compass web URL for a task key (e.g. TECH-1)."""
    return f"{COMPASS_WEB_BASE_URL}/tickets/{key}"


class CompassClient:
    """Fetch visible Compass work without performing any write operation."""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://compass.zubale.com/api/v2/work",
        timeout_seconds: int = 10,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._mcp_url = f"{COMPASS_WEB_BASE_URL}/api/v2/mcp"

    def _call_mcp(self, tool_name: str, arguments: dict[str, str]) -> dict[str, Any]:
        request = Request(
            self._mcp_url,
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                }
            ).encode(),
            headers={"Authorization": f"Bearer {self._api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            payload = json.load(response)
        if not isinstance(payload, dict) or payload.get("error"):
            raise ValueError("Compass rejected the MCP tool call")
        result = payload.get("result")
        if not isinstance(result, dict):
            raise ValueError("Compass returned an invalid MCP tool result")
        return result

    def post_comment(self, key: str, body: str) -> dict[str, Any]:
        """Post a textual progress update without changing task workflow fields.

        With PULSE_COMPASS_WRITE_MODE=mock the comment is never sent to
        Compass: it is logged instead, so live rehearsals can exercise the
        full Pulse flow with zero real writes.
        """
        if not key.strip() or not body.strip():
            raise ValueError("Compass comments require a task key and non-empty body")
        if os.environ.get("PULSE_COMPASS_WRITE_MODE", "").strip().lower() == "mock":
            logger.warning("PULSE_COMPASS_MOCK_COMMENT key=%s body=%s", key, body)
            return {"mock": True}
        return self._call_mcp("post_comment", {"key": key, "body": body})

    def _request_json(self, path: str, params: dict[str, object] | None = None) -> dict[str, Any]:
        query = f"?{urlencode(params)}" if params else ""
        request = Request(
            f"{self._base_url}{path}{query}",
            headers={"Authorization": f"Bearer {self._api_key}"},
            method="GET",
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise ValueError("Compass returned a non-object JSON response")
        return payload

    def weekly_assignments(
        self,
        emails: list[str],
        *,
        team: str,
        local_day: date,
        max_tasks_per_email: int = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return open work due Monday-Friday, grouped by normalized assignee email."""
        normalized = {email.strip().lower() for email in emails if isinstance(email, str) and email.strip()}
        assignments: dict[str, list[dict[str, Any]]] = {email: [] for email in normalized}
        if not assignments:
            return assignments

        monday = local_day - timedelta(days=local_day.weekday())
        friday = monday + timedelta(days=4)
        keys: list[str] = []
        seen_keys: set[str] = set()
        for status in ("todo", "active", "blocked"):
            result = self._request_json("/tickets", {"team": team, "status": status, "limit": 100})
            for ticket in result.get("tickets") or []:
                if not isinstance(ticket, dict):
                    continue
                key = ticket.get("key")
                if isinstance(key, str) and key and key not in seen_keys:
                    seen_keys.add(key)
                    keys.append(key)

        for key in keys:
            ticket = self._request_json(f"/tickets/{quote(key, safe='')}")
            assignee = _assignee_email(ticket.get("assignee"))
            due_date = _parse_due_date(ticket.get("dueDate"))
            if assignee not in assignments or due_date is None or not monday <= due_date <= friday:
                continue
            assignments[assignee].append(ticket)

        for email, tasks in assignments.items():
            tasks.sort(key=lambda task: (str(task.get("dueDate") or ""), str(task.get("key") or "")))
            assignments[email] = tasks[:max_tasks_per_email]
        return assignments


def _assignee_email(value: object) -> str:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, dict):
        for field in ("email", "emailAddress"):
            candidate = value.get(field)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip().lower()
    return ""


def _parse_due_date(value: object) -> date | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None
