# SPEC-004: DSU con doble foco y publicación Slack estructurada

**Estado:** Draft. La opción de producto está aprobada: foco principal + foco secundario opcional. Este documento no autoriza implementación, despliegue, push ni cambio de datos productivos.

## Objetivo

Permitir que cada persona registre hasta dos focos concretos para el día —un foco principal obligatorio y un foco secundario opcional— y publicar el DSU guiado con jerarquía visual sobria de Slack Block Kit.

Cada foco debe conservar una asociación inequívoca entre ticket y objetivo. El mensaje final debe ser compacto, accesible y reproducible exactamente si la entrega a Slack se reintenta.

El bot continúa siendo una integración de **actualizaciones solamente**: puede crear los comentarios ya previstos para avances por ticket, pero nunca cambia estado, prioridad, responsable, sprint, fechas ni visibilidad de Compass.

---

## Decisión de producto

Se adopta la opción **foco principal + foco secundario opcional**.

No se adopta un selector múltiple con texto compartido porque no permite saber qué objetivo corresponde a cada ticket. Tampoco se permite una lista abierta de focos: dos es el límite explícito de este spec para conservar claridad visual y evitar que la sección se convierta en backlog.

---

## Estado actual verificado

- El paso 2 del wizard muestra los tickets del snapshot del sprint y captura una única selección `priority_key` más un único `priority_goal`.
- `_format_guided_channel_post` publica `Hoy` como texto libre y actualmente ignora `priority_key`.
- El envío guiado persiste primero una fila durable de `guided_standup_deliveries` y después reclama esa fila para publicar una vez.
- La fila durable contiene `channel_text`, pero no contiene un payload de bloques. Por ello, un diseño Block Kit correcto no puede depender de reconstruir el mensaje desde Compass durante un reintento.
- El proyecto ya utiliza `client.chat_postMessage(..., text=..., blocks=...)` en otros módulos; no se requiere una nueva autorización de Slack para enviar bloques con el scope actual de publicación.
- La seguridad de enlaces vigente se mantiene: solo `portal_task_url(task)` puede convertir una clave en enlace. Una URL no canónica, externa o ausente deja la clave como texto plano.

---

## Experiencia final

### Paso 2 de 3 — Focos de hoy

El paso conserva el contexto visible de tickets del sprint. Sustituye la selección única actual por dos pares ticket/objetivo claramente etiquetados.

```text
2 de 3 · Focos de hoy

Tickets del sprint
• TECH-55 — Flujo de aprobación de AI Hub
• TECH-87 — Adopción de skill de Cloud Run

Foco principal
[ TECH-55 — Flujo de aprobación de AI Hub ▼ ]

Objetivo en TECH-55
[ Probar localmente el flujo de aprobación ]

Foco secundario — opcional
[ Ninguno ▼ ]

Objetivo en el foco secundario — opcional
[                                             ]
```

Si la persona selecciona un foco secundario, la etiqueta del cuarto campo se actualiza al ticket seleccionado al volver al paso o al renderizar el siguiente estado del modal:

```text
Objetivo en TECH-87 — obligatorio si se selecciona este foco
[ Documentar el patrón de despliegue ]
```

La versión con un solo foco conserva una interacción equivalente a la actual: foco principal y objetivo; el segundo par permanece vacío.

### Mensaje raíz de Slack

Cada publicación nueva usa bloques sobrios y mantiene un texto fallback equivalente.

```text
Daily Standup · @Eliab
08 oct · 09:22 · Sin bloqueos

AVANCES
• TECH-55 — Flujo de aprobación de AI Hub
  Implementé la validación inicial.
• TECH-87 — Adopción de skill de Cloud Run
  Documenté las dependencias.

FOCO DE HOY
• TECH-55 — Flujo de aprobación de AI Hub
  Probar localmente el flujo de aprobación.
• TECH-87 — Adopción de skill de Cloud Run
  Documentar el patrón de despliegue.
```

El bloque `BLOQUEOS` solo aparece cuando el texto registrado representa un bloqueo real. `Sin bloqueo`, `Ninguno` y equivalentes no añaden una sección visual vacía; el contexto puede indicar `Sin bloqueos`.

---

## Requisitos funcionales

### R1 — Dos focos como máximo, con objetivos independientes

- El foco principal es obligatorio y debe ser un ticket del snapshot del sprint o la opción existente `Otra prioridad no asociada a un ticket`.
- El foco secundario es opcional y admite únicamente un ticket del snapshot o `Ninguno`.
- No se admiten más de dos focos en este flujo.
- El objetivo principal es obligatorio y debe contener texto no vacío.
- Si hay foco secundario, su objetivo es obligatorio y debe contener texto no vacío.
- Si el foco secundario es `Ninguno`, su objetivo se ignora y no se persiste ni publica.
- El foco principal y secundario no pueden tener la misma clave. La validación debe marcar el campo secundario, preservar el modal y no persistir ni publicar nada.
- El foco secundario no admite `other`; dos prioridades libres no asociadas a tickets están fuera de alcance de este spec.

