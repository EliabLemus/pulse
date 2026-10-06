# SPEC-002: DSU guiado con contexto de tickets de Compass

**Estado:** Draft — pendiente de aprobación del owner. No implementación, despliegue ni push hasta aprobar este spec.

## Objetivo

Mantener Compass DSU como el flujo diario de avances del sprint, pero reemplazar el formulario único por un recorrido guiado de tres pasos. Cada avance publicado en Slack debe conservar el contexto humano del ticket: enlace, clave y título.

El bot seguirá siendo una integración de **actualizaciones solamente**: podrá publicar `post_comment` en Compass, pero nunca cambiará estado, prioridad, asignado, sprint, fechas ni visibilidad de tickets.

---

## Estado actual verificado

- El DM y el modal reciben tareas del sprint actual filtradas por `assigneeEmail`.
- Los tickets `done` se excluyen antes de llegar al DM/modal.
- El modal ya renderiza título y enlace de cada ticket, pero el DM lista la clave como texto plano.
- Las tres preguntas actuales se capturan en un solo modal (`standup_form_modal`). Las respuestas publicadas al hilo convierten referencias de ticket en enlace, pero no adjuntan el título.
- Los comentarios de Compass se crean únicamente con `post_comment` y la prioridad de hoy nunca se sincroniza como comentario.
- `get_my_work` / Follow Up queda fuera de este spec: no define los tickets del DSU y no se modifica ni se muestra en este flujo.

---

## Experiencia final

```text
DM
  → botón “Completar mi avance”
  → paso 1/3: avance de ayer por ticket
  → paso 2/3: prioridad de hoy con tickets visibles
  → paso 3/3: bloqueos por ticket
  → confirmación privada + publicación al hilo individual de Slack
  → comentarios por ticket en Compass, cuando corresponda
```

### Paso 1 de 3 — Avance de ayer

Cada tarea abierta del sprint se muestra con título, enlace y un campo propio:

```text
1 de 3 · Avance de ayer

TECH-8 — Despliegue Beta en TechOps ZARM Space
[ Describe el avance de este ticket ]

TECH-9 — Migración a Cloud Run + Cloud SQL
[ Describe el avance de este ticket ]
```

El usuario puede dejar campos vacíos. Un campo no vacío es candidato a comentario en ese ticket de Compass.

### Paso 2 de 3 — Prioridad de hoy

Mantiene visibles todos los tickets abiertos como contexto, incluyendo enlace, título y alerta de vencimiento. Además exige seleccionar una tarea principal del sprint y escribir el objetivo concreto del día:

```text
2 de 3 · Prioridad de hoy

Sprint 2
• TECH-8 — Despliegue Beta en TechOps ZARM Space
• TECH-9 — Migración a Cloud Run + Cloud SQL

Tarea principal
[ TECH-8 — Despliegue Beta en TechOps ZARM Space ▼ ]

¿Qué harás concretamente?
[ Validaré el pipeline Bucket → Cloud Run ]
```

La respuesta se publica en Slack como compromiso diario, pero nunca genera comentario en Compass.

### Paso 3 de 3 — Bloqueos

Cada tarea abierta se vuelve a mostrar con contexto y campo propio. Los campos vacíos significan que no hay bloqueo que registrar para ese ticket.

```text
3 de 3 · Bloqueos

TECH-8 — Despliegue Beta en TechOps ZARM Space
[ Describe el bloqueo o deja vacío ]
```

Un bloqueo real por ticket se publica como comentario en Compass. La detección existente de negaciones en español se conserva: `Sin bloqueo`, `Sin bloqueos`, `Nada`, `Ninguno`, etc., no generan escalación.

---

## Requisitos funcionales

### R1 — Claves y títulos visibles donde aportan contexto

- Cada ticket mostrado en DM, pasos 1–3 y mensajes publicados debe usar un enlace Slack mrkdwn a `https://compass.zubale.com/tickets/<KEY>`.
- En los hilos de Slack, una respuesta asociada a una tarea se renderiza como un encabezado legible y un cuerpo separado:

```text
*<TECH-8 enlazado> — Despliegue Beta en TechOps ZARM Space*
Terminé la validación del pipeline.
```

