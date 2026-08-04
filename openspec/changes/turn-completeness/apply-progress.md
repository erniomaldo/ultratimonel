# Turn Completeness — Apply Progress

## Ejecución 1: Implementación completa

### Fase 1: Schema + Persistence ✅
- [x] 1.1 Agregar columna `gates_detail TEXT` a tabla `intentos` (migración v3)
- [x] 1.2 Actualizar `SCHEMA_VERSION` a 3 y `SCHEMA_DESCRIPTION`
- [x] 1.3 Actualizar `_init_db()` para aplicar adiciones v3 en fresh install, v2→v3 migration, y idempotent check
- [x] 1.4 Agregar `capture_gates_for_intento(intento_id, gates)` a Persistence
- [x] 1.5 Agregar `complete_intento_with_gates(intento_id, status, gates_passed, gates_detail)` a Persistence
- [x] 1.6 Fix pre-existente: get_intento eliminó alias `gs` sin JOIN (causaba OperationalError)

### Fase 2: Server — begin_turn ✅
- [x] 2.1 Agregar globals de turno: `_active_intento`, `_turn_lock` (RLock)
- [x] 2.2 Helper `_get_active_intento()` con locking
- [x] 2.3 Helper `_set_active_intento()` con locking
- [x] 2.4 Helper `_clear_active_intento()` con locking
- [x] 2.5 Implementar tool `begin_turn(session_id, project, mission_id=0, checklist_item_id=0)` en server.py
- [x] 2.6 begin_turn: validar no hay turno activo (turn-scoping)
- [x] 2.7 begin_turn: capturar gates via `list_gate_states()`
- [x] 2.8 begin_turn: crear intento con `create_intento()` y persistir gates con `capture_gates_for_intento()`
- [x] 2.9 begin_turn: registrar como turno activo

### Fase 3: Server — end_turn ✅
- [x] 3.1 Extraer `_validate_gates_for_completion(session_id, project)` de complete_intento
- [x] 3.2 Actualizar `complete_intento()` para usar `_validate_gates_for_completion()` (DRY)
- [x] 3.3 Implementar tool `end_turn(session_id, project, mission_id=0, checklist_item_id=0)` en server.py
- [x] 3.4 end_turn: validar turno activo existe
- [x] 3.5 end_turn: validar turn-scoping (intento pertenece a session+project)
- [x] 3.6 end_turn: ejecutar bouncer de gates via `_validate_gates_for_completion()`
- [x] 3.7 end_turn: capturar estado final de gates
- [x] 3.8 end_turn: completar intento con `complete_intento_with_gates()`
- [x] 3.9 end_turn: limpiar estado de turno activo

### Fase 4: Tests ✅
- [x] 4.1 Test: begin_turn con 4 gates PASS → intento con gates_captured=4
- [x] 4.2 Test: begin_turn sin gates previos → gates_captured=0
- [x] 4.3 Test: begin_turn duplicado → error, no crea nuevo intento
- [x] 4.4 Test: end_turn 4/4 gates PASS → intento completado success
- [x] 4.5 Test: end_turn gate BLOCK → bloqueado, intento permanece running
- [x] 4.6 Test: end_turn sin turno activo → error
- [x] 4.7 Test: end_turn turn-scoping mismatch → error
- [x] 4.8 Test: end_turn partial pass (3/4) → fail
- [x] 4.9 Test: end_turn clears active turn state
- [x] 4.10 Test: backward compat — complete_intento con bouncer funciona
- [x] 4.11 Test: backward compat — complete_intento sin bouncer funciona
- [x] 4.12 Test: flujo completo begin_turn → end_turn = workflow completo
- [x] 4.13 Test: schema version v3
- [x] 4.14 Test: gates_detail column exists
- [x] 4.15 Test: capture_gates_for_intento persists JSON
- [x] 4.16 Test: complete_intento_with_gates updates intento
- [x] 4.17 Test: migración v2→v3

### Fase 5: Verificación ✅
- [x] 5.1 `pytest tests/test_server.py tests/test_persistence.py tests/test_gate_engine.py tests/test_context_extractor.py tests/test_triple_match.py` — **93 passed**
- [x] 5.2 Tests existentes no se rompieron (75 originales + 18 nuevos)
- [x] 5.3 py_compile OK en server.py y persistence.py
