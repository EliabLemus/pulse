# Tasks: refresh-guided-tasks-and-blockers

TDD, one vertical slice per check. Each implementation task is done only after
its red test is shown failing.

## 1. OpenSpec delta

- [x] Write `proposal.md`, `tasks.md`, `specs/guided-dsu/spec.md` with real
      symbols and WHEN/THEN scenarios including the accepted pre-mortem cases.

## 2. Refresh before routing (`handlers.py`)

- [x] RED: fresh-empty session + refresh returns tasks → `fill_in_form` opens
      `guided_standup_modal` (AC1).
- [x] RED: refresh invoked from `fill_in_form` respects a ≤2 s cap and opens
      the modal from existing data when the refresh hangs/fails (AC2).
- [x] RED: empty→non-empty refresh resets `started_at` before saving so the
      first guided submission does not TTL-expire (AC3).
- [x] GREEN: minimal implementation in `handle_fill_in_form` +
      `_refresh_session_compass_tasks(timeout=...)`.
- [x] Guard tests: still-empty session → legacy modal; sessions without
      Compass context never trigger a refresh.

## 3. Step-2 `Sin bloqueos` control (`blocks.py` + `handlers.py`)

- [x] RED: step 2 renders selected `no_blockers_toggle` checkbox and no
      `blockers` free-text block by default (AC4).
- [x] RED: `no_blockers_toggle` block action ack()s and views_update()s the
      same modal; uncheck shows the field, recheck hides it (AC4).
- [x] RED: final submit checked → stores exactly `Sin bloqueos` and
      `reports_a_blocker(...)` is false (AC5).
- [x] RED: final submit unchecked + whitespace → validation error on the
      `blockers` field, nothing stored (AC5).
- [x] RED: final submit unchecked + substantive text → stores the text (AC5).
- [x] RED: toggles and Back/Forward preserve other answers, the check state
      and the typed blocker draft (AC5).
- [x] Guard: checkbox absent from the submitted payload (pre-deploy modal)
      keeps the previous behavior.
- [x] GREEN: minimal implementation in `guided_standup_modal`,
      `handle_guided_standup_submit`, new `no_blockers_toggle` action,
      `handle_guided_back`.

## 4. Guided edit (AC6)

- [x] RED: guided edit of a stored canonical `Sin bloqueos` reopens step 2
      checked with no free-text input; a stored real blocker reopens unchecked
      with the text.

## 5. Gates

- [x] Focused suites green (73) + `test_blockers.py` green (31) = 104 passed;
      full `app/tests`: failure set byte-identical to the clean base
      (`diff` of sorted FAILED lists: IDENTICAL; 75 pre-existing failures in
      unrelated modules, +18 new passing tests, 0 new failures).
- [x] `ruff check .` clean (exit 0); `ruff format --check` clean for every
      file this change touches (the one remaining unformatted file,
      `app/tests/test_ticket_comment_body.py`, is untouched by this diff —
      pre-existing); `git diff --check` clean.
- [x] Conventional commit on the assigned branch; no push.
