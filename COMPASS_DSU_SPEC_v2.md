# Compass DSU — Spec: keys por usuario + filtro In Progress + mejoras auditadas
Fecha: 2026-10-31 · Estado: PENDIENTE DE APROBACIÓN DEL OWNER
Repo: /Users/openjaime/Projects/morgenruf/.worktrees/compass-presentation (branch release/compass-presentation)

## PARTE A — Requerimiento del owner (decisión ya evaluada, falta OK final)

### A1. Keys por usuario para comentar impersonando
- Tabla nueva `compass_user_api_keys(user_id PK, key_ciphertext, added_at, active)`. Keys cifradas en reposo.
- Carga por comando CLI dentro del contenedor (key por stdin, nunca argv/logs): cero redeploy por alta/baja/revocación.
- Propagar `user_id` a `compass_comment_jobs` (hoy el job no lo lleva; el standup_id ya lo tiene → 1 columna + 1 línea en el INSERT).
- Worker: resuelve la key del usuario al momento de comentar → impersona. Sin key propia → fallback a la global (nadie bloqueado mientras se generan las keys).
- Key del usuario falla (4xx) → job marcado `unknown` + warning al canal (política no-retry del worker intacta).

### A2. Pedir avances SOLO de tickets In Progress
- `compass.py:134`: filtro pasa de {todo, active, blocked} a {'active'} (statusCategory canónico, no status literal).
- Usuario sin tickets active → no recibe DM de avances (skip completo).
- Los blocked siguen cubiertos por la pregunta de bloqueos + owner_healthcheck.

## PARTE B — Auditoría GLM (deleg_068565a0), priorizada para decisión

### P1 — Alto impacto
- R1 · Comment worker pierde comentarios en errores claramente reintentables (DNS/conexión rechazada = la petición NUNCA llegó, hoy se pierde igual que todo lo demás). Fix: distinguir pre-flight (retry seguro ×3 con backoff) de ambigüedad real post-envío (unknown, como hoy).
- R2 · Jobs `unknown` sin visibilidad: sin query de reconciliación, sin sección en RUNBOOK. Fix: script `--reconcile` + alerta al owner si unknown > 0 tras N corridas + RUNBOOK.
- R3 · Snapshot caduco degrada el DSU en silencio: si el refresh falla, a los 30 min el usuario cae al flujo plano sin saber que perdió contexto Compass. Fix: alerta en refresh fallido + aviso en el DM ("modo simple") + edad configurable.

### P2 — Impacto medio
- R4 · Fricción diaria: con 5 tickets y 1 trabajado hay que marcar 4 checkboxes "sin avances". Fix: checkbox global "sin avances en el resto" o vacío=sin avances con confirmación.
- R5 · No hay forma de saber estado sin leer logs (jobs pendientes/unknown, edad de snapshot, últimas corridas). Fix: comando /pulse status solo-owner o sección en dashboard.
- R6 · Sesión guiada puede quedar atascada (wizard_step=2) si falla la persistencia y el usuario cierra el modal: bloquea el siguiente DM programado hasta TTL. Fix: expiración explícita + mensaje de recuperación.
- R7 · _call_mcp sin retry para el snapshot (idempotente, read-only): retry simple con backoff, trivialmente seguro.

### P3 — Calidad (refactor incremental al tocar cada área, NO como proyecto aparte)
- Parseo de questions JSON repetido ≥5× → helper. register_handlers ~1200 líneas → extraer guided/home/webhooks. Tests faltantes: pre/post-flight del worker, fallos context_worker, edit_window_hours ×3, expiración de sesión.

## Orden de implementación propuesto (si todo se aprueba)
A1+A2 (requerimiento) → R1 → R2 → R3 → R4 → R5 → R6 → R7 → P3 incremental.
Todo con tests; deploy SOLO con orden explícita del owner.
