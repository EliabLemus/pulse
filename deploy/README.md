# Pulse TechOps pilot deployment

This package deploys the local Pulse fork as a small, isolated Docker Compose
project. It never uses the upstream `morgenruf/morgenruf:latest` image.

## What it creates

- `pulse-techops` Compose project, scoped so rollback cannot affect other stacks.
- `pulse-techops-postgres` named volume for pilot data.
- a local image built from `../app`.
- a one-shot migration job before the app starts.
- an idempotent seed of one workspace, one participant, and one schedule:
  - L/M/J/V at 09:15, `America/Guatemala`
  - pending reminders at 09:45, 10:15, and 10:45
  - window close at 11:00
  - immediate posts in the configured private channel

It does **not** create a Slack app, invite the bot, alter Caddy, or contact Slack.
Those are deliberate operator actions.

## 1. Prepare the host

Copy the example without putting secrets in Git:

```bash
cd /path/to/morgenruf/deploy
cp .env.techops.example .env.techops
chmod 600 .env.techops
openssl rand -hex 32
```

Set all values in `.env.techops`. `DATABASE_URL` and `PULSE_DB_PASSWORD` must
refer to the same URL-safe password. Use Slack IDs (`T...`, `U...`, `A...`,
`C...`/`G...`), not display names. The direct pilot needs an `xoxb-...` token
and the Slack signing secret.

## 2. Configure Slack

1. Copy `slack-manifest.techops.json` to a local temporary file.
2. Replace every `https://PULSE_PUBLIC_HOST` with the exact public HTTPS base
   URL that will be in `APP_URL`; do not commit that derived manifest if it
   contains private hostnames.
3. Create/install the app from the derived manifest. Keep token rotation off
   for this direct-seeded pilot.
4. Record the workspace, app, bot-user, participant/manager, and private
   channel IDs in `.env.techops`.
5. Invite the bot to `#techops-notification-test`.

## 3. Add public routing

The app deliberately binds only to `127.0.0.1:$PULSE_PORT`. Configure the
existing TLS proxy to route the chosen hostname to that loopback port, then
configure the same HTTPS base URL in Slack for:

- `/slack/events`
- `/slack/interactions`
- `/oauth/callback`

Validate proxy configuration before any proxy reload. Do not expose port 3015
directly to the Internet.

## 4. Validate and deploy

```bash
./deploy-techops.sh
```

The script validates configuration without echoing secrets, builds the local
image, starts Postgres, applies migrations, seeds the pilot idempotently, then
starts Pulse and checks `/healthz`. It can be safely re-run after a failed
attempt; the seed updates the named pilot schedule instead of adding another.

Useful status commands:

```bash
docker compose --project-name pulse-techops --env-file .env.techops -f docker-compose.techops.yml ps
docker compose --project-name pulse-techops --env-file .env.techops -f docker-compose.techops.yml logs --tail=100 app
curl --fail http://127.0.0.1:3015/healthz
```

## 5. Live acceptance check

On a Monday, Tuesday, Wednesday, or Thursday (Guatemala time):

1. At 09:15 verify only the pilot participant receives the three-question DM.
2. Leave it unanswered and verify reminders only at 09:45, 10:15, and 10:45.
3. Submit an update and verify it posts immediately to
   `#techops-notification-test`, not another channel.
4. Submit a blocker and verify the configured manager ID is mentioned.
5. Leave a future run unanswered and verify the 11:00 missing-update post.

## Rollback and recovery

Default rollback stops only this Compose project and **preserves the database**:

```bash
./rollback-techops.sh
```

Re-deploy with `./deploy-techops.sh`; migrations and seed are idempotent.

Permanently deleting the pilot database is intentionally guarded and must be
an explicit operator decision:

```bash
PULSE_CONFIRM_PURGE=DELETE_PULSE_DATA ./rollback-techops.sh --purge-data
```

That command removes `pulse-techops-postgres`; it cannot be undone. It never
touches other Docker Compose projects.
