"""Conversation state — tracks each user's active standup session.

Per-workspace persistent data (members, standups) lives in PostgreSQL via db.py.
Active DM conversation state is stored in Redis (with in-memory fallback) via
session_store so sessions survive pod restarts.
Cache keys are `team_id:user_id` to support multi-workspace.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Optional

import src.core.session_store as session_store

QUESTIONS = [
    "✅ *What did you complete yesterday?*\n> List by project (e.g. `Proj-Bridj: deployed TF module`)",
    "🎯 *What are you working on today?*\n> List by project",
    "🚧 *Any blockers?*\n> Type `none` if you're clear",
]


# ---------------------------------------------------------------- Compass context state
#
# Pure classifier, no feature-module imports: core owns the vocabulary so both
# the scheduler and the standup handlers can derive a session's rendering
# state without core depending on src.modules.*.


def context_state(tasks: list, *, unavailable: bool = False) -> str:
    """Map a Compass context read onto the session's explicit rendering state.

    Exactly one of three values: ``fresh_with_tasks`` (snapshot available and
    non-empty), ``fresh_empty`` (snapshot available, zero tasks) or
    ``unavailable`` (missing, stale or failed read). Explicit unavailability
    wins over any task list so a stale snapshot never renders tickets.
    """
    if unavailable:
        return "unavailable"
    return "fresh_with_tasks" if tasks else "fresh_empty"


@dataclass
class UserSession:
    cache_key: str  # "team_id:user_id"
    team_id: str
    channel: str  # target channel for the summary post
    step: int = 0  # 0=sent q1, 1=sent q2, 2=sent q3, 3=mood, 4=done
    answers: list[str] = field(default_factory=list)
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    questions: list[str] = field(default_factory=lambda: list(QUESTIONS))
    standup_name: str = "Team Standup"
    schedule_id: Optional[int] = None  # source schedule — avoids channel-based lookup ambiguity
    editing_standup_id: Optional[int] = None  # set when user is editing an existing submission
    edit_initial_answers: list[str] = field(default_factory=list)  # pre-fill text for each question
    compass_tasks: list[dict] = field(default_factory=list)  # open tasks rendered in the guided DSU
    # Explicit Compass context health at session start. The dataclass default
    # is the empty sentinel so directly-constructed old/test sessions (no
    # explicit state) keep the legacy rendering path; _deserialize and
    # StateStore.start map real/legacy payloads onto an explicit value.
    compass_context_state: str = ""
    wizard_step: int = 0  # 0=progress, 1=priority, 2=blockers
    wizard_answers: dict = field(default_factory=dict)  # partial values retained across modal navigation
    guided_submission_id: Optional[int] = None  # durable root delivery pending during finalisation

    @property
    def user_id(self) -> str:
        return self.cache_key.split(":", 1)[-1]


def _serialize(session: "UserSession") -> dict:
    return {
        "cache_key": session.cache_key,
        "team_id": session.team_id,
        "channel": session.channel,
        "step": session.step,
        "answers": session.answers,
        "questions": session.questions,
        "standup_name": session.standup_name,
        "schedule_id": session.schedule_id,
        "editing_standup_id": session.editing_standup_id,
        "edit_initial_answers": session.edit_initial_answers,
        "compass_tasks": session.compass_tasks,
        "compass_context_state": session.compass_context_state,
        "wizard_step": session.wizard_step,
        "wizard_answers": session.wizard_answers,
        "guided_submission_id": session.guided_submission_id,
        "started_at": session.started_at.isoformat(),
    }


def _parse_started_at(value: object) -> datetime:
    """The stored start time. A session written before it was stored reads as now."""
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _deserialize(data: dict) -> "UserSession":
    return UserSession(
        cache_key=data["cache_key"],
        team_id=data.get("team_id", ""),
        channel=data.get("channel", ""),
        step=data.get("step", 0),
        answers=data.get("answers", []),
        questions=data.get("questions", list(QUESTIONS)),
        standup_name=data.get("standup_name", "Team Standup"),
        schedule_id=data.get("schedule_id"),
        editing_standup_id=data.get("editing_standup_id"),
        edit_initial_answers=data.get("edit_initial_answers") or [],
        compass_tasks=data.get("compass_tasks") or [],
        compass_context_state=data.get("compass_context_state", "unavailable"),
        wizard_step=data.get("wizard_step", 0),
        wizard_answers=data.get("wizard_answers") or {},
        guided_submission_id=data.get("guided_submission_id"),
        started_at=_parse_started_at(data.get("started_at")),
    )


# How long an open session for one standup holds off the DM for another.
OTHER_STANDUP_BLOCK = timedelta(hours=4)

# A guided wizard step left open this long is expired: the sprint snapshot it
# was built from is stale, so submitting would post progress against tickets
# that may have moved. The next wizard interaction tells the user to restart.
# 20 hours, not 30 minutes: a session opened at 09:15 must survive answering
# after lunch without losing everything typed. It still expires before the
# next day's standup fires, which is what the staleness argument is about.
GUIDED_WIZARD_TTL = timedelta(hours=20)


class StateStore:
    """Redis-backed store for active standup DM conversations (in-memory fallback)."""

    def __init__(self) -> None:
        self._lock = Lock()

    def start(
        self,
        cache_key: str,
        channel: str,
        *,
        team_id: str = "",
        questions: list[str] | None = None,
        standup_name: str = "Team Standup",
        schedule_id: Optional[int] = None,
        editing_standup_id: Optional[int] = None,
        edit_initial_answers: Optional[list[str]] = None,
        compass_tasks: Optional[list[dict]] = None,
        compass_context_state: str = "unavailable",
    ) -> UserSession:
        """Begin a new standup session. cache_key should be 'team_id:user_id'."""
        if not team_id:
            # Derive team_id from cache_key when not provided explicitly
            team_id = cache_key.split(":", 1)[0] if ":" in cache_key else ""
        with self._lock:
            session = UserSession(
                cache_key=cache_key,
                team_id=team_id,
                channel=channel,
                questions=list(questions) if questions is not None else list(QUESTIONS),
                standup_name=standup_name,
                schedule_id=schedule_id,
                editing_standup_id=editing_standup_id,
                edit_initial_answers=list(edit_initial_answers) if edit_initial_answers else [],
                compass_tasks=[dict(task) for task in compass_tasks] if compass_tasks else [],
                compass_context_state=compass_context_state or "unavailable",
            )
            session_store.set_session(cache_key, _serialize(session))
            return session

    def get(self, cache_key: str) -> Optional[UserSession]:
        data = session_store.get_session(cache_key)
        return _deserialize(data) if data else None

    def guided_wizard_expired(self, cache_key: str, now: datetime | None = None) -> bool:
        """Whether a guided wizard session has sat past GUIDED_WIZARD_TTL.

        Only a session carrying Compass tasks can expire this way: it renders
        a sprint snapshot whose tickets may have moved since it was captured.
        A plain DM session never expires here.
        """
        session = self.get(cache_key)
        if session is None or not session.compass_tasks:
            return False
        now = now or datetime.now(timezone.utc)
        return now - session.started_at >= GUIDED_WIZARD_TTL

    def clear_guided_wizard_if_expired(self, cache_key: str, now: datetime | None = None) -> bool:
        """Drop an expired guided wizard and report whether that happened.

        Returns True when the session was expired and removed, so the caller
        can send the recovery message exactly once.
        """
        if not self.guided_wizard_expired(cache_key, now=now):
            return False
        self.clear(cache_key)
        return True

    def record_answer(self, cache_key: str, answer: str) -> Optional[UserSession]:
        with self._lock:
            data = session_store.get_session(cache_key)
            if not data:
                return None
            session = _deserialize(data)
            session.answers.append(answer)
            session.step += 1
            session_store.set_session(cache_key, _serialize(session))
            return session

    def save(self, session: UserSession) -> UserSession:
        """Persist a session after an atomic in-process update."""
        with self._lock:
            session_store.set_session(session.cache_key, _serialize(session))
            return session

    def clear(self, cache_key: str) -> None:
        session_store.delete_session(cache_key)

    def is_active(self, cache_key: str) -> bool:
        return session_store.has_session(cache_key)

    def blocks_scheduled_dm(self, cache_key: str, schedule_id: Optional[int], now: datetime | None = None) -> bool:
        """Whether an open session should stop a scheduled standup DM.

        A session for the same standup is still in progress, so it is left
        alone (the DM job's own retries hit this). A session for another
        standup blocks only while it is recent, which is what the old 4 hour
        TTL gave. Sessions now live for a working day, and without this an
        abandoned morning standup would have swallowed the evening one.
        """
        session = self.get(cache_key)
        if session is None:
            return False
        if schedule_id is not None and session.schedule_id == schedule_id:
            return True
        now = now or datetime.now(timezone.utc)
        return now - session.started_at < OTHER_STANDUP_BLOCK


state_store = StateStore()