### R2 — Modelo de respuestas compatible

- El modelo canónico de sesión será `focus_items`, una lista ordenada de uno o dos objetos serializables:

```json
[
  {"key": "TECH-55", "goal": "Probar localmente el flujo de aprobación"},
  {"key": "TECH-87", "goal": "Documentar el patrón de despliegue"}
]
```

- Un foco principal no asociado a ticket se representa como:

```json
[{"key": "other", "goal": "Preparar la propuesta técnica"}]
```

- Durante una transición de sesión, `priority_key` y `priority_goal` existentes se interpretan como el primer `focus_item` si `focus_items` no existe. No se pierde una sesión ya iniciada.
- La columna histórica `standups.today` conserva una representación humana estable, en orden de foco:

```text
TECH-55: Probar localmente el flujo de aprobación
TECH-87: Documentar el patrón de despliegue
```

- Esta representación histórica no decide la publicación: el payload durable de entrega es la fuente para reintentos.

### R3 — Jerarquía Block Kit sobria y accesible

- Las publicaciones guiadas nuevas usan, como máximo, estos bloques: `header`, `context`, `section` para Avances, `divider`, `section` para Foco de hoy y `section` opcional para Bloqueos.
- No se usan `fields`, tablas, cards, botones, acciones ni rich-text avanzado en el mensaje raíz del DSU.
- La sección `FOCO DE HOY` conserva el orden principal → secundario y cada foco conocido se representa con:

```text
• <enlace canónico|TECH-55> — *Título del snapshot*
  Objetivo concreto.
```

- `other` se representa sin una clave ni enlace inventados:

```text
• Prioridad no asociada a ticket
  Preparar la propuesta técnica.
```

- El parámetro superior `text` contiene la versión textual completa del mismo contenido, incluyendo ambos focos cuando existan. Es el fallback para notificaciones y accesibilidad.
- Se conservan `unfurl_links=False` y `unfurl_media=False`.

### R4 — Enlaces y snapshot seguro

- El título, la clave y la URL se resuelven exclusivamente desde `session.compass_tasks`, capturado antes de abrir el wizard.
- Un foco con clave ausente del snapshot no debe causar excepción, búsqueda de Compass ni enlace inventado. Si aparece por una sesión obsoleta, se publica únicamente su objetivo como prioridad no asociada y se registra una advertencia sin secretos.
- Solo `portal_task_url(task)` puede producir un enlace. Las rutas antiguas `/tickets/<KEY>`, dominios externos y URLs inválidas permanecen como texto plano.
- Finalizar un DSU no consulta Compass para renderizar el mensaje ni para reintentar su entrega.

### R5 — Entrega durable y reintentos idénticos

- La migración nueva añade `channel_blocks JSONB` nullable a `guided_standup_deliveries`.
- Para toda nueva entrega guiada, la inserción atómica guarda `channel_text` y `channel_blocks` en la misma transacción que el standup y los comment jobs.
- `channel_blocks` es una lista JSON serializada de bloques sin secretos. Los datos se limitan a la identidad Slack, tickets del snapshot, avances, focos y bloqueos ya presentes en el fallback.
- `claim_guided_delivery` devuelve `channel_id`, `channel_text` y `channel_blocks`.
- La publicación usa `client.chat_postMessage(channel=..., text=..., blocks=channel_blocks, unfurl_links=False, unfurl_media=False)` cuando la columna contiene bloques válidos.
- Para registros históricos sin `channel_blocks`, el worker publica exclusivamente `channel_text`; no se re-renderiza y no se consulta Compass. Esto mantiene reintentos compatibles.
- Los estados `pending`, `processing`, `delivered` y `unknown`, la semántica de no duplicar la raíz y la conciliación de outcomes ambiguos no cambian.

### R6 — Sin cambio de frontera Compass

- Ningún foco de hoy, principal o secundario, crea un comentario en Compass.
- Los comentarios Compass continúan correspondiendo exclusivamente a avances por ticket de la sección Avances.
- Ningún flujo derivado de este spec modifica campos de workflow de Compass.

---

## Fuera de alcance

- Tres o más focos diarios.
- Dos prioridades libres sin ticket.
- Distribución de tiempo, porcentajes, estimaciones u horas por foco.
- Botones de completar, cambiar estado o crear tickets desde Slack.
- Actualizar posts guiados ya entregados antes de esta funcionalidad.
- Reescribir los mensajes históricos ni enriquecerlos con datos actuales de Compass.
- Cambiar el canal productivo, schedule, participantes, recordatorios o la política de comentarios Compass.

