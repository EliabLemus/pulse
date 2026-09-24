# Runbook: verificación de conexión (Tailscale/Funnel + Slack)

> Referencia operativa del check diario de Compass DSU (Pulse) y de qué hacer
> cuando falla. El check tiene dos mitades y cada una apunta a capas distintas.

## El check diario

- **Lun–Vie 09:00 GT** (15 min antes del DSU): Pulse envía un DM **solo al
  propietario**: "🔧 Verificación de conexión. Pulsa OK:" con un botón **OK**.
- Al pulsar **OK**, el payload vuelve por la ruta pública
  (Funnel → Caddy → Pulse) y Pulse confirma en el mismo chat:
  "✅ Conexión verificada: Tailscale y Slack responden."

Qué prueba cada mitad:

```text
DM llega              → Pulse → Slack funciona (contenedor vivo, token válido)
Botón responde        → Tailscale/Funnel → Caddy → Pulse funciona (ruta pública)
Silencio total        → algo está rojo (además del watchdog de endpoints)
```

## Paso 0 — Clasificar el fallo

```text
A. El DM de verificación nunca llegó
   → roto: Pulse → Slack (contenedor o token)

B. El DM llegó, pero el botón OK no responde
   → roto: Tailscale/Funnel → Caddy → Pulse (la ruta pública)
```

## Rama A — DM no llega (Pulse → Slack)

```text
1. docker ps                     → ¿pulse-techops-app-1 está up y healthy?
2. docker logs --since 15m pulse-techops-app-1 | grep -iE 'error|token|health'
   → "bot token invalid" = refrescar el token de la instalación desde la
     admin de la Slack app. NUNCA pedir/pegar tokens en chats.
3. curl -s localhost:3015/healthz → debe responder 200 {"status":"ok"}
4. Contenedor caído: docker compose up -d y volver a 1.
```

## Rama B — Botón sin respuesta (Funnel → Caddy → Pulse)

En orden de capa, de adentro hacia afuera:

```text
1. Caddy → contenedor:
   curl -s localhost:8081/pulse/healthz
   Falta aquí = contenedor o Caddy. Revisar contenedor (rama A paso 1)
   y el proceso Caddy antes de tocar Tailscale.

2. Funnel publicado:
   tailscale funnel status        → debe mostrar localhost:8081
   Si no:
     tailscale funnel reset
     tailscale funnel --bg --yes http://localhost:8081

3. Sesión de Tailscale colgada (síntoma histórico: exit 35 / error TLS
   genérico de Slack):
     tailscale down && tailscale up
   launchctl con exit 113 = variante App Store: cerrar la app Tailscale
   con osascript y reabrirla.

4. DNS público (Slack resuelve por Internet, no por tu tailnet):
   dig +short @1.1.1.1 nexus-2.tailf73d68.ts.net A
   Vacío = el problema es publicación DNS, no la app. Esperar la ventana
   de propagación y repetir. NO cambiar URLs.

5. Contrato completo desde los relays públicos (NUNCA solo desde la
   tailnet; MagicDNS puede enmascarar una publicación rota):
   /pulse/healthz            → 200 con "status":"ok"
   /pulse/slack/events       → 405
   /pulse/slack/interactions → 405
   Los 405 son correctos: rutas POST-only.
```

## Lo que ya corre solo

```text
Watchdog de endpoints (job 26a93c292b55): cada 5 min, 07:00–11:00 lun–vie,
verifica los tres contratos y auto-repara funnel → Caddy → contenedores
en silencio. Un falso positivo conocido: el probe vía proxy puede fallar
aun con todo sano; confirmar siempre con checks directos.

Reinicio nocturno preventivo (job d4080ca5bd2c): 00:15 GT reinicia el
cliente Tailscale preservando el Funnel y valida el contrato desde cada
relay público.
```

## Reglas fijas durante el diagnóstico

```text
Diagnóstico SIEMPRE desde resolvers públicos (1.1.1.1 / 8.8.8.8); un curl
exitoso por MagicDNS no prueba nada público.
Nunca tocar api.morgenruf.dev, Cloudflare ni GCP.
Nunca cambiar la Request URL de Slack
(nexus-2.tailf73d68.ts.net/pulse/slack/interactions).
Reinicios fuera del watchdog: proponer y esperar confirmación explícita.
```
