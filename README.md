# Pulse

Async DSU (daily standup) bot for Slack with a ticket-aware Compass integration, a web dashboard, and scheduled reporting. Built for the TechOps pilot; self-hostable anywhere Docker runs.

**Based on [morgenruf](https://github.com/morgenruf/morgenruf)** — Pulse started as a fork of that MIT-licensed Slack standup app and evolved substantially: the free-text questionnaire became a guided, ticket-aware DSU flow wired into Compass, with its own worker architecture, safety gates and ops tooling.

## What Pulse does

The DM walks each participant through three steps: pick a primary focus (optionally a secondary one) from your current sprint tickets, write a short update per ticket, and review before posting. Every published update keeps the ticket's human context — verified portal link, key and title — and the bot refuses key-only or title-only answers, so an update always says something the ticket does not.

On submission, the DSU is:

- posted to the standup channel as a structured summary,
- delivered as comments on each Compass ticket by a background worker,
- recorded in Postgres for the dashboard (who answered, who is blocked, participation history).

**Compass integration is updates-only.** It can publish `post_comment` on a ticket and nothing else — it never changes status, priority, assignee, sprint, dates or visibility. Ticket links are verified against the portal URL pattern; the bot never invents a link from a key.

Design decisions live in two specs:

- [`openspec/SPEC-002-guided-ticket-aware-dsu.md`](openspec/SPEC-002-guided-ticket-aware-dsu.md) — the three-step guided wizard with sprint-ticket context
- [`openspec/SPEC-004-dual-focus-enterprise-dsu.md`](openspec/SPEC-004-dual-focus-enterprise-dsu.md) — dual-focus selection (one mandatory primary focus, one optional secondary) with structured Slack publishing

## Architecture highlights

- **Workers over daemon.** Compass is reached only from short-lived worker processes, never from the always-on app daemon: `deploy/run-compass-context-worker.sh` refreshes read-only sprint snapshots for the DM, `deploy/run-compass-comment-worker.sh` delivers queued comments. Both read the Compass API key from the host keychain at launch; the daemon holds no credential.
- **Mock mode for rehearsals.** `PULSE_COMPASS_WRITE_MODE=mock` (opt-in, never a default) records Compass writes locally instead of sending them. The trial script refuses to run without it; the production worker always runs with the variable cleared.
- **Fail-open snapshot refresh.** The respond button re-checks Compass synchronously with a 10-second cap; on timeout the wizard renders with the existing snapshot.
- **Watchdog.** `deploy/check-compass-dsu-endpoints.sh` verifies public ingress from the outside (check-host.net quorum) and stays silent unless a completed quorum fails. Its repair is bounded and always re-proven externally.

## Quick start

```bash
git clone https://github.com/EliabLemus/pulse.git
cd pulse/app
cp .env.example .env            # Slack credentials and APP_URL go in here
docker compose up -d
```

Slack needs to reach the app over HTTPS; while testing, `cloudflared tunnel --url http://localhost:3000` and set that URL as `APP_URL`.

Full operator procedures: [RUNBOOK.md](RUNBOOK.md) and [deploy/README.md](deploy/README.md).

## Requirements

- Docker and Docker Compose
- A Slack workspace where you can install an app
- Optional: a Compass instance + API key for the ticket-aware DSU flow

## Tests

```bash
uv venv .venv && uv pip install -r app/requirements.txt pytest pytest-mock ruff
.venv/bin/python -m pytest app/tests -q
.venv/bin/ruff check . && .venv/bin/ruff format . --check
```

## Inherited from upstream

The fork retains the upstream modules (standups, coffee chats, kudos, celebrations, insights) and the MCP server; see the [upstream README](https://github.com/morgenruf/morgenruf#readme) for those features' full documentation.

## License

[MIT](LICENSE) — carries the upstream Morgenruf Contributors copyright notice, as required by the license.