---

## Diseño técnico

### Archivos previstos

- `app/src/modules/standup/blocks.py`
  - Reemplazar el par de campos de prioridad por los pares de foco principal/secundario.
  - Añadir builders puros para el mensaje Block Kit y el fallback textual, ambos desde el mismo input normalizado.
  - Mantener los builders de modal deterministas y el orden principal → secundario.

- `app/src/modules/standup/handlers.py`
  - Capturar, validar, normalizar y restaurar `focus_items` en Siguiente/Atrás.
  - Traducir sesiones antiguas con `priority_key`/`priority_goal`.
  - Renderizar `channel_text` y `channel_blocks` una vez antes de persistir.
  - Publicar exactamente el payload reclamado por la cola, sin reconsultar Compass.

- `app/src/modules/standup/comment_jobs.py`
  - Extender `save_guided_submission` para recibir `channel_blocks`.
  - Persistir el JSON y devolverlo desde `claim_guided_delivery`.
  - Mantener el fallback para registros sin bloques.

- `app/src/modules/standup/migrations/073_guided_delivery_blocks.sql`
  - Añadir `channel_blocks JSONB` nullable sin reescribir filas existentes.
  - No añadir defaults que conviertan una entrega histórica en un payload visual artificial.

- `app/tests/test_guided_dsu_handlers.py`
  - Cubrir captura, Atrás, validación y publicación del doble foco.
  - Cubrir `chat_postMessage` con fallback, bloques y unfurls apagados.

- `app/tests/test_guided_comment_jobs.py`
  - Cubrir guardado y claim de `channel_blocks`, más el fallback de una fila histórica nula.

- `app/tests/test_compass_dsu.py`
  - Cubrir el modal con foco secundario opcional y restauración de una sesión antigua de prioridad única.

### Invariantes de implementación

- El renderizador de texto y el renderizador de bloques reciben los mismos datos normalizados; no se permite que uno incluya un foco que el otro omite.
- El máximo de bloques por mensaje se mantiene ampliamente por debajo del límite de Slack.
- La cola persistida, no el estado Redis, define el payload publicado tras un fallo o reintento.
- Ningún payload de bloques contiene credenciales, `private_metadata`, respuestas internas de Compass ni URLs no verificadas.
- No se agregan dependencias nuevas.

---

## Deltas de implementación

### Delta 001 — Contrato de doble foco y modal

**Objetivo:** capturar y restaurar uno o dos focos con objetivos separados sin cambiar aún la cola ni la publicación.

1. Escribir tests RED para foco principal único, foco secundario válido, secundaria duplicada, secundaria sin objetivo y restauración con Atrás.
2. Implementar la traducción de `priority_key`/`priority_goal` a `focus_items` para sesiones preexistentes.
3. Construir los dos pares de controles del paso 2 y su copy condicional.
4. Ejecutar los tests enfocados y formatear los archivos editados antes de ampliar la suite.

### Delta 002 — Renderizadores puros de fallback y Block Kit

**Objetivo:** producir artefactos visual y textual equivalentes desde el snapshot y `focus_items`.

1. Escribir tests RED para uno y dos focos, `other`, clave obsoleta, URL canónica y URL no canónica.
2. Implementar un builder puro que devuelva `{text, blocks}`.
3. Verificar que los bloques usan la jerarquía acordada y que Bloqueos se omite cuando no existe bloqueo real.
4. Mantener intactos Avances, la seguridad de enlaces y las reglas de comentarios.

### Delta 003 — Cola durable de bloques

**Objetivo:** garantizar que el reintento publica el mismo mensaje sin reconstrucción ni lectura externa.

1. Escribir tests RED para persistencia/claim de `channel_blocks` y para fallback de una fila histórica nula.
2. Añadir la migración `073_guided_delivery_blocks.sql`.
3. Extender persistencia, claim y llamada `chat_postMessage`.
4. Confirmar que la ruta de error preserva la sesión y que un outcome desconocido no reintenta automáticamente.

### Delta 004 — Gates y validación de entrega aislada

**Objetivo:** cerrar la funcionalidad sin publicar en producción.

1. Ejecutar gates de Judge completos.
2. Validar el payload con Slack Block Kit Builder o un test de forma local; no enviar mensajes reales durante esta validación.
3. Revisar que migración, payload y fallback no contienen secretos ni dependen de Redis/Compass después de persistir.
4. Preparar evidencia para una decisión separada de piloto o despliegue. No desplegar ni publicar sin orden explícita del owner.

---

