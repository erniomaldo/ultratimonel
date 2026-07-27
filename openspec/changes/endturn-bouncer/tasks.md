# endTurn Bouncer — Tasks

## Fase 2: Implementación (SDD)

### Task 1: Modificar complete_intento() con bouncer
- [x] Agregar parámetros `session_id` y `project` (default "")
- [x] Implementar lógica de validación contra `list_gate_states()`
- [x] Retornar `status: "blocked"` si gates mandatory no pasan
- [x] Fallthrough a `persistence.complete_intento()` si validación pasa

### Task 2: Tests
- [ ] Test: gates PASS/SKIP → completado ok
- [ ] Test: gate BLOCK → blocked
- [ ] Test: múltiples gates fallando → todas listadas
- [ ] Test: optional gate BLOCK → ignorada
- [ ] Test: sin session_id → backward compat
- [ ] Test: sin project → backward compat
- [ ] Test: sin gates en BD → completado ok
- [ ] Test: 75 unit tests existentes siguen pasando

### Task 3: Fix list_gate_states — dedup con MAX(id)
- [x] Corregir query en `persistence.py` para usar `WHERE id IN (SELECT MAX(id) ... GROUP BY gate_name)`
- [x] Verificar que el bouncer ya no encuentra entradas WARN duplicadas
- [x] 75 unit tests pasando

### Task 4: Verificación
- [x] 75 unit tests pasando
- [ ] judgment-day (opencoe)
- [ ] PR + push

## Fase 3: Deploy
- [ ] Revisión manual del PM
- [ ] Aprobación PR
- [ ] Merge a main
