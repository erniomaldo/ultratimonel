# Turn Completeness — Proposal

## Problema

Los intentos creados con el flujo consolidado `begin_turn` / `end_turn` registran
gates VACIOS (`gates_passed=0`, `gates=[]`) aunque el turno pase los gates.

El flujo anterior (`record_intento` + `complete_intento` con
`session_id`/`project`/`gates_passed`) SÍ persistía los 4 gates con detalle:
evidencia, intento #140 con 4/4 y array de gates poblado via dashboard API.

En la consolidación de 5 tool calls a 2 (`begin_turn` + `end_turn`) se perdieron
pasos críticos del workflow completo de ultratimonel porque **los tools nunca
fueron implementados en server.py**. El plugin `plugin_preflight.py` ya tenía
hooks que referencian `mcp__ultratimonel__begin_turn` y
`mcp__ultratimonel__end_turn`, pero las funciones no existían.

## Objetivo

`begin_turn` + `end_turn` deben cubrir TODO el workflow que antes cubría el
flujo de 5 calls. Un turno debe quedar COMPLETO con sus gates persistidos, sin
llamadas extra.

## Scope

### In-scope
- Implementar `begin_turn(session_id, project)` como tool MCP en server.py
- Implementar `end_turn(session_id, project, mission_id, checklist_item_id)` como tool MCP en server.py
- Agregar columna `gates_detail` (JSON) a la tabla `intentos` + migración v3
- Persistence methods: `capture_gates_for_intento()`, `complete_intento_with_gates()`
- Turn-scoping server-side (validar que el intento pertenezca al turno actual)
- Backward compatibility: `record_intento`/`complete_intento` siguen funcionando
- Tests nuevos para el flujo de 2 calls

### Out-of-scope
- NO modificar `plugin_preflight.py` (es de otro change)
- NO modificar dashboard_server.py
- NO modificar la tabla `gate_state` (ya existe y funciona)
- NO cambiar el patrón de 1 ciclo por respuesta del plugin

## Decisiones confirmadas

| Decisión | Rationale |
|----------|-----------|
| Columna JSON `gates_detail` en `intentos` | Snapshot point-in-time; más simple que tabla separada; evita joins |
| Estado de turno en module-level globals | Simple, thread-safe con锁 si es necesario; el plugin ya maneja su propio estado |
| `begin_turn` captura gates del estado actual | Sin llamada extra; usa `list_gate_states()` existente |
| `end_turn` replica bouncer de `complete_intento` | Misma validación: mandatory gates deben ser PASS/SKIP/PENDING |
| Turn-scoping via global `_active_intento` | Validación server-side de que el intento pertenece al turno actual |

## Impacto

- Los intentos creados vía `begin_turn`/`end_turn` tendrán `gates_passed` correcto
  y `gates_detail` poblado
- El dashboard API `/api/intentos/{id}` mostrará gates completos
- El flujo de 2 calls cubre todo el workflow anterior de 5 calls
- Backward compatible: existing tools siguen funcionando

## Artefactos generados
- proposal.md (este archivo)
- specs/turn-completeness/spec.md — requerimientos SHALL con escenarios
- design.md — ADRs con rationale y alternativas
- tasks.md — tareas por fase PAC
