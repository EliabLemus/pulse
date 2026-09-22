"""Read-only Compass MCP client for optional Pulse DM context."""

from __future__ import annotations

import json
import logging
import os
from typing import Any
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


    def active_sprint_assignments(
        self,
        emails: list[str],
        *,
        team: str,
        max_tasks_per_email: int = 5,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return open active-sprint work, grouped by normalized assignee email."""
        normalized = {email.strip().lower() for email in emails if isinstance(email, str) and email.strip()}
        assignments: dict[str, list[dict[str, Any]]] = {email: [] for email in normalized}
        if not assignments:
            return assignments

        response = _mcp_text_json(self._call_mcp("get_active_sprint", {"team": team}))
        if response.get("active") is not True:
            return assignments

        for task in response.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            assignee = _assignee_email(task.get("assigneeEmail") or task.get("assignee"))
            if assignee not in assignments or str(task.get("statusCategory") or "").lower() not in {
                "todo",
                "active",
                "blocked",
            }:
                continue
            assignments[assignee].append(task)

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


def _mcp_text_json(result: dict[str, Any]) -> dict[str, Any]:
    """Extract one JSON object from a successful MCP text response."""
    for item in result.get("content") or []:
        if not isinstance(item, dict) or item.get("type") != "text" or not isinstance(item.get("text"), str):
            continue
        try:
            payload = json.loads(item["text"])
        except json.JSONDecodeError as exc:
            raise ValueError("Compass returned invalid MCP JSON") from exc
        if isinstance(payload, dict):
            return payload
        break
    raise ValueError("Compass returned no JSON MCP payload")
