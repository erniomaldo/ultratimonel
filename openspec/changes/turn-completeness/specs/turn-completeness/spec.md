# Turn Completeness — Specs

## Alcance

Requisitos para los nuevos tools MCP `begin_turn` y `end_turn` que consolidan
el workflow de 5 calls en 2 calls, asegurando que cada intento persista sus
gates con detalle completo.

---

## Req-1: begin_turn — ejecutar gates frescos y crear intento

**SHALL** recibir `session_id` (str) y `project` (str) como argumentos.

**SHALL** recibir opcionalmente `message` (str) y `sender` (str) para extraer
contexto y ejecutar los gates de forma autónoma.

**SHALL** validar que no existe un turno activo previo (turn-scoping).

**SHALL** ejecutar INTERNAMENTE los 4 gates (1a/1b/1c/1e) de forma fresca
usando `extract_context()` + `run_triple_match()`, NO leyendo estados viejos
de la DB.

**SHALL** persistir cada resultado de gate via `persistence.upsert_gate_state()`
para que el estado refleje el momento exacto del begin_turn.

**SHALL** crear un nuevo intento con status='running' y persistir los gates
ejecutados en la columna `gates_detail` como JSON.

**SHALL** registrar el intento como turno activo para validación posterior.

**SHALL** retornar JSON con `intento_id`, `status: "started"`, conteo de
gates capturados, `gates_passed_so_far`, `overall`, y `context` extraído.

### Escenario 1a: begin_turn ejecuta gates frescos exitosamente

WHEN el agente llama `begin_turn(session_id="s1", project="voy-rojo",
message="test msg", sender="user")`
THEN se ejecutan los 4 gates de forma fresca (1a→1b→1c→1e)
AND cada gate se persiste en gate_state con estado actualizado
AND se crea un intento con status='running'
AND `gates_detail` contiene los 4 gates ejecutados con nombre, estado y mensaje
AND `gates_passed_so_far` refleja el conteo real de PASS/SKIP
AND el intento se registra como turno activo
AND se retorna `intento_id > 0` y `overall` con el estado agregado

### Escenario 1b: begin_turn sin message/sender (backward compat)

WHEN el agente llama `begin_turn(session_id="s2", project="alpha")`
(sin message ni sender — firma legacy)
THEN se usa sender por defecto "user" y message vacío
AND los gates se ejecutan de forma fresca igual que con params explícitos
AND se crea un intento con status='running'
AND se retorna `intento_id > 0`

### Escenario 1c: begin_turn servicios no disponibles -> WARN frescos

WHEN el agente llama `begin_turn(...)` y los servicios externos (agentmemory,
checkpoint, nextcloud) no responden
THEN los gates salen en estado WARN (no BLOCK ni SKIP)
AND se persisten como WARN en gate_state
AND se crea un intento con status='running'
AND `overall` es "WARN"
AND el turno puede continuar (el agente decide si procede)

### Escenario 1d: begin_turn duplicado (turno ya activo)

WHEN existe un turno activo y el agente llama `begin_turn()` nuevamente
THEN se detecta como huérfano si no corresponde al mismo intento running
AND se auto-completa el turno huérfano como "fail"
AND se crea el nuevo intento con gates frescos

---

## Req-2: end_turn — completar intento con validación de gates

**SHALL** recibir `session_id` (str), `project` (str), `mission_id` (int),
`checklist_item_id` (int) como argumentos.

**SHALL** validar que existe un turno activo (turn-scoping).

**SHALL** validar que el intento activo pertenece a `session_id` + `project`
(turn-scoping: no reintroducir bug de turn count desync).

**SHALL** ejecutar el bouncer endTurn: validar que todas las gates mandatory
están en estado PASS, SKIP o PENDING.

**SHALL** contar los gates que passed (PASS + SKIP) y actualizar `gates_passed`.

**SHALL** completar el intento con status='success' o 'fail',
`gates_passed`, y `gates_detail` actualizado.

**SHALL** limpiar el estado de turno activo.

**SHALL** retornar JSON con resultado de la validación y detalle de gates.

### Escenario 2a: end_turn exitoso — 4/4 gates PASS

WHEN existe un turno activo con intento ID 140
AND los 4 gates mandatory están en PASS
THEN el bouncer permite la completación
AND el intento se actualiza con status='success', gates_passed=4
AND `gates_detail` se actualiza con el estado final de cada gate
AND el turno activo se limpia
AND se retorna status="ok" con detalle de gates

### Escenario 2b: end_turn bloqueado — gate mandatory en BLOCK

WHEN existe un turno activo
AND una gate mandatory está en BLOCK
THEN el bouncer retorna action=block
AND el intento NO se actualiza (permanece 'running')
AND el turno activo permanece
AND se retorna JSON con error detallando qué gates fallaron

