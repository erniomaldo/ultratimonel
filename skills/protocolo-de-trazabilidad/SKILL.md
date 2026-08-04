---
name: protocolo-de-trazabilidad
description: "Quad Persistence protocol — begin_turn → work → end_turn. Consolidated two-tool flow."
version: 4.0.0
license: MIT
tags: [persistence, protocol, checkpoint, agentmemory, deck, notes, ultratimonel]
---

# Protocolo de Trazabilidad — Ultratimonel (v4)

## ⚠️ Advertencia

**Este skill describe el flujo CORRECTO y actual.** Si ves referencias a `assert_gates`, `record_intento`, `complete_intento` o `complete_gate` como calls separadas, están deprecadas. El flujo consolidado reemplaza 5+ calls con solo 2.

---

## El flujo obligatorio — 4 pasos, no negociables

Cada mensaje del usuario sigue EXACTAMENTE este orden:

```
[Usuario envía mensaje]
    ↓
Paso 1: begin_turn(session_id, project, mission_id, checklist_item_id)
        ├── Detecta proyecto y contexto
        ├── Pasa las 4 gates (memoria, checkpoint, collective, deck)
        └── Crea el intento con scope de turno → retorna intento_id
    ↓
Paso 2: Trabajar — ejecutar tools, recopilar datos, hacer análisis
    ↓
Paso 3: end_turn(intento_id, status="success")
        ├── Valida que intento_id pertenece al turno actual (turn-scoping)
        ├── Ejecuta el bouncer de gates (registra el resultado real)
        ├── Completa SIEMPRE: final_status "success" o "fail" + gates_detail completo
        ├── Nunca deja el estado roto (ni running huérfano, ni turno atascado)
        └── Limpia el turno activo
    ↓
Paso 4: Presentar resultados al usuario
```

### Nota sobre begin_turn y assert_gates (2026-08-03)

- `begin_turn` es **autocontenido**: ejecuta los 4 gates internamente (assert fresco
  contra los servicios) y persiste el snapshot en el intento (`gates_detail`).
  El agente NO necesita llamar `assert_gates()` manualmente — el flujo es de 2 calls.
- Params opcionales: `message=""`, `sender="user"` (contexto del assert).
- `assert_gates` sigue existiendo como tool (el plugin la usa en pre_llm_call para
  inyectar contexto), pero no es parte del flujo del agente.

### ⚠️ Reglas de hierro

1. **begin_turn es obligatorio.** No hay trabajo sin intento. Si no puedes vincular a una misión (mission_id > 0, checklist_item_id > 0), no llames a begin_turn — reporta que el trabajo queda sin registrar.

2. **Vincular a misión primero.** Antes de begin_turn, debes tener mission_id y checklist_item_id válidos de la tabla `missions`. Si no existe card en Deck:
   - Crea la card
   - `sync_tasks(project)` para sincronizarla
   - `mission_list(project)` para obtener mission_id y checklist_item_id

3. **end_turn cierra el intento.** Sin excepción. Un intento abierto = trabajo sin registrar.

4. **No hay paso 5.** La generación (respuesta al usuario) es el último paso, después de end_turn.

5. **El bouncer bloquea tools fuera del ciclo.** El plugin `ultratimonel-preflight` en el runtime de Hermes verifica que las gates estén PASS antes de permitir tools críticas. No intentes saltarlo.

---

## ¿Qué pasó con assert_gates, record_intento, complete_gate?

| Tool deprecada | Reemplazo | Motivo |
|---|---|---|
| `assert_gates` (call separada) | `begin_turn()` | Consolidado: begin_turn ejecuta las 4 gates internamente |
| `record_intento()` | `begin_turn()` | begin_turn crea el intento y retorna intento_id |
| `complete_intento()` | `end_turn()` | end_turn completa el intento del turno actual |
| `complete_gate()` | `begin_turn()` | begin_turn pasa las gates automáticamente |

**No uses las tools deprecadas.** El bouncer del plugin puede rechazarlas.

---

## 🎯 Cómo ejecutar begin_turn de verdad (runtime MCP)

Las tools MCP NO son funciones nativas: van por `tool_describe` + `tool_call` con el nombre completo `mcp__ultratimonel__begin_turn`.

### session_id — qué valor usar (NO experimentes)

