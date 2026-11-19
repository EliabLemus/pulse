# guided-dsu — delta spec (refresh-guided-tasks-and-blockers)

## ADDED Requirements

### Requirement: refresh sprint context before the fill_in_form routing decision

The Slack `fill_in_form` action ("Completar mi avance") SHALL attempt a Compass
snapshot refresh **before** choosing between the guided wizard and the legacy
form whenever the session is known to carry Compass context — that is, the
session has `compass_tasks` or `compass_context_state == "fresh_empty"`.

#### Scenario: fresh-empty session gains tasks on click

- **WHEN** a session has `compass_tasks == []` and
  `compass_context_state == "fresh_empty"`, and the member clicks
  `fill_in_form`, and the refresh returns open sprint tasks
- **THEN** `handle_fill_in_form` opens `guided_standup_modal` at the session's
  `wizard_step` (0 for a fresh session), not `standup_form_modal`.

#### Scenario: still-empty session stays legacy

- **WHEN** the refreshed snapshot for such a session still has zero tasks
- **THEN** the legacy `standup_form_modal` opens with the session's existing
  prefill behavior, unchanged.

#### Scenario: sessions without Compass context do not refresh

- **WHEN** a session has no `compass_tasks` and a `compass_context_state`
  other than `fresh_empty` (empty or `unavailable`)
- **THEN** no refresh is attempted and the legacy form opens as before.

#### Scenario: trigger_id latency cap

- **WHEN** the refresh invoked from `fill_in_form` hangs or fails
- **THEN** it is abandoned after at most 2 seconds
  (`_refresh_session_compass_tasks(..., timeout=2)`), the modal still opens
  from the session's existing data, and `_start_standup_session` keeps its
  10-second cap.

#### Scenario: TTL reset on empty → non-empty

- **WHEN** `_refresh_session_compass_tasks` moves a session from zero tasks to
  one or more tasks
- **THEN** `session.started_at` is reset to the refresh time before the
  session is saved, so `clear_guided_wizard_if_expired` does not expire the
  wizard at its first submission for age alone.

### Requirement: checked-by-default `Sin bloqueos` control on the blockers step

The guided wizard step 2 (blockers) SHALL render a checkbox with a unique
action id `no_blockers_toggle` (block `no_blockers`, option value
`no_blockers`, visible label "Sin bloqueos"), selected by default, and SHALL
NOT render the free-text `blockers` input while it is selected.

#### Scenario: default render

- **WHEN** `guided_standup_modal(..., step=2, answers={})` is built
- **THEN** the `no_blockers` checkbox is present with
  `initial_options` selected, its element `action_id` is
  `no_blockers_toggle`, and no block with `block_id == "blockers"` exists.

#### Scenario: uncheck shows the field, recheck hides it

- **WHEN** the member toggles the checkbox
- **THEN** the `no_blockers_toggle` block action `ack()`s and calls
  `views_update` on the same view (never a submit-only `response_action`):
  unchecked rerenders step 2 with the free-text `blockers` input prefilled
  with the preserved draft; checked rerenders without it.

#### Scenario: checked submission stores the canonical phrase

- **WHEN** step 2 is submitted with the checkbox selected
- **THEN** the persisted blocker answer is exactly `Sin bloqueos` and
  `reports_a_blocker("Sin bloqueos")` is false, so the channel summary shows
  "Sin bloqueos" and no `Bloqueos` section.

#### Scenario: unchecked requires substantive text

- **WHEN** step 2 is submitted with the checkbox unselected and the text field
  empty or whitespace-only
- **THEN** the submission is rejected with a validation error on the
  `blockers` field and nothing is stored.

#### Scenario: unchecked substantive text persists

- **WHEN** step 2 is submitted with the checkbox unselected and substantive
  text in the field
- **THEN** the text is persisted as the blocker answer and the channel summary
  reports a blocker.

#### Scenario: state survives toggles and Back/Forward

- **WHEN** the member types a blocker draft, toggles the checkbox any number
  of times, or navigates Back from step 2 and Forward again
- **THEN** other wizard answers are preserved, the checkbox state round-trips,
  and the typed draft is still in the field when it is shown again; a real
  typed blocker never silently becomes "no blockers".

#### Scenario: pre-deploy modal without the checkbox

- **WHEN** step 2 is submitted from a modal that has no `no_blockers` block
  (opened before this change)
- **THEN** the free-text answer is stored as typed, as before.

#### Scenario: guided edit of a stored canonical no-blocker

- **WHEN** guided edit reopens a submission whose stored blockers field is
  exactly `Sin bloqueos` and the member reaches step 2
- **THEN** the checkbox is selected and no free-text input is rendered; a
  stored real blocker instead renders the checkbox unselected with the text.