- El título es contexto visual, no parte del avance. El texto crudo escrito por la persona se preserva para persistencia y sincronización; el título se añade exclusivamente en la representación de Slack.
- Solo se expande título para claves presentes en `session.compass_tasks`; una clave arbitraria no debe disparar búsqueda adicional ni revelar metadatos de otro ticket.

### R1.1 — Un título no cuenta como avance

- En los pasos 1 y 3, el título se muestra fuera del campo editable. El usuario escribe únicamente el contenido nuevo del avance o bloqueo.
- Antes de permitir Siguiente o Enviar, cada campo no vacío se normaliza: trim, collapse de espacios, casefold y eliminación de puntuación decorativa.
- Un campo se rechaza con error de campo si, tras normalizar, equivale a cualquiera de: clave sola (`TECH-8`), título solo, clave seguida solo del título, o texto sin caracteres alfanuméricos.
- Error visible:

```text
Eso solo repite el ticket. Escribe qué cambió, qué resultado lograste o qué bloqueo tienes.
```

- Un texto que contiene contenido adicional se acepta, incluso si empieza con la clave o el título. Ejemplo válido: `TECH-8: terminé la validación del pipeline.`
- No se usa un mínimo arbitrario de palabras ni clasificación con LLM: el objetivo es bloquear duplicados vacíos, no juzgar la calidad semántica de una actualización humana.
- Un campo inválido no publica al hilo ni ejecuta `post_comment`; el usuario corrige el mismo paso del modal.

### R2 — Alerta visual para vencidos

- Una tarea abierta con fecha límite anterior al día local del schedule se marca como vencida en rojo:

```text
🔴 <TECH-8 enlazado> — Despliegue Beta en TechOps ZARM Space
Vencida desde 22 sep
```

- La alerta aparece en el DM y en los tres pasos del modal.
- Esta alerta no escribe ni altera Compass y no pretende retirar elementos de Follow Up.
- La ausencia de `dueDate`, una fecha inválida o una fecha de hoy/futura no genera alerta.

### R3 — Validación manual de estado antes de comentar progreso

- El bot nunca cambia estados automáticamente.
- Para cada avance o bloqueo por ticket, antes de ejecutar `post_comment`, el bot consulta el ticket con el tool MCP read-only `get_ticket`.
- Si la categoría de estado viva es `active`, publica el comentario.
- Si es `todo`, no publica el comentario de ese ticket y conserva el modal con el error:

```text
TECH-8 todavía está en “Todo”. Cámbiala a “In progress” en Compass y vuelve a enviar este paso.
```

  El mensaje incluye el enlace de ese ticket.
- Si es `blocked`, permite publicar el comentario. Un ticket bloqueado necesita registrar contexto, no ser forzado a `In progress`.
- Si es `done`, no publica comentario y pide quitar ese texto o usar una tarea abierta.
- Si la consulta read-only falla, el avance del DSU sigue siendo publicable en Slack, pero ese comentario no se sincroniza a Compass y la confirmación identifica las claves no sincronizadas. Esto preserva el comportamiento fail-open actual de la captura diaria sin inventar estados.

### R4 — Navegación guiada sin perder respuestas

- Se usa una única superficie modal actualizada entre pasos; no una cadena de modales apilados.
- `private_metadata` mantiene `team_id:user_id` y el paso actual.
- Al confirmar un paso, sus respuestas se guardan en `state_store`/Redis antes de renderizar el siguiente.
- `Atrás` conserva exactamente los valores introducidos en pasos anteriores.
- Si la sesión expiró, el usuario recibe el flujo existente para iniciar un nuevo avance; no se publican respuestas parciales ni comentarios.
- El paso 3 finaliza el standup usando `_complete_standup` y reemplaza las respuestas del session de forma atómica.

### R5 — Publicación al hilo y Compass

- Se conserva el modelo actual: un mensaje raíz individual por usuario y día en `#techops-automation`, con su propio hilo nativo.
- La publicación de Slack incluye títulos para las claves conocidas del sprint.
- Los comentarios Compass conservan el encabezado `Avance de <Nombre>:` y únicamente contienen contenido por ticket; no incluyen el compromiso de prioridad de hoy.
- La edición del avance conserva esta regla: el último contenido enviado es la fuente visible en Slack; no se cambia automáticamente ningún campo de workflow de Compass.

---

## Fuera de alcance

