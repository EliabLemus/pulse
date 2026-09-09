# Adaptación TechOps del bot de standups (pilot) — Spec

**Base:** upstream `morgenruf/morgenruf` v1.6.0 (MIT), commit `1649910` + `994bb3f` (docker.yaml deshabilitado).
**Objetivo:** ventana diaria de updates por DM con recordatorios solo a pendientes, publicación inmediata en canal, mención al manager por bloqueos y cierre con "sin update".

---

## 1. Parámetros del pilot (fuente: decisión del usuario)

| Parámetro | Valor |
|---|---|
| Participante | Solo Eliab (manager) en la fase de prueba |
| Días | L/M/J/V (`mon,tue,wed,thu`) |
| Hora DM inicial | 09:15 `America/Guatemala` |
| Recordatorios | 09:45, 10:15, 10:45 — **solo si no ha respondido** |
| Cierre | 11:00 — post `⚠️ Sin update: @user` |
| Canal de destino | `techops-notification-test` (privado; el bot debe ser invitado) |
| Mención por bloqueo | Manager = Eliab durante el pilot |

## 2. Realidad del código (auditado hoy)

Lo que ya existe y se conserva:

- **Post inmediato por update:** `_complete_standup` (`app/src/handlers.py:356`) publica cada standup al canal del schedule apenas llega la última respuesta, en thread diario (`upsert_daily_thread`), respetando `notify_on_report`. **No hace falta construir el post inmediato; ya existe.**
- **Detección de bloqueos:** `app/src/blockers.py` clasifica `has_blockers` con frases reales ("na", "• None", "n/a"). Reutilizable tal cual.
- **Scopes del manifest:** `chat:write`, `im:*`, `channels:read/join/history`, `groups:read`, `users:read`, `message.im` ya están en `slack-manifest.json`. Suficiente para canal privado + DMs.
- **Scheduler con reconciliación:** `register_schedule_job` (`app/src/scheduler.py:996`) registra jobs cron por fila de `standup_schedules`; `_sync_jobs_from_db` re-registra cada 2 min. Cualquier campo nuevo que afecte triggers debe agregarse a `_SCHEDULE_TRIGGER_FIELDS` (`scheduler.py:1062`).

Lo que falta (los 3 cambios reales):

1. Recordatorios **posteriores** al inicio y **solo a pendientes** (el actual `_send_reminder_to_workspace` es previo y va a todos).
2. **Cierre de ventana** a las 11:00 con lista de "sin update".
3. **Mención del manager** en el post del canal cuando `has_blockers` es verdadero.

## 3. Cambios por archivo

### 3.1 Migración `app/migrations/029_techops_window.sql` (nueva)

```sql
ALTER TABLE standup_schedules
    ADD COLUMN IF NOT EXISTS pending_reminder_times TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS window_end TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS missing_mention TEXT NOT NULL DEFAULT '';
```

- `pending_reminder_times`: `"09:45,10:15,10:45"` (horas locales del schedule). Vacío = comportamiento upstream.
- `window_end`: `"11:00"`. Vacío = sin cierre.
- `missing_mention`: Slack user ID del manager a notar en cierre/bloqueos. Vacío = no menciona.

### 3.2 `app/src/scheduler.py`

- Nueva función `send_pending_reminders(team_id, bot_token, schedule_id)`:
  - Calcula pendientes: `participants` del schedule − user_ids con fila en `standups` donde `schedule_id = S AND standup_date = CURRENT_DATE` (usar `db.get_today_standups(team_id)` y filtrar por `schedule_id`, que existe desde migración 026).
  - Excluye `is_skipped_today` y vacaciones (`db.is_skipped_today`, `db.is_on_vacation`).
  - DM por pendiente: `⏰ Recordatorio: falta tu update para *{standup_label}*. Responde por aquí 🙏`
- En `register_schedule_job`: si `pending_reminder_times` no vacío, registrar un job cron por cada hora (job id `pending_reminder_{team}_{sched}_{HHMM}`), mismo `day_of_week`/`tz` que el principal.
- Nueva función `close_window(team_id, bot_token, schedule_id)`:
  - Pendientes con la misma lógica; si hay, post al canal: `⚠️ Sin update: <@U...>` (uno por línea). Si nadie pendiente, no postea nada.
