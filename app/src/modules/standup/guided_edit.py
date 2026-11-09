"""Guided edit mode: rebuild the per-ticket wizard from a stored submission.

A guided DSU stores its answers in the standup row with ``TICKET-KEY: text``
prefixes (one line per ticket). Editing must never fall back to the legacy
three-question editor, which would destroy that per-ticket format. This module
parses those fields back into the wizard's ``wizard_answers`` shape so the same
guided steps reopen pre-filled. Lines that do not carry a recognizable ticket
prefix are kept as free-text entries instead of being dropped.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# A ticket key like TECH-163, OPS-42: an alphanumeric prefix, a dash and a
# number, followed by ": " and the answer text.
_TICKET_LINE_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9_]*-\d+)\s*:\s*(.*)$")
# The canonical no-progress wording written by the guided wizard.
_SIN_AVANCES_RE = re.compile(r"^\s*_?sin\s+avances hoy_?\s*$", re.IGNORECASE)

FREE_TEXT_KEY_BASE = "NOTA"


def _is_sin_avances(text: str) -> bool:
    return bool(_SIN_AVANCES_RE.match(text.strip()))


def parse_progress_lines(text: str) -> list[dict[str, Any]]:
    """Split a ``TICKET-KEY: answer`` block into per-ticket entries.

    One entry per line: ``{ticket_key, ticket_title, answer, blocked}``.
    Lines without a ticket prefix become entries with ``ticket_key=None`` so
    free-text rows survive the round trip.
    """
    entries: list[dict[str, Any]] = []
    for line in str(text or "").splitlines():
        if not line.strip():
            continue
        match = _TICKET_LINE_RE.match(line)
        if match:
            key, answer = match.group(1), match.group(2).strip()
            blocked = _is_sin_avances(answer)
            entries.append({"ticket_key": key, "ticket_title": "", "answer": "" if blocked else answer, "blocked": blocked})
        else:
            entries.append({"ticket_key": None, "ticket_title": "", "answer": line.strip(), "blocked": False})
    return entries


def parse_focus_lines(text: str) -> list[dict[str, str]]:
    """Split the ``TICKET-KEY: goal`` focus block into focus items."""
    items: list[dict[str, str]] = []
    for line in str(text or "").splitlines():
        if not line.strip():
            continue
        match = _TICKET_LINE_RE.match(line)
        if match:
            items.append({"key": match.group(1), "goal": match.group(2).strip()})
        else:
            items.append({"key": "other", "goal": line.strip()})
    return items


def rebuild_guided_edit(standup_row: dict, snapshot_tasks: list[dict]) -> dict[str, Any] | None:
    """Rebuild wizard state for editing a stored guided submission.

    Returns ``None`` when nothing could be recovered. ``snapshot_tasks`` are
    the fresh Compass sprint tasks; every parsed ticket key missing from the
    snapshot gets a minimal task entry so its step-0 field still renders.
    """
    if not isinstance(standup_row, dict):
        return None
    progress_entries = parse_progress_lines(standup_row.get("yesterday") or "")
    focus_items = parse_focus_lines(standup_row.get("today") or "")
    blockers_text = str(standup_row.get("blockers") or "")
    if not progress_entries and not focus_items and not blockers_text.strip():
        return None

    tasks_by_key = {str(task.get("key") or ""): dict(task) for task in snapshot_tasks if task.get("key")}
    extra_index = 0
    entries: list[dict[str, Any]] = []
    for entry in progress_entries:
        key = entry.get("ticket_key")
        if key and key not in tasks_by_key:
            extra_index += 1
            tasks_by_key[key] = {"key": key, "title": ""}
        if key is None:
            extra_index += 1
            key = f"{FREE_TEXT_KEY_BASE}-{extra_index}"
            entry = {**entry, "ticket_key": key}
            tasks_by_key[key] = {"key": key, "title": "Nota libre"}
        entry.setdefault("ticket_title", str(tasks_by_key.get(key, {}).get("title") or ""))
        entries.append(entry)
    for item in focus_items:
        key = item.get("key") or ""
        if key and key != "other" and key not in tasks_by_key:
            tasks_by_key[key] = {"key": key, "title": ""}

    progress: dict[str, str] = {}
    sin_avances: list[str] = []
    for entry in entries:
        key = str(entry.get("ticket_key") or "")
        if entry.get("blocked"):
            sin_avances.append(key)
        elif str(entry.get("answer") or "").strip():
            progress[key] = str(entry["answer"])

    return {
        "compass_tasks": list(tasks_by_key.values()),
        "wizard_answers": {
            "progress": progress,
            "sin_avances": sin_avances,
            "sin_avances_resto": [],
            "focus_items": [item for item in focus_items if item.get("goal")],
            "blockers": blockers_text,
        },
        "entries": entries,
    }


def changed_guided_comments(previous_entries: list[dict], comments: list[dict[str, str]]) -> list[dict[str, str]]:
    """Keep only comment jobs whose ticket answer text actually changed.

    ``previous_entries`` are the per-ticket entries captured when the edit
    session was opened; ``comments`` are the freshly built jobs.
    """
    previous: dict[str, str] = {}
    for entry in previous_entries or []:
        key = str(entry.get("ticket_key") or "")
        if not key:
            continue
        previous[key] = "Sin avances hoy" if entry.get("blocked") else str(entry.get("answer") or "")
    changed: list[dict[str, str]] = []
    for comment in comments or []:
        key = str(comment.get("ticket_key") or "")
        body = str(comment.get("body") or "").split("\n", 1)[-1]
        if previous.get(key, "") != body:
            changed.append(comment)
    return changed
