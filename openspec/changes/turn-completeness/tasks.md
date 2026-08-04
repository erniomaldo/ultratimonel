# Turn Completeness — Tasks

## Fase 1: Schema + Persistence

- [x] 1.1 Agregar columna `gates_detail TEXT` a tabla `intentos` (migración v3)
- [x] 1.2 Actualizar `SCHEMA_VERSION` a 3 y `SCHEMA_DESCRIPTION`
- [x] 1.3 Agregar `DDL_V3_ADDITIONS` con ALTER TABLE
- [x] 1.4 Actualizar `_init_db()` para aplicar adiciones v3
- [x] 1.5 Agregar `capture_gates_for_intento(intento_id, gates)` a Persistence
- [x] 1.6 Agregar `complete_intento_with_gates(intento_id, status, gates_passed, gates_detail)` a Persistence
- [x] 1.7 Actualizar `create_intento()` para aceptar `gates_detail` opcional

## Fase 2: Server — begin_turn

- [x] 2.1 Agregar globals de turno: `_active_intento`, `_turn_lock` (RLock)
- [x] 2.2 Helper `_get_active_intento()` con locking
- [x] 2.3 Helper `_set_active_intento()` con locking
- [x] 2.4 Implementar tool `begin_turn(session_id, project)` en server.py
- [x] 2.5 begin_turn: validar no hay turno activo
- [x] 2.6 begin_turn: capturar gates via `list_gate_states()`
- [x] 2.7 begin_turn: crear intento con gates_detail JSON
- [x] 2.8 begin_turn: registrar como turno activo

## Fase 3: Server — end_turn

- [x] 3.1 Extraer `_validate_gates_for_completion(session_id, project)` de complete_intento
- [x] 3.2 Implementar tool `end_turn(session_id, project, mission_id, checklist_item_id)` en server.py
- [x] 3.3 end_turn: validar turno activo existe
- [x] 3.4 end_turn: validar turn-scoping (intento pertenece a session+project)
- [x] 3.5 end_turn: ejecutar bouncer de gates
- [x] 3.6 end_turn: completar intento con gates_passed y gates_detail actualizado
- [x] 3.7 end_turn: limpiar estado de turno activo

## Fase 4: Tests

- [x] 4.1 Test: begin_turn con 4 gates PASS → intento con gates_detail poblado
- [x] 4.2 Test: begin_turn sin gates previos → intento con gates_detail=[]
- [x] 4.3 Test: begin_turn duplicado → error, no crea nuevo intento
- [x] 4.4 Test: end_turn 4/4 gates PASS → intento completado success
- [x] 4.5 Test: end_turn gate BLOCK → bloqueado, intento permanece running
- [x] 4.6 Test: end_turn sin turno activo → error
- [x] 4.7 Test: end_turn turn-scoping mismatch → error
- [x] 4.8 Test: flujo completo begin_turn → end_turn = workflow completo
- [x] 4.9 Test: backward compat — record_intento + complete_intento siguen funcionando
- [x] 4.10 Test: migración v2→v3 — columna gates_detail existe

## Fase 5: Verificación

- [x] 5.1 Ejecutar `pytest tests/ -q --tb=short` — 97/97 passing
- [x] 5.2 Verificar que tests existentes no se rompieron (91/91 sin regresiones)
- [x] 5.3 Verificar py_compile en server.py y persistence.py

## Fase 6: Fix dependiente — MCP initialize timeout

- [x] 6.1 Identificar causa raíz: bridge http_to_stdio tarda >5s en handshake
- [x] 6.2 Aumentar initialize timeout de 5s a 30s en mcp_client.py (commit 7bc8d7a)
- [x] 6.3 Verificar en producción: gates 1c/1e pasan a PASS, intentos #171 y #172 SUCCESS 4/4

## Fase 7: Documentación retrospectiva

- [x] 7.1 Agregar ADR-008 en design.md (timeout fix)
- [x] 7.2 Agregar Req-6 en spec.md (MCP timeout requirement)
- [x] 7.3 Actualizar verify-report.md con evidencia final de producción
