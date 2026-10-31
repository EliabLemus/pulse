"""Read-only Compass MCP client and deterministic ticket-text validation."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)


class CompassPreFlightError(RuntimeError):
    """The request never reached Compass, so nothing was applied.

    Connection refused, DNS failure, and any HTTP error status returned
    before Compass acknowledged the tool call. Retrying is always safe
    because no write happened.
    """


class CompassPostFlightError(RuntimeError):
    """The request was sent but the outcome cannot be known (e.g. timeout).

    Retrying could duplicate a comment, so callers must treat this as an
    unknown outcome and never re-send.
    """

COMPASS_WEB_BASE_URL = "https://compass.zubale.com"
_PORTAL_TASK_URL_RE = re.compile(
    rf"^{re.escape(COMPASS_WEB_BASE_URL)}/(?:v2/)?portal/tasks/"
    r"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}$",
)


def portal_task_url(task: dict[str, Any]) -> str:
    """Return a verified Compass portal URL, never inventing one from a key."""
    url = task.get("url")
    if isinstance(url, str) and _PORTAL_TASK_URL_RE.fullmatch(url):
        return url
    return ""


def is_substantive_ticket_text(value: str, task: dict[str, Any]) -> bool:
    """Reject content that only repeats the visible ticket identity.

    The bot does not attempt to grade a human update. It only rejects blank,
    punctuation-only, key-only, title-only, and key-plus-title submissions.
    """
    normalized = _normalise_display_text(value)
    if not normalized or not any(char.isalnum() for char in normalized):
        return False
    key = _normalise_display_text(str(task.get("key") or ""))
    title = _normalise_display_text(str(task.get("title") or ""))
    identities = {identity for identity in (key, title, f"{key} {title}".strip()) if identity}
    return normalized not in identities


def _normalise_display_text(value: str) -> str:
    folded = " ".join(value.casefold().split())
    return " ".join(re.sub(r"[^\w\s]+", " ", folded, flags=re.UNICODE).split())


class CompassClient:
    """Use Compass MCP without mutating ticket workflow fields."""

    def __init__(self, api_key: str, *, timeout_seconds: int = 10, connection_attempts: int = 3) -> None:
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._connection_attempts = max(1, int(connection_attempts))
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
        attempts = self._connection_attempts
        for attempt in range(1, attempts + 1):
            try:
                with urlopen(request, timeout=self._timeout_seconds) as response:
                    payload = json.load(response)
            except HTTPError as exc:
                # Compass answered with an HTTP error status before the tool
                # call could be applied, so this is a pre-flight failure and a
                # retry is safe. Protocol-level errors inside a 200 (below)
                # are valid responses and are never retried.
                raise CompassPreFlightError(f"Compass HTTP {exc.code} for {tool_name}") from exc
            except URLError as exc:
                # DNS resolution and connection refused happen before the
                # request is sent. A read timeout after the send is a socket
                # timeout instead, handled below.
                if isinstance(getattr(exc, "reason", None), TimeoutError):
                    if attempt < attempts:
                        _sleep_backoff(attempt)
                        continue
                    raise CompassPostFlightError(f"Compass timeout after send for {tool_name}") from exc
                if attempt < attempts:
                    _sleep_backoff(attempt)
                    continue
                raise CompassPreFlightError(f"Compass unreachable for {tool_name}: {exc.reason}") from exc
            except TimeoutError as exc:
                # The request left the process but no response arrived; the
                # tool call may have been applied, so this is ambiguous.
                raise CompassPostFlightError(f"Compass timeout after send for {tool_name}") from exc
            if not isinstance(payload, dict) or payload.get("error"):
                raise ValueError("Compass rejected the MCP tool call")
            result = payload.get("result")
            if not isinstance(result, dict):
                raise ValueError("Compass returned an invalid MCP tool result")
            return result
        raise CompassPostFlightError(f"Compass unreachable for {tool_name}")  # pragma: no cover

    def get_ticket(self, key: str) -> dict[str, Any]:
        """Read one ticket for submit-time status validation."""
        if not key.strip():
            raise ValueError("Compass ticket key is required")
        payload = _mcp_text_json(self._call_mcp("get_ticket", {"key": key.strip()}))
        if not isinstance(payload.get("key"), str):
            raise ValueError("Compass returned an invalid ticket")
        return payload

    def post_comment(self, key: str, body: str) -> None:
        """Append a human-authored progress comment without mutating ticket fields.

        ``PULSE_COMPASS_WRITE_MODE=mock`` is an opt-in rehearsal seam. It
        records the attempted write locally in logs but never contacts Compass.
        Production deployments explicitly strip that environment variable.
        """
        normalized_key = key.strip()
        normalized_body = body.strip()
        if not normalized_key:
            raise ValueError("Compass ticket key is required")
        if not normalized_body:
            raise ValueError("Compass comment body is required")
        if os.environ.get("PULSE_COMPASS_WRITE_MODE", "").strip().lower() == "mock":
            logger.warning("PULSE_COMPASS_MOCK_COMMENT key=%s body=%s", normalized_key, normalized_body)
            return
        self._call_mcp("post_comment", {"key": normalized_key, "body": normalized_body})

    def active_sprint_assignments(
        self,
        emails: list[str],
        *,
        team: str,
        max_tasks_per_email: int = 5,
    ) -> dict[str, Any]:
        """Return open sprint tasks grouped by normalized assignee email."""
        normalized = {email.strip().lower() for email in emails if isinstance(email, str) and email.strip()}
        assignments: dict[str, list[dict[str, Any]]] = {email: [] for email in normalized}
        if not assignments:
            return assignments

        response = _mcp_text_json(self._call_mcp("get_active_sprint", {"team": team}))
        if response.get("active") is not True:
            return assignments

        context: dict[str, Any] = dict(assignments)
        sprint = response.get("sprint")
        if isinstance(sprint, dict) and isinstance(sprint.get("name"), str) and sprint["name"].strip():
            context["sprint_name"] = sprint["name"].strip()

        for task in response.get("tasks") or []:
            if not isinstance(task, dict):
                continue
            assignee = _assignee_email(task.get("assigneeEmail") or task.get("assignee"))
            category = str(task.get("statusCategory") or "").strip().lower()
            if assignee not in assignments or category != "active":
                continue
            assignments[assignee].append(task)

        for email, tasks in assignments.items():
            tasks.sort(key=lambda task: (str(task.get("dueDate") or ""), str(task.get("key") or "")))
            assignments[email] = tasks[:max_tasks_per_email]
        context.update(assignments)
        return context


def _sleep_backoff(attempt: int) -> None:
    """Exponential backoff between connection retries: 1s, 2s, 4s, ..."""
    time.sleep(2 ** (attempt - 1))


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