- En `register_schedule_job`: si `window_end` no vacío, job `window_close_{team}_{sched}` a esa hora.
- Agregar los 3 campos a `_SCHEDULE_TRIGGER_FIELDS` para que el sync loop re-registre al editarlos.

### 3.3 `app/src/handlers.py` — `_complete_standup`

Después de resolver `sched_config` y antes de postear:

- `missing = sched_config.get("missing_mention")`
- Si `missing` y el standup tiene `has_blockers` (campo ya persistido; ver `db.save_standup` / `blockers.py`): anteponer al `formatted` una línea `🚧 <@{missing}> — bloqueo reportado por <@{user_id}>` y forzar mención visible aunque `notify_on_report` sea False (la mención del manager nunca se degrada a nombre plano).

### 3.4 `app/src/db.py`

- `get_standups_today_for_schedule(team_id, schedule_id) -> list[dict]`: `SELECT * FROM standups WHERE team_id=%s AND schedule_id=%s AND standup_date=CURRENT_DATE`.
- Nada más; `create_standup_schedule`/`update_standup_schedule` ya aceptan kwargs arbitrarios → los 3 campos nuevos fluyen sin tocar más.

## 4. Slack App (una sola, para pilot)

1. Crear app desde `slack-manifest.json` (ajustar `redirect_urls` al dominio del pilot; events URL `https://<host>/slack/events`).
2. Scopes ya correctos; instalar al workspace → bot token `xoxb-...`.
3. Invitar el bot a `#techops-notification-test` (`/invite @bot` en el canal privado).
4. Secretos en el host (nexus): `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SECRET_KEY`, `DATABASE_URL`. Nunca en git.

## 5. Despliegue (Mac mini / nexus, Docker)

- `docker compose` nuevo (fuera del repo o en `deploy/`): servicios `db` (postgres:16, volumen local) + `app` (build `./app`), puerto interno 3000, TLS por Caddy existente.
- `python src/migrate.py` corre migraciones al arrancar (verificar entrypoint del upstream; si no, paso explícito del compose).
- Healthcheck: `curl localhost:3000/healthz` (confirmar ruta en `main.py`; si no existe, usar `/`).

## 6. Tareas (orden)

1. Rama `feat/techops-window`: migración 029 + `db.get_standups_today_for_schedule` + test.
2. `send_pending_reminders` + registro de jobs + tests (congelar `db.get_today_standups`, `resolve_participants`, `_slack_dm_with_retry`).
3. `close_window` + job + tests (pendiente → menciona; sin pendientes → no postea).
4. Mención de manager en `_complete_standup` + test (`has_blockers` True/False × `missing_mention` vacío/lleno).
5. `_SCHEDULE_TRIGGER_FIELDS` + test de fingerprint (editar `pending_reminder_times` re-registra jobs).
6. `ruff check app/src/` y `pytest app/tests/` en verde (hoy: 530 passed — no debe bajar).
7. Deploy nexus + crear schedule del pilot con los valores de la sección 1 (vía dashboard o SQL) + prueba en vivo el siguiente L/M/J/V.

## 7. Criterios de aceptación

- [ ] 09:15 llega DM con las 3 preguntas (solo a Eliab).
- [ ] Si no responde: DMs extra únicamente a las 09:45/10:15/10:45.
- [ ] Al responder, el update aparece en `#techops-notification-test` enseguida (thread diario), nunca en `#techops-automation`.
- [ ] Con bloqueo ≠ "none", el post menciona al manager.
- [ ] 11:00: si faltó, `⚠️ Sin update: @eliab` en el canal; si respondió, nada.
- [ ] Suite completa verde antes de cada merge a `main`.

## 8. Fuera de alcance del pilot

- Múltiples participantes/quipos/mood/analytics adicionales (ya vienen con upstream).
- Publicar imágenes a ghcr.io (docker.yaml sigue deshabilitado).
- Google Chat adapter, MCP, webhooks salientes.
