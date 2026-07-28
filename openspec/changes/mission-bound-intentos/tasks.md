# Mission-Bound Intentos — Tasks

## Fase 1: Protocolo (agente — este turno)
- [x] Crear openspec artifacts (proposal, design ADRs, tasks, spec)
- [x] Actualizar SOUL.md: Paso 4b nuevo + Paso 5 sin fallback mission_id=0

## Fase 2: Tool validation + DB integrity (opencode — server.py + persistence.py)
- [ ] `record_intento()`: rechazar mission_id <= 0 con mensaje de error claro
- [ ] `record_intento()`: rechazar checklist_item_id <= 0
- [ ] `create_intento()` en persistence: validar mismos constraints
- [ ] Activar `PRAGMA foreign_keys = ON` en cada conexión de escritura en persistence.py
- [ ] Agregar FOREIGN KEY para `checklist_item_id → checklist_items(id)` en tabla intentos
- [ ] Test: mission_id=0 → error
- [ ] Test: checklist_item_id=0 → error
- [ ] Test: mission_id=5, item=10 (válido) → ok
- [ ] Test: 75 tests existentes siguen pasando

## Fase 3: Plugin bouncer (PR futuro)
- [ ] pre_tool_call: validar mission_id > 0 en record_intento
- [ ] Verificar misión existe en DB antes de permitir

## Fase 4: Turn-scoped intento lifecycle (plugin, PR #8)
- [ ] `complete_intento()`: validar que intento_id pertenece al turno actual
- [ ] Spec: openspec/changes/mission-bound-intentos/specs/intento-id-enforcement/spec.md
- [ ] Test: complete_intento con intento_id de otro turno → error
- [ ] Test: complete_intento con intento_id del turno actual → ok

## Fase 5: begin_turn / end_turn tools (PR #8)
- [ ] Spec: openspec/changes/mission-bound-intentos/specs/consolidated-intent-flow/spec.md
- [ ] `begin_turn(mission_id)`: create intento with turn scope, return intento_id
- [ ] `end_turn(intento_id)`: complete turno-scoped intento, reject foreign turns
- [ ] server.py: implement both tools with internal gate logic
- [ ] Plugin bouncer: adapt pre_tool_call to validate mission_id in begin_turn (not individual calls)
- [ ] Test: begin_turn con mission_id válido → crea intento, retorna ID
- [ ] Test: end_turn con intento_id del turno actual → completa ok
- [ ] Test: end_turn con intento_id de turno anterior → rechaza con error
- [ ] 75 tests existentes siguen pasando
