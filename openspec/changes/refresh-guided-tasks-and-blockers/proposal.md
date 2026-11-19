# Proposal: refresh-guided-tasks-and-blockers

## Why

Two UX gaps in the Compass DSU flow:

1. A session whose morning snapshot came back **fresh-empty** (Compass reachable,
   zero open sprint tasks) stays empty for the whole day. When the member clicks
   `fill_in_form` ("Completar mi avance") hours later — after tickets moved to
   in-progress — the routing check `if session.compass_tasks` still sees `[]` and
   opens the **legacy** three-field modal. The member then cannot report
   per-ticket progress at all.
2. The guided wizard's step 2 (blockers) shows only a free-text field with the
   hint "escribe `ninguno`". Most days there are no blockers, so the common case
   is typing a negation by hand, and typo'd negations historically get counted
   as blockers by `src/modules/standup/blockers.py`.

## What Changes

### 1. Refresh before routing in `fill_in_form`

- `handle_fill_in_form` decides guided vs legacy **after** attempting a Compass
  snapshot refresh for any session known to carry Compass context: one with
  `compass_tasks` **or** `compass_context_state == "fresh_empty"`.
- Because this path owns a Slack `trigger_id` (~3 s to call `views_open`), the
  refresh invoked here is capped at **2 seconds** (`_refresh_session_compass_tasks(..., timeout=2)`),
  fail-open: on timeout/error the modal opens from existing session data.
- `_start_standup_session` keeps its existing 10-second cap.
- Sessions with no Compass context (`compass_context_state` empty/`unavailable`
  and no tasks) never refresh and keep the legacy path.
- A still-empty session after refresh opens the legacy modal exactly as before.

### 2. TTL reset on empty → non-empty transition

`_refresh_session_compass_tasks` resets `session.started_at` (before saving)
when a session that had **no** tasks receives **tasks**. Otherwise the wizard
opened from a morning DM would immediately TTL-expire (`GUIDED_WIZARD_TTL`,
20 h) at its first submission.

### 3. Checked-by-default `Sin bloqueos` control on step 2

- Step 2 renders a checkbox (block `no_blockers`, action id
  `no_blockers_toggle`, option value `no_blockers`, label "Sin bloqueos")
  **selected by default**, with **no** free-text `blockers` input on screen.
- Unchecking dispatches a block action: the handler `ack()`s and
  `views_update`s the **same** modal with the free-text field visible,
  pre-filled with the preserved draft. Checking again collapses the field.
- The checkbox state and the typed draft persist in `wizard_answers`
  (`no_blockers`, `blockers`) across toggles and Back/Forward navigation;
  other answers are untouched.
- Final submission from step 2:
  - checkbox present + checked → stores exactly `Sin bloqueos`
    (`reports_a_blocker` is false);
  - checkbox present + unchecked + empty/whitespace text → field validation
    error, nothing stored;
  - checkbox present + unchecked + substantive text → stores the text;
  - checkbox absent (pre-deploy modal still open) → previous behavior, text
    as typed.
- Guided edit of a stored canonical `Sin bloqueos` reopens step 2 checked with
  no text field (derivation: unchecked only when the stored draft actually
  reports a blocker).

## Impact

Files touched: `app/src/modules/standup/handlers.py`, `blocks.py`,
`guided_edit.py` (only if needed for edit derivation — expected: no change),
`blockers.py` (expected: no change), plus tests and this OpenSpec change.
No Compass ticket mutations, no legacy (non-guided) blocker form changes, no
external calls, no Slack sends beyond existing modal update calls.

## Risks / pre-mortem (accepted cases)

- **Timeout cap**: a slow Compass read must not eat the `trigger_id` window →
  2 s cap, fail-open to existing data (AC2).
- **TTL**: empty→non-empty must not inherit the morning `started_at`, or the
  first submission silently expires (AC3).
- **Action id collision**: generic `value` would collide with per-ticket
  checkbox actions → unique `no_blockers_toggle` (AC4).
- **Canonical phrase**: checked stores exactly `Sin bloqueos`; `blockers.py`
  already lists `sin bloqueos` as a no-blocker phrase so `reports_a_blocker`
  is false (AC5).
- **Silent no-blocker**: Back/Forward must carry the check state so a real
  typed blocker never collapses into "no blockers" (AC5).
- **Guided edit**: stored canonical `Sin bloqueos` must reopen checked with no
  text field (AC6).