### Escenario 2c: end_turn sin turno activo

WHEN no existe un turno activo y el agente llama `end_turn()`
THEN se retorna error indicando que no hay turno activo
AND no se intenta completar ningún intento

### Escenario 2d: end_turn turn-scoping mismatch

WHEN el turno activo pertenece a session_id="s1"/project="p1"
AND el agente llama `end_turn(session_id="s2", project="p2", ...)`
THEN se retorna error de turn-scoping
AND el intento del turno activo NO se modifica

---

## Req-3: Flujo consolidado de 2 calls = workflow completo

**SHALL** el flujo `begin_turn` → trabajo → `end_turn` cubrir TODO lo que
cubría el flujo anterior de 5 calls:

1. Creación del intento (record_intento)
2. Captura de gates del estado actual (nuevo en begin_turn)
3. Ejecución de trabajo (sin cambios)
4. Validación de gates (complete_intento bouncer)
5. Cierre con detalle completo (complete_intento update)

### Escenario 3: Flujo completo de 2 calls

WHEN el agente ejecuta:
  1. `begin_turn(session_id="s1", project="voy-rojo")` → intento_id=200
  2. [trabajo del agente]
  3. `end_turn(session_id="s1", project="voy-rojo", mission_id=5, checklist_item_id=10)`
THEN el intento #200 queda con:
  - status='success' (o 'fail' si gates bloquean)
  - gates_passed=4 (conteo correcto)
  - gates_detail=array con 4 objetos {gate_name, state, message, ...}
  - completed_at populated
AND el dashboard API `/api/intentos/200` retorna gates poblados

---

## Req-4: Backward compatibility

**SHALL** `record_intento()` seguir funcionando como antes.

**SHALL** `complete_intento()` seguir funcionando con su bouncer existente.

**SHALL** la migración de schema v2→v3 ser backward compatible
(tabla intentos existe, nueva columna gates_detail es nullable).

### Escenario 4a: record_intento sigue funcionando

WHEN el agente llama `record_intento(session_id, project, mission_id, checklist_item_id)`
THEN se crea un intento con status='running' (comportamiento existente)
AND no se capturan gates automáticamente
AND el flujo legacy complete_intento → record_intento sigue funcionando

### Escenario 4b: complete_intento con bouncer existe

WHEN el agente llama `complete_intento(intento_id, gates_passed=4, session_id="s1", project="p1")`
THEN el bouncer valida gates desde gate_state (comportamiento existente)
AND si hay gates BLOCK/WARN mandatory, bloquea la completación
AND si todo está PASS/SKIP, completa el intento

---

## Req-5: Schema v3 — columna gates_detail

**SHALL** agregar columna `gates_detail TEXT` a la tabla `intentos`.

**SHALL** la columna debe ser nullable (INTENTS creados antes de v3 no la tienen).

**SHALL** el valor debe ser un JSON array de objetos con estructura:
```json
[
  {
    "gate_name": "1a",
    "state": "PASS",
    "mandatory": true,
    "message": "description",
    "duration_ms": 123
  }
]
```

### Escenario 5a: Migración v2→v3

WHEN la DB está en schema v2 y se conecta un servidor v3
THEN la migración agrega `gates_detail` a la tabla `intentos`
AND los intentos existentes funcionan normal (columna NULL)
AND los nuevos intentos vía begin_turn tienen gates_detail poblado

---

## Req-6: MCP client initialize timeout suficiente para bridges

**SHALL** el cliente MCP permitir un timeout de inicialización de al menos 30
segundos para servidores que operan mediante bridge http_to_stdio (p. ej.
Nextcloud MCP), donde el handshake `initialize` requiere una llamada HTTP
externa que puede tardar >5s.

**SHALL** el timeout de initialize estar separado del timeout de tool calls
(8s), ya que son fases con características de latencia distintas.

### Escenario 6a: Initialize timeout suficiente para bridge Nextcloud

WHEN el MCP client conecta contra un servidor bridge http_to_stdio (Nextcloud)
AND el handshake initialize tarda ~2-4s (latencia HTTP real)
THEN el cliente NO corta la conexión por timeout (timeout=30s)
AND el servidor se inicializa correctamente
AND los gates dependientes del servidor (1c Collective, 1e Deck) pueden
    resolverse a PASS en asserts posteriores

### Escenario 6b: Initialize timeout no afecta tool calls

WHEN un tool call al mismo servidor bridge tarda más de 8s
THEN el timeout de tool calls (8s) sigue aplicándose independientemente
AND el initialize timeout (30s) NO interfiere con el comportamiento de
    tool calls
