# DELTAS — SPEC-001 Blocker negation: ticket keys without separator and Spanish time qualifiers

**Status:** Draft — pending owner approval. No implementation, no deploy, no push until approved.

**Trigger (production, 2026-09-24 09:15 GT):** the owner submitted a blockers answer where every line was a per-ticket negation:

```text
TECH-17: Sin bloqueos
TECH-39: Sin bloqueos
TECH-40: Sin bloqueos
TECH-34: Sin bloqueos
```

Pulse published `@Eliab — bloqueo reportado por @Eliab` to the channel and stored `has_blockers = t` (standup id 15). Root cause of *this specific incident* is already fixed on `main` by `cd6ec5e` (line-by-line per-ticket judging) but that commit is **not deployed** — the running container predates it. This spec covers the remaining gaps so one deploy fixes everything tonight.

## Verified current behavior (main @ f05fe9a, probed 2026-09-24)

| Answer | Verdict today | Should be |
|---|---|---|
| `TECH-39: Sin bloqueos` | not a blocker ✓ | not a blocker |
| `TECH-17: Sin bloqueos\nTECH-39: Sesión bloqueada, falta definición` | blocker ✓ | blocker |
| `TECH-39 sin bloqueos` (no colon) | **blocker ✗** | not a blocker |
| `TECH-44: Nada por ahora` | **blocker ✗** | not a blocker |
| `TECH-34: Ninguno por hoy` | **blocker ✗** | not a blocker |
| `Sin bloqueos por ahora` | **blocker ✗** | not a blocker |
| `bloqueado por el ambiente de pruebas` | blocker ✓ | blocker (must stay) |

## Delta 001 — Ticket key without separator is still a per-ticket negation

**Objective:** a line that starts with a ticket key followed by a negation but **no separator** (`TECH-39 sin bloqueos`) is judged on what follows the key, exactly like the colon form.

**Files:** `app/src/blockers.py` (single regex), `app/tests/test_blockers.py`.

**Technical note:** `_TICKET_PREFIX` currently requires `[:：\-–—]` after the key. Accept separator OR whitespace (`\s*(?:[:：\-–—]\s*|\s+)`), never a bare boundary — `TECH-40abc` must not match. The strip is semantically safe because the key itself never asserts blocking; whatever remains decides the line. This is already true for the colon form (`TECH-40 Dar seguimiento a esto` → "dar seguimiento a esto" → still a blocker).

## Delta 002 — Spanish trailing time qualifiers are non-blocking qualifiers

**Objective:** mirror the existing English qualifier rule (`for now`, `today`, …) for the Spanish forms the team actually writes.

**Files:** same as Delta 001.

**Accepted qualifiers (exact phrases, never a `por .*` wildcard):**
`por ahora`, `por hoy`, `de momento`, `esta semana`, `por esta semana`, `todavía` / `aún` (with accents and ASCII forms).

Safety property to preserve: a qualifier is *stripped* before the no-blocker phrase check, and the remainder still decides. So `bloqueado hoy` → strip `hoy` → `bloqueado` → still a blocker. The strip can never turn a real blocker into a negation; it only lets `Nada por ahora` reach the `nada` phrase.

**Vocabulary dependency:** `nada`, `ninguno`, `ninguna`, `sin bloqueo(s)` are already in `_NO_BLOCKER_PHRASES`; this delta adds no new bare phrases except none required — qualifiers only.

## Delta 003 — Regression evidence for the owner's exact 4-ticket format

**Objective:** pin today's incident as a permanent test so it can never resurface silently.

**Files:** `app/tests/test_blockers.py`.

Add to `TestPerTicketMultilineAnswers`:

```python
OWNER_2026_09_24 = (
    "TECH-17: Sin bloqueos\nTECH-39: Sin bloqueos\n"
    "TECH-40: Sin bloqueos\nTECH-34: Sin bloqueos"
)
```

Asserts: `reports_a_blocker(OWNER_2026_09_24) is False`; `has_blockers(SPANISH_Q, [...]) is False`; and the mixed variant with one real blocker line still `True`.

## Non-goals

- No changes to question wording, modal, or the published update format.
- No LLM/NLP classification — deterministic rules only.
- No rewrite of historical DB rows: standup id 15 keeps `has_blockers = t` (it was the visible escalation that got us here). Optional owner decision later, out of scope.
- No deploy script changes. The fix ships inside the already-agreed release.

## Acceptance criteria

```yaml
- id: AC-1
  criterion: "TECH-39 sin bloqueos" (separator-less) is not a blocker
  test: reports_a_blocker('TECH-39 sin bloqueos') is False
- id: AC-2
  criterion: "TECH-44: Nada por ahora" and "TECH-34: Ninguno por hoy" are not blockers
  test: reports_a_blocker(...) is False for both
- id: AC-3
  criterion: "Sin bloqueos por ahora" (no ticket key) is not a blocker
  test: reports_a_blocker('Sin bloqueos por ahora') is False
- id: AC-4
  criterion: real blockers keep flagging, with and without ticket keys, with qualifiers present
  test: |
    reports_a_blocker('bloqueado por el ambiente de pruebas') is True
    reports_a_blocker('TECH-39: Sesión bloqueada, falta definición de requerimiento') is True
    reports_a_blocker('TECH-44: Esperando acceso, por ahora nada avanzado') is True
- id: AC-5
  criterion: "TECH-40abc" style concatenation does not strip (word boundary)
  test: reports_a_blocker('TECH-40abc nada') is True
- id: AC-6
  criterion: owner's exact 4-ticket 2026-09-24 format is not a blocker (regression pin)
  test: TestPerTicketMultilineAnswers::test_owner_2026_09_24_format
- id: AC-7
  criterion: English qualifier behavior unchanged
  test: existing TestNoBlockerPhrases pass untouched
```

## Judge gates (all must pass before commit)

```bash
cd /Users/openjaime/projects/morgenruf
python3 -m pytest app/tests/test_blockers.py -q        # focused
python3 -m pytest app/tests -q                          # full suite
ruff check app/src/blockers.py app/tests/test_blockers.py
ruff format --check app/src/blockers.py app/tests/test_blockers.py
git diff --check
```

## Deployment dependency (owner decision, tonight)

The incident of 2026-09-24 needs **both** `cd6ec5e` (already on main) and this spec's fix to be in the running image. One `deploy/deploy-techops.sh` run tonight covers both, together with the 09:00 owner health check (`26c0939`). After deploy: manual health-check DM + OK button round-trip as the post-deploy proof.

## Rollback

Single-file logic change + tests; `git revert` of the delta commit and redeploy restores behavior. No schema, no data, no config changes.