- Mostrar Follow Up a usuarios, `get_my_work`, OAuth por usuario o `get_user_follow_up`.
- Crear, resolver, mover, asignar, repriorizar o reprogramar tickets.
- Cambiar estados desde Slack o añadir una acción “Marcar en progreso”. El usuario lo hace directamente en Compass.
- Buscar y revelar títulos de tickets fuera del contexto del sprint asignado a la persona.
- Cambiar el canal productivo, horarios, días de envío o las reglas de silenciamiento de fin de semana.

---

## Diseño técnico

### Archivos previstos

- `app/src/blocks.py`
  - Extraer un renderizador único de tarjeta/línea de ticket: enlace, título y estado de vencimiento.
  - Reemplazar `standup_form_modal` por builders deterministas para paso 1, paso 2 y paso 3.
  - Añadir renderizador de respuesta publicada que inyecte títulos solo desde el mapa de tareas de la sesión.

- `app/src/handlers.py`
  - Abrir el paso 1 desde `fill_in_form`.
  - Añadir handlers de navegación de pasos y submit del wizard.
  - Persistir el paso actual/valores antes de actualizar la vista.
  - Validar tickets vivos antes de `post_comment` y devolver errores por ticket sin mutaciones.
  - Pasar el mapa `key → {title, dueDate, url}` al formateador del mensaje de hilo.

- `app/src/state.py`
  - Añadir campos serializables para `wizard_step`, respuestas por paso y selección de prioridad.
  - Conservar compatibilidad con sesiones existentes y `replace_answers`.

- `app/src/compass.py`
  - Añadir un método read-only `get_ticket(key)` basado en el tool MCP `get_ticket`.
  - Validar forma del payload y no registrar secretos ni cuerpos arbitrarios.

- `app/tests/test_pulse_single_form.py`
  - Cubrir el wizard, las tarjetas con título/enlace, vencidos y persistencia Atrás/Siguiente.

- `app/tests/test_handlers.py`
  - Cubrir render en hilo con título; prioridad sin comentario Compass; reglas `todo`/`active`/`blocked`/`done`; fallo de consulta read-only sin pérdida del DSU.

- `app/tests/test_compass.py`
  - Cubrir `get_ticket` con mock de `_call_mcp`, forma inválida y errores del MCP.

- `app/tests/test_spanish_vocabulary.py`
  - Extender solo si se introduce copy visible nueva; `update` queda prohibido y el vocabulario visible usa `avance`.

### Compatibilidad

- `statusCategory: done` continúa filtrándose en `CompassClient` y en los builders de Block Kit.
- Las reglas de tickets para comentarios siguen limitadas a avance de ayer y bloqueos. Prioridad de hoy sigue sin sincronizar.
- La app no usa su MCP local (`mcp_server.py`/`mcp_http.py`) para estos datos; consume exclusivamente el MCP externo de Compass a través de `CompassClient`.

---

## Deltas de implementación

### Delta 001 — Modelo de sesión y builders del wizard

**Objetivo:** construir los tres pasos deterministas sin cambiar aún la publicación ni Compass.

- Añadir campos de wizard a `UserSession`, serialización/deserialización y helpers de reemplazo por índice.
- Escribir tests RED para paso 1/2/3, selección de prioridad, Atrás/Siguiente y preservación de valores.
- Crear builders de modal con los campos y contexto de tickets descritos.
- Extraer renderizador único para enlaces, títulos y vencidos.

### Delta 002 — Publicación de hilos con títulos

**Objetivo:** hacer que el hilo diario conserve el contexto de cada ticket sin alterar los datos almacenados.

- Escribir tests RED para una línea conocida `TECH-8: texto` → enlace + título + texto.
- Agregar el mapa de tareas de sesión al formateo de publicación.
- Mantener intactas claves desconocidas y respuestas sin ticket.

### Delta 003 — Validación live read-only antes de comentarios

**Objetivo:** impedir comentarios de progreso en `Todo` o `Done`, sin modificar Compass y sin perder el DSU cuando el MCP falla.

- Añadir `CompassClient.get_ticket` y tests de contrato MCP.
- Escribir tests RED para cada categoría de estado y para el fallo del MCP.
- Integrar validación justo antes de `post_comment`.
- Implementar error de modal por ticket para `Todo`/`Done`; para error MCP, completar Slack y reportar claves no sincronizadas.

