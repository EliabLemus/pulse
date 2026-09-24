# Pulse

> Fork of the open-source [Morgenruf](https://github.com/morgenruf/morgenruf) project (MIT), adapted for the TechOps daily-update workflow.

Pulse collects a daily update in one Slack modal and posts it automatically to the team channel. It is self-hosted: Slack callbacks reach the app over HTTPS, while standup data lives in PostgreSQL.

## How to use Pulse

![Diagrama del flujo completo de Pulse: inicio, formulario, publicación, bloqueo, edición, omitir, recordatorios, cierre y permisos de canal.](docs/pulse-workflow.svg)

[Ver el diagrama a tamaño completo](docs/pulse-workflow.svg)

### Qué ocurre a cada hora

- **09:00 Guatemala, lunes a viernes:** verificación de conexión — Pulse envía al propietario un DM con un botón **OK**; al pulsarlo confirma que Tailscale/Funnel y Slack responden (ver [`docs/runbook-verification.md`](./docs/runbook-verification.md)).
- **09:15 Guatemala, lunes, miércoles, jueves y viernes:** Pulse envía el DM inicial. *(Martes sin notificaciones: Sprint Planning. Sábado y domingo: silencio total.)*
- **09:45, 10:15 y 10:45:** solo quienes siguen pendientes reciben un recordatorio por DM. Las personas que respondieron, omitieron el día o están de vacaciones quedan excluidas.
- **11:00:** Pulse publica únicamente `Sin avance: @usuario` para cada participante pendiente. **No** vuelve a resumir o mencionar los avances ya publicados en el hilo diario.
- **Bloqueos:** el update se publica completo y la mención al responsable se añade al final, para no romper la lectura del avance. Respuestas negativas ("Sin bloqueos", "Ninguno", "Nada"), incluidas las respuestas por ticket (`TECH-43: Sin bloqueos`), **nunca** generan mención.

## Pulse TechOps workflow

1. At the configured time, Pulse sends each member a DM with **Completar mi update**.
2. The button opens one Spanish-language modal with exactly three questions:
   - ¿Qué lograste avanzar o completar ayer?
   - ¿Cuál es tu tarea principal para hoy?
   - ¿Tienes algún bloqueo que te impida avanzar hoy?
3. On submission, Pulse posts the update in the configured team-channel daily thread. There is no mood capture and nobody copies/pastes a template.
4. **Omitir hoy** is reversible: the confirmation includes **Completar mi update**, and typing `standup` also clears the same-day skip.
5. **Edit responses** reopens the same prefilled form. New submissions store their Slack message pointer, so editing updates the original thread reply in place instead of posting a duplicate. Records made before message pointers existed fall back safely to a marked thread reply.

The published format is deliberately plain and team-readable:

```text
Avances de @usuario - 15 de septiembre de 2026

¿Qué lograste avanzar o completar ayer?
• …

¿Cuál es tu tarea principal para hoy?
• …

¿Tienes algún bloqueo que te impida avanzar hoy?
Sin bloqueos
```

For public target channels such as `#techops-automation`, `chat:write.public` lets Pulse post without joining the channel. Pulse deliberately does **not** request `channels:join`, so it cannot add itself to any channel. Private channels still require an explicit invitation from a channel member.

[![Tests](https://github.com/EliabLemus/pulse/actions/workflows/test.yml/badge.svg)](https://github.com/EliabLemus/pulse/actions/workflows/test.yml)
[![Lint](https://github.com/EliabLemus/pulse/actions/workflows/lint.yml/badge.svg)](https://github.com/EliabLemus/pulse/actions/workflows/lint.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

A self-hosted, open-source Slack standup bot. Ask structured daily questions, post formatted updates to team channels, and keep full ownership of your standup data — no SaaS subscription required.

---

## Repository Structure

```
pulse/
├── app/
│   ├── src/            ← Python bot (Flask + slack-bolt)
│   ├── migrations/     ← SQL migration files (auto-applied on start)
│   ├── helm/morgenruf/ ← Production Helm chart
│   └── Dockerfile
├── brand/              ← Logo & brand assets
├── slack-manifest.yaml ← Slack app manifest
├── CHANGELOG.md
└── README.md
```

---

## Features

- 📅 **Configurable schedule** — per-team times, timezones, and days
- 💬 **DM-based collection** — bot DMs each member individually
- ❓ **Custom questions** — fully editable from the dashboard (not hardcoded)
- ⏭️ **Skip today** — DM `skip` to opt out for the day
- ⏰ **Pre-standup reminder** — configurable minutes before standup time
- 🌍 **Per-user timezone** — DM `timezone America/New_York` to set personal timezone
- 🚧 **Blocker detection** — highlights blockers in summaries
- 🤖 **Manual trigger** — type `standup` in DM anytime
- 🎭 **Mood tracking** — 4th question captures team sentiment (😊/😐/😔)
- 🔗 **Auto-linking** — Jira/GitHub issue references become clickable links
- 🪝 **Webhooks** — HMAC-signed HTTP webhooks on `standup.completed`
- ✏️ **Edit window** — members can edit responses within a configurable time window
- 📊 **Web dashboard** — Analytics tab, participation stats, CSV export
- 📧 **Welcome email + weekly digest** — via Resend
- 🏠 **App Home tab** — shows workspace status in Slack Home
- 🐳 **Kubernetes-ready** — production Helm chart at `charts.morgenruf.dev`
- ☁️ **Cloudflare Zero Trust** — works behind CF tunnel (no ingress controller needed)
- 🗃️ **PostgreSQL** — full standup history, migrations auto-applied on startup

---

## Quick Start

### 1. Create a Slack App

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) → **Create New App** → From manifest
2. Paste the manifest from [`slack-manifest.yaml`](./slack-manifest.yaml)
3. Under **OAuth & Permissions**, add your redirect URL: `https://<your-domain>/oauth/callback`
4. Copy **Client ID**, **Client Secret**, and **Signing Secret**

### 2. Run locally

```bash
cd app
cp .env.example .env
# Fill in SLACK_CLIENT_ID, SLACK_CLIENT_SECRET, SLACK_SIGNING_SECRET, DATABASE_URL
pip install -r src/requirements.txt
python src/main.py
```

### 3. Deploy to Kubernetes

See [**Kubernetes Deployment**](#kubernetes-deployment) below.

---

## Docker Image

This fork does not publish images to a registry — build from source:

```bash
docker compose --project-name pulse-techops -f deploy/docker-compose.techops.yml build app
```

The upstream project publishes [`morgenruf/morgenruf`](https://hub.docker.com/r/morgenruf/morgenruf) on DockerHub (mirrored at `ghcr.io/morgenruf/morgenruf:latest`). This repository tracks upstream features, but the TechOps deployment package deliberately always builds from source and never pulls the upstream image.

## Docker / Mac Quickstart

The fastest way to run Morgenruf locally or on a Mac server.

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (Mac/Linux/Windows)
- A Slack app — [create one](https://api.slack.com/apps) using the manifest at `slack-manifest.yaml`

### 1. Clone and configure

```bash
git clone https://github.com/EliabLemus/pulse.git
cd pulse/app
cp .env.example .env
# Edit .env with your Slack credentials
```

### 2. Start

```bash
docker compose up -d
```

That's it. The bot is now running at `http://localhost:3000`.

### 3. Expose to the internet (required for Slack webhooks)

Slack needs to reach your bot over a **stable public HTTPS hostname** — buttons inside already-delivered DMs keep posting to the stored Request URL long after the message was sent, so an ephemeral URL breaks every historical button when it dies.

**Tailscale Funnel (used in production here):**
```bash
tailscale funnel --bg --yes http://localhost:8081
# https://<your-host>.ts.net → Caddy (:8081) → container
# Validate from public resolvers/DNS, not from inside the tailnet:
#   dig +short @1.1.1.1 <your-host>.ts.net A
```

**Cloudflare Tunnel:**
```bash
brew install cloudflare/cloudflare/cloudflared
cloudflared tunnel --url http://localhost:3000
# Copy the https://xxxx.trycloudflare.com URL
# Set APP_URL=https://xxxx.trycloudflare.com in .env
# docker compose restart app
```

**ngrok:**
```bash
ngrok http 3000
# Copy the https URL and set APP_URL in .env
```

### 4. Configure your Slack app

Set these URLs in your Slack app settings:
- **Event Subscriptions Request URL:** `https://your-tunnel-url/slack/events`
- **OAuth Redirect URL:** `https://your-tunnel-url/oauth/callback`
- **Interactivity Request URL:** `https://your-tunnel-url/slack/interactions`

Then click **"Add to Slack"** from `https://your-tunnel-url/install`.

### Mac as a permanent server

To run on a Mac Mini or Mac server permanently:

```bash
# Start on boot
brew services start docker  # or use Docker Desktop login items

# Keep containers running
docker compose up -d --restart-policy always
```

---

## Google Chat (Beta)

Morgenruf supports Google Chat via the Chat REST API and a service account.

> **Note:** Google Chat bot integration requires **Google Workspace** (not free Gmail accounts).

### Setup

1. **Create a GCP project** at [console.cloud.google.com](https://console.cloud.google.com)
2. **Enable the Chat API** — _APIs & Services → Library → Google Chat API → Enable_
3. **Create a service account** — _IAM & Admin → Service Accounts → Create_
4. **Download the JSON key** for the service account
5. **Set the env var** — paste the entire JSON as a single line:
   ```bash
   GOOGLE_CREDENTIALS='{"type":"service_account","project_id":"...","private_key":"...","client_email":"...",...}'
   ```
6. **Configure the bot in Google Chat Admin** — _admin.google.com → Apps → Google Chat → Manage bots_
   - Set the **Webhook URL** to: `https://your-domain.com/google/events`
   - Enable _Direct messages_ and _Space messages_
7. **Restart Morgenruf** — the Google Chat blueprint is registered automatically when `GOOGLE_CREDENTIALS` is set.

### Commands (in Google Chat DM or Space)

| Command | Description |
|---------|-------------|
| `/standup` | Start your daily standup |
| `/skip` | Skip today's standup |
| `/help` | Show available commands |

---

## Standup format

Pulse’s TechOps workflow uses the single Spanish form and clean channel format shown above. The three questions are schedule-configured rather than hardcoded, but the pilot uses those exact questions. Mood collection is disabled for this workflow.

The upstream Morgenruf project retains broader configuration options (multiple schedules, dashboard, analytics, webhooks, Google Chat, and optional integrations). This fork’s pilot behavior is documented in [Pulse TechOps workflow](#pulse-techops-workflow).

---

## DM Commands

| Command | Description |
|---------|-------------|
| `standup` | Start your standup now |
| `skip` | Skip today's standup |
| `timezone <tz>` | Set your personal timezone (e.g. `timezone Europe/London`) |
| `help` | Show available commands |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SLACK_CLIENT_ID` | ✅ | Slack app client ID |
| `SLACK_CLIENT_SECRET` | ✅ | Slack app client secret |
| `SLACK_SIGNING_SECRET` | ✅ | Request signing secret |
| `DATABASE_URL` | ✅ | PostgreSQL connection URL |
| `APP_URL` | ✅ | Public base URL (e.g. `https://api.morgenruf.dev`) |
| `FLASK_SECRET_KEY` | ✅ | Random secret for session cookies |
| `PORT` | | HTTP port (default: `3000`) |
| `RESEND_API_KEY` | | For welcome emails (optional) |

---

## Kubernetes Deployment

Morgenruf ships a production-ready Helm chart at `app/helm/morgenruf/`.

### Database (recommended: external PostgreSQL)

> **We recommend using an external PostgreSQL instance** rather than the bundled sub-chart.
> The bundled sub-chart is convenient for testing but adds operational complexity in production.
> Bitnami images were also removed from Docker Hub, which can cause pull failures.

**Good options:**
- [CloudNativePG](https://cloudnative-pg.io/) operator (k8s-native)
- [Supabase](https://supabase.com) / [Neon](https://neon.tech) (managed, free tiers)
- AWS RDS / Google Cloud SQL / Azure Database
- Plain `postgres:16` StatefulSet in your cluster

Once you have a database, create the database and user:

```sql
CREATE DATABASE morgenruf;
CREATE USER morgenruf WITH PASSWORD 'strongpassword';
GRANT ALL PRIVILEGES ON DATABASE morgenruf TO morgenruf;
```

### Install

```bash
helm repo add morgenruf https://charts.morgenruf.dev
helm repo update

helm upgrade --install morgenruf morgenruf/morgenruf \
  --namespace morgenruf \
  --create-namespace \
  --set slack.clientId="YOUR_CLIENT_ID" \
  --set slack.clientSecret="YOUR_CLIENT_SECRET" \
  --set slack.signingSecret="YOUR_SIGNING_SECRET" \
  --set externalDatabase.url="postgresql://morgenruf:pass@host:5432/morgenruf" \
  --set flaskSecretKey="$(openssl rand -hex 32)" \
  --set app.url="https://api.your-domain.com"
```

> **Migrations** run automatically as an init container on every pod start — idempotent and safe.

### Cloudflare Zero Trust (no ingress controller)

If you use Cloudflare Tunnel instead of an ingress controller:

```bash
# Disable ingress in Helm
--set ingress.enabled=false

# Then add a Public Hostname in Cloudflare Zero Trust dashboard:
# Hostname: api.your-domain.com
# Service:  http://morgenruf.morgenruf.svc.cluster.local:3000
```

### Gateway API (HTTPRoute)

If your cluster uses [Gateway API](https://gateway-api.sigs.k8s.io/) instead of (or in addition to) Ingress, enable the chart's HTTPRoute and point it at your Gateway:

```bash
helm upgrade --install morgenruf morgenruf/morgenruf \
  --namespace morgenruf \
  --create-namespace \
  --set ingress.enabled=false \
  --set httpRoute.enabled=true \
  --set httpRoute.hostName="api.your-domain.com" \
  --set httpRoute.gateway.name="morgenruf-gateway" \
  --set httpRoute.gateway.namespace="morgenruf" \
  # ... plus required slack / database / app.url values
```

Requires Gateway API CRDs and an existing Gateway that matches `httpRoute.gateway`. Disable Ingress when HTTPRoute owns the hostname so you don't double-route the same host.

### values.yaml reference

```yaml
# Required ─────────────────────────────────────────────
slack:
  clientId: ""           # Slack app → Basic Information → Client ID
  clientSecret: ""       # Slack app → Basic Information → Client Secret (32 chars)
  signingSecret: ""      # Slack app → Basic Information → Signing Secret

externalDatabase:
  url: ""                # postgresql://user:pass@host:5432/db

flaskSecretKey: ""       # openssl rand -hex 32

app:
  url: "https://api.your-domain.com"   # Public HTTPS URL for OAuth redirects

# Optional ─────────────────────────────────────────────
resend:
  apiKey: ""             # Resend API key for welcome emails (free tier ok)

ingress:
  enabled: true          # set false for Cloudflare Tunnel / Gateway API / custom routing
  className: "nginx"
  hosts:
    - host: api.your-domain.com

httpRoute:
  enabled: false         # set true for Gateway API HTTPRoute
  hostName: "api.your-domain.com"
  gateway:
    name: morgenruf-gateway
    namespace: morgenruf
```

> ⚠️ **Common mistake:** `slack.clientSecret` and `slack.signingSecret` are **different values**.  
> Both are found on your Slack app's **Basic Information** page.  
> — Client Secret: 32 hex chars (e.g. `346a428c78b0d8c84b70e74d12a58ab5`)  
> — Signing Secret: 32 hex chars, listed separately under "App Credentials"

---

## Helm Chart Structure

```
app/helm/morgenruf/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── deployment.yaml   ← init container runs migrations
    ├── service.yaml
    ├── ingress.yaml
    ├── httproute.yaml    ← Gateway API HTTPRoute (optional)
    ├── redis.yaml
    ├── configmap.yaml
    └── secret.yaml
```

---

## Deploy

- **Quickstart / evaluation:** the Docker / Mac Quickstart above.
- **Production single-workspace (TechOps pilot):** see [`deploy/README.md`](./deploy/README.md) — a reversible Docker Compose stack (Postgres + Redis + app) with idempotent migrations and seed, plus a guarded data purge.

Whichever route you choose, Slack's Request URLs must point at your public HTTPS host (`/slack/events`, `/slack/interactions`, `/oauth/callback`). Use a stable hostname — a reverse proxy, Cloudflare Tunnel with a named tunnel, or Tailscale Funnel — rather than an ephemeral quick tunnel: Slack stores the Request URL, and the buttons inside already-delivered DMs keep posting to it long after the message was sent. If the stored hostname dies, every historical DM button dies with it.

---

## Roadmap

- [x] Multi-workspace Slack OAuth
- [x] Web dashboard (`/dashboard`)
- [x] Webhooks with HMAC signing
- [x] Jira/GitHub auto-linking
- [x] Edit window for responses
- [x] Email notifications (Resend)
- [x] Custom questions
- [x] Skip today
- [x] Pre-standup reminders
- [x] Per-user timezone
- [x] Mood tracking
- [x] Analytics dashboard + CSV export
- [x] Weekly digest email
- [x] Owner connection self-check (daily DM + OK button round-trip proof)
- [ ] Vacation date ranges (currently indefinite until the user returns)
- [ ] Multiple standup schedules per workspace
- [ ] Jira/Linear/GitHub integration
- [ ] Microsoft Teams support *(coming soon)*
- [ ] Public REST API

---

## License

[MIT](./LICENSE)

---

## Contributing

PRs welcome! See [CONTRIBUTING.md](./CONTRIBUTING.md) for guidelines.

---


