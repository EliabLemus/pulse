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

### 3.2 `app/src/db.py`

- Whitelists: agregar los 3 campos al set `allowed` de `create_standup_schedule` (`db.py:1305`) **y** de `update_standup_schedule` (`db.py:1484`). Ambas funciones filtran kwargs; sin esto los campos nuevos no se pueden crear ni editar desde el dashboard/API.
- Nuevo helper:

```python
def get_standups_today_for_schedule(team_id: str, schedule_id: int) -> list[dict]:
    """Submissions de hoy para un schedule (índice idx_standups_schedule, migración 026)."""
    sql = """
        SELECT * FROM standups
        WHERE team_id = %s AND schedule_id = %s AND standup_date = CURRENT_DATE
    """
    with db_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (team_id, schedule_id))
            return [dict(r) for r in cur.fetchall()]
```

### 3.3 `app/src/scheduler.py`

- Nueva función `send_pending_reminders(team_id, bot_token, schedule_id)`:
  - Pendientes = `participants` del schedule − user_ids en `db.get_standups_today_for_schedule(team_id, schedule_id)` − `is_skipped_today` − `is_on_vacation`.
  - DM por pendiente: `⏰ Recordatorio: falta tu update para *{standup_label}*. Responde por aquí 🙏` (etiqueta con la misma lógica de `_send_reminder_to_workspace`).
- En `register_schedule_job`: si `pending_reminder_times` no vacío, un job cron por hora (ids `pending_reminder_{team}_{sched}_{HHMM}`), mismos `day_of_week`/`tz` que el principal. No interfiere con `reminder_minutes` del upstream (cubre 09:45 posiblemente duplicado solo si alguien configura ambos; el pilot usa solo los nuevos).
- Nueva función `close_window(team_id, bot_token, schedule_id)`:
  - Mismo cálculo de pendientes; si hay, post al canal: `⚠️ Sin update: <@U...>` una línea por persona. Si no hay pendientes, no postea nada.
- En `register_schedule_job`: si `window_end` no vacío, job `window_close_{team}_{sched}` a esa hora.
- Agregar `pending_reminder_times`, `window_end`, `missing_mention` a `_SCHEDULE_TRIGGER_FIELDS` (`scheduler.py:1062`) para que el reconcile de 2 min re-registre jobs al editarlos.

### 3.4 `app/src/handlers.py` — `_complete_standup`

Después de resolver `sched_config` y antes de postear:

- `missing = (sched_config.get("missing_mention") or "").strip()`
- Si `missing` y el standup reporta bloqueo: anteponer al `formatted` una línea `🚧 <@{missing}> — bloqueo reportado por <@{user_id}>`.
- Cómo saber si reporta bloqueo: llamar `blockers.has_blockers(session.questions, question_answers)` directamente (misma lógica que `db.save_standup`). **No** leer `has_blockers` de la fila en edición: `db.update_standup` (ruta de edits, `db.py:1667`) recalcula con la lista vieja `("none","no","nope","-","n/a","")` en vez de `blockers.py` y puede divergir.
- La mención del manager nunca se degrada a nombre plano: el reemplazo de `notify_on_report=False` debe aplicar **solo** sobre `<@{user_id}>` del autor, no sobre `<@{missing}>`.

## 4. Slack App (una sola, para pilot)

1. Crear app desde un manifest derivado: copiar `slack-manifest.json` → `slack-manifest.techops.json` con (a) `settings.interactivity.request_url`, `event_subscriptions.request_url` y `redirect_urls` apuntando a `https://<host-publico-nexus>` (vienen hardcodeadas a `api.morgenruf.dev`), y (b) `token_rotation_enabled: false` (sin OAuth flow en el pilot; con true Slack rota tokens que aquí no tendrían refresh). Scopes y `bot_events` se quedan igual — ya incluyen `groups:read` (canal privado) y `message.im`.
2. Instalar al workspace → bot token `xoxb-...`.
3. Invitar el bot a `#techops-notification-test` (`/invite @bot` dentro del canal privado).
4. Secretos en el host (nexus), nunca en git: `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `FLASK_SECRET_KEY` (obligatorio, ≥32 chars, valida `main.py:82`), `DATABASE_URL`.

## 5. Despliegue (Mac mini / nexus, Docker)

Verificado hoy contra el repo:

- **Migraciones no corren solas**: el CMD es `python src/main.py` y nada llama `run_migrations()`. Crear `deploy/docker-compose.techops.yml` (base: `app/docker-compose.yml`, que ya trae `db` postgres:16-alpine con healthcheck) con `build: ./app` en vez de `image: morgenruf/morgenruf:latest`, y un servicio one-shot `migrate` (`python src/migrate.py`) del que `app` dependa.
- **Pilot sin OAuth**: sembrar la instalación directo en DB antes de arrancar — `db.save_installation(team_id, team_name, xoxb, bot_user_id, app_id)` — y crear el schedule. El scheduler registra los jobs al arranque leyendo `installations` (`_load_workspace_jobs`, `main.py:47`); con la fila sembrada funciona sin OAuth flow.
- **Creación del schedule del pilot**: por SQL (el dashboard también sirve, pero requiere login) con los valores de la sección 1 más `pending_reminder_times='09:45,10:15,10:45'`, `window_end='11:00'`, `missing_mention='<tu UID>'`. El reconcile de 2 min lo registra sin reiniciar.
- TLS por Caddy existente; `/healthz` existe (`main.py:161`) para healthcheck.

## 6. Tareas (orden)

1. Rama `feat/techops-window`: migración 029 + whitelists de `db.py` + `get_standups_today_for_schedule` + test.
2. `send_pending_reminders` + registro de jobs + tests (mock de `WebClient`, `db.get_standups_today_for_schedule`, `is_skipped_today`, `is_on_vacation`).
3. `close_window` + job + tests (pendiente → menciona; sin pendientes → no postea).
4. Mención de manager en `_complete_standup` + tests (`has_blockers` True/False × `missing_mention` vacío/lleno × `notify_on_report` on/off).
5. `_SCHEDULE_TRIGGER_FIELDS` + test de fingerprint (editar `pending_reminder_times` re-registra jobs).
6. `ruff check app/src/` y `pytest app/tests/` en verde (hoy: 530 passed — no debe bajar).
7. `slack-manifest.techops.json` + `deploy/docker-compose.techops.yml` + seed script del pilot.
8. Deploy nexus + prueba en vivo el siguiente L/M/J/V.

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