### Delta 004 — Piloto privado y cierre de aceptación

**Objetivo:** validar UX completa sin afectar la operación productiva.

- Ejecutar Judge local completo.
- Desplegar únicamente bajo orden explícita del owner a una imagen/instancia de piloto que entregue solo al canal privado de prueba, no a `#techops-automation`.
- Hacer recorrido real: ticket activo, ticket vencido, ticket Todo, ticket bloqueado, prioridad, Atrás, reenvío y comentario Compass mock/live autorizado.
- Solo después de los criterios de aceptación y orden explícita del owner, planificar el lanzamiento al schedule productivo.

---

## Criterios de aceptación

```yaml
- id: AC-1
  criterion: Cada clave de ticket mostrada en DM, pasos del modal y mensaje de hilo tiene enlace a Compass y título.
  test: tests de blocks + handler verifican '<https://compass.zubale.com/tickets/TECH-8|TECH-8> — Título'.

- id: AC-2
  criterion: Repetir solo la clave, solo el título, o clave+título no cuenta como avance/bloqueo ni llega a Slack o Compass.
  test: tests parametrizados de normalización verifican error de campo y cero llamadas a publicación/post_comment.

- id: AC-3
  criterion: Un ticket vencido abierto se marca 🔴 y muestra la fecha de vencimiento; una fecha futura o vacía no.
  test: test parametrizado con dueDate pasada, hoy, futura, ausente e inválida.

- id: AC-4
  criterion: El paso Prioridad de hoy mantiene la lista de tickets y obliga seleccionar una tarea principal del sprint.
  test: builder contiene contexto, select con tareas conocidas y campo de objetivo.

- id: AC-5
  criterion: La prioridad de hoy nunca produce post_comment.
  test: mock CompassClient.assert_not_called para respuesta exclusiva del paso 2.

- id: AC-6
  criterion: Un avance para estado todo se rechaza con enlace e instrucción de pasar a In progress, sin post_comment.
  test: get_ticket devuelve statusCategory todo; post_comment no se invoca.

- id: AC-7
  criterion: Un avance para active y un bloqueo para blocked publican comentario; done no.
  test: matriz active/blocked/done con assertions de post_comment.

- id: AC-8
  criterion: Si get_ticket falla, el avance se publica en Slack y la confirmación señala la clave no sincronizada; no se modifica Compass.
  test: mock get_ticket lanza excepción y se verifica publicación + cero post_comment.

- id: AC-9
  criterion: Atrás/Siguiente conserva todos los textos y la selección de prioridad sin publicar contenido parcial.
  test: tests de state_store y handlers de navegación.

- id: AC-10
  criterion: La suite completa, ruff repo-wide, formato y diff limpio pasan antes de cualquier piloto.
  test: comandos Judge de esta spec.
```

---

## Judge gates

```bash
cd /Users/openjaime/projects/morgenruf
uv venv .venv
uv pip install -r app/requirements.txt pytest pytest-mock ruff

env -u PULSE_COMPASS_WRITE_MODE .venv/bin/python -m pytest app/tests -q
.venv/bin/ruff check . --output-format=github
.venv/bin/ruff format . --check
git diff --check
```

Piloto e2e adicional, antes de lanzamiento:

```text
1. Confirmar que la imagen/contendor del piloto contiene el commit esperado.
2. Verificar DM y los tres pasos con una cuenta piloto.
3. Confirmar que los posts llegan solo al canal privado de prueba.
4. Verificar que un ticket active recibe exactamente un comentario con el nombre real del usuario.
5. Verificar que un ticket todo no recibe comentario ni mutación y entrega el enlace a Compass.
6. Verificar que ningún estado, sprint, prioridad, assignee o fecha cambió.
7. Confirmar que el flujo productivo y el schedule de #techops-automation siguen sin tocarse.
```

## Rollout y rollback

- **Piloto:** instancia/schedule aislado, canal privado de prueba y participantes de prueba. No reutilizar `#techops-automation` para validar cambios.
- **Lanzamiento:** requiere aprobación explícita después del piloto e2e verde.
- **Rollback:** revertir el commit de la feature y desplegar la imagen previa. No hay migración de DB obligatoria ni cambio de estado remoto, por lo que no existe reparación de datos Compass.