| Fuente | Orden | Evidencia |
|---|---|---|
| `echo $HERMES_SESSION_ID` | 1º — si está definido en el entorno | sesiones 20260728_211911, 20260730_182025, 20260728_161629 → OK |
| `"default"` | 2º — **siempre funciona** | probado OK 2026-07-29 (intento #151) |
| `"current"` | 3º — legacy | sesiones Matrix 2026-06 → OK |

**PROHIBIDO (workaround):** leer la DB directo (`sqlite3 ~/.hermes/ultratimonel.db`), husmear `sessions.json`, o escanear el filesystem buscando el session_id. Eso está bloqueado por deny patterns POR ALGO EXISTE. Si dudas → usa `"default"` o pregunta al usuario.

### Ejemplo completo (flujo real)

```json
// 1. tool_describe(name="mcp__ultratimonel__begin_turn") → ver schema
// 2. tool_call:
{
  "name": "mcp__ultratimonel__begin_turn",
  "arguments": {
    "session_id": "default",
    "project": "ultratimonel",
    "mission_id": 482,
    "checklist_item_id": 2333
  }
}
// → {"status":"ok","intento_id":155,"turno":1}

// 3. Trabajar con tools normales
// 4. tool_call:
{
  "name": "mcp__ultratimonel__end_turn",
  "arguments": {"intento_id": 155, "status": "success"}
}
// → {"status":"ok"}
```

**Pitfalls:**
- Si `begin_turn` falla: **DETENTE y reporta.** No reintentes con valores inventados, no parchees.
- Si no hay misión vinculable: NO llames begin_turn — reporta "trabajo sin registrar" (precedente correcto: sesión 20260730_200925).
- `mission_list(project)` te da `mission_id` y `checklist_item_id` — no los adivines.
- Un solo ciclo begin→trabajo→end por turno. Múltiples ciclos = bug conocido en el plugin.

---

## Quad Persistence (los 4 sistemas)

Aunque el flujo de tools se consolidó, los 4 sistemas de persistencia siguen activos:

### 1. AgentMemory / Memory tool

Hechos durables, decisiones, bugs, patrones, descubrimientos, preferencias del usuario.
Memoria semántica cross-session.

**Cuándo:** después de cada paso lógico significativo (decisión tomada, bug arreglado, lección aprendida).

### 2. Checkpoint (`mcp__checkpoint__*`)

Coordinación de estado entre workers, tareas largas y sesiones. Previene duplicación en flujos nocturnos y batch.

**Cuándo:** cada fase de un plan checkpointea su resultado antes de pasar a la siguiente.

### 3. Deck (Nextcloud Deck)

Tarjeta en el board con estado, checklist PAC, referencias a commits y PRs.
**Fuente de verdad de PLANIFICACIÓN/INTENCIÓN** — no de ejecución.

⚠️ **Deck se desactualiza.** Siempre verificar con `gh` antes de reportar estado como verdad.

### 4. Nextcloud Notes

Documentación de protocolos y referencias maestras.
**No es collective, ni forms, ni pages — es Notes específicamente.**

**Regla:** usar `nc_notes_search_notes` y `nc_notes_get_note`, NO collectives.

---

## Directives — qué hacer cuando una gate falla

Aunque `begin_turn()` ejecuta las gates internamente, puedes necesitar acciones correctivas:

| Gate fallida | Prioridad | Acción |
|---|---|---|
| 1a (sin memorias) | medium | Memory.save — guarda contexto del proyecto |
| 1a (no disponible) | high | Verifica que el sistema de memoria esté activo |
| 1b (checkpoint nuevo) | low | Checkpoint.set_state — checkpoint inicial |
| 1c (sin collective) | high | Crea documentación del proyecto en Collective |
| 1c (steering incompleta) | medium | Agrega páginas de steering al collective |
| 1e (sin board) | medium | Crea board en Deck para el proyecto |
| 1e (sin cards) | low | Agrega cards al board del proyecto |

---

## Verificación rápida — ¿estás violando el protocolo?

- ❌ ¿Llamaste a `record_intento`? → usa `begin_turn`
- ❌ ¿Llamaste a `complete_intento`? → usa `end_turn`
- ❌ ¿Ejecutaste tools sin `begin_turn` primero? → violación
- ❌ ¿Respondiste al usuario sin cerrar con `end_turn`? → violación
- ❌ ¿Usaste mission_id=0? → violación (debe ser > 0, linkeado a misión real)
- ✅ `begin_turn` → trabajo → `end_turn` → responder → flujo correcto

---

## Grace Period

El plugin `ultratimonel-preflight` tiene `ULTRATIMONEL_GRACE_TURNS=3`. Durante los primeros 3 turnos el bouncer NO bloquea tools aunque las gates fallen. A partir del turno 4 el bouncer es estricto.