## Criterios de aceptación

```yaml
- id: AC-1
  criterion: El paso Focos de hoy permite un foco principal y un foco secundario opcional, pero nunca más de dos.
  test: Builder test verifica dos pares de controles y no existe mecanismo de tercera selección.

- id: AC-2
  criterion: Cada foco seleccionado tiene un objetivo propio; un foco secundario con objetivo vacío se rechaza sin persistir ni publicar.
  test: Handler test usa secondary key + empty goal y espera error de campo, cero save_guided_submission y cero chat_postMessage.

- id: AC-3
  criterion: El mismo ticket no puede ser foco principal y secundario.
  test: Handler test espera error en secondary selector y ninguna escritura/publicación.

- id: AC-4
  criterion: Una sesión anterior con priority_key/priority_goal se restaura como un único foco principal sin pérdida de texto.
  test: State/modal test carga answers legacy y verifica initial values del foco principal.

- id: AC-5
  criterion: El mensaje nuevo con dos focos muestra clave, título del snapshot y objetivo en orden principal-secundario; uno con foco único no renderiza una línea secundaria vacía.
  test: Pure renderer tests verifican text fallback y blocks para uno/dos focos.

- id: AC-6
  criterion: Solo una URL portal canónica se renderiza como enlace; URL externa, antigua o ausente deja la clave plana.
  test: Renderer tests parametrizados para URL portal válida, /tickets/<KEY>, example.com y null.

- id: AC-7
  criterion: text fallback y blocks contienen la misma identidad y los mismos focos, y la publicación conserva unfurl_links/unfurl_media falsos.
  test: Handler test compara contenido y kwargs de chat_postMessage.

- id: AC-8
  criterion: La entrega durable guarda y reclama channel_text + channel_blocks en la misma transacción; una fila histórica sin bloques entrega solo texto sin re-renderizar.
  test: Comment-job tests inspeccionan INSERT/RETURNING y ejercitan ambos payloads.

- id: AC-9
  criterion: La entrega y los reintentos no hacen lectura de Compass ni crean comentarios por Foco de hoy.
  test: Mock CompassClient/worker asserts no calls during final submission with uno o dos focos.

- id: AC-10
  criterion: Ninguna acción de este spec cambia estado, prioridad, asignado, sprint, fechas o visibilidad de Compass.
  test: Scope test y revisión de llamadas permiten solo el flujo de comentarios existente para avances.

- id: AC-11
  criterion: Los tests enfocados, suite completa, ruff y diff check pasan antes de considerar piloto.
  test: Judge commands de esta spec devuelven exit 0.
```

---

## Judge gates

Desde la raíz del worktree aislado:

```bash
# RED/GREEN por delta: sustituir <test> por el test recién creado.
env -u PULSE_COMPASS_WRITE_MODE .venv/bin/python -m pytest app/tests/test_guided_dsu_handlers.py::<test> -q

# Cobertura enfocada después de cada delta.
env -u PULSE_COMPASS_WRITE_MODE .venv/bin/python -m pytest \
  app/tests/test_guided_dsu_handlers.py \
  app/tests/test_guided_comment_jobs.py \
  app/tests/test_compass_dsu.py -q

# Formato/lint de archivos tocados antes de la suite amplia.
.venv/bin/ruff format \
  app/src/modules/standup/blocks.py \
  app/src/modules/standup/handlers.py \
  app/src/modules/standup/comment_jobs.py \
  app/tests/test_guided_dsu_handlers.py \
  app/tests/test_guided_comment_jobs.py \
  app/tests/test_compass_dsu.py
.venv/bin/ruff check app/src/modules/standup app/tests

# Judge final.
env -u PULSE_COMPASS_WRITE_MODE .venv/bin/python -m pytest app/tests -q
.venv/bin/ruff check . --output-format=github
.venv/bin/ruff format . --check
git diff --check
git status --short
```

No se usa `hermes verify` como juez del backend.

---

## Decisiones pendientes antes de implementación

- **Piloto/despliegue:** requieren orden separada del owner después de gates verdes. Este spec no concede esa autorización.
- **Copy exacto del contexto:** usar `Daily Standup` y `FOCO DE HOY` como propuesta inicial; puede ajustarse antes del primer test visual sin cambiar el contrato.
- **Actualización de mensajes existentes:** permanece fuera de alcance; el cambio aplica solo a publicaciones nuevas.

## Relación con specs previos

- Extiende `openspec/SPEC-002-guided-ticket-aware-dsu.md`.
- Reemplaza únicamente su supuesto de una sola `Tarea principal` por uno o dos focos explícitamente acotados.
- No reabre las decisiones de Spectrum/Compass read-only, comentarios por avance ni schedule del DSU.
