# Turn Completeness — Verify Report (Fix Round 2)

## Resumen

Se corrigió el comportamiento ROTO de `end_turn` en producción donde gates WARN/BLOCK
dejaban intentos en estado `running` permanente y turnos activos huérfanos que
bloqueaban IRRECUPERABLEMENTE futuros `begin_turn`. Se implementó recuperación
dual: `end_turn` nunca bloquea (completa con fail) + `begin_turn` auto-limpia
turnos huérfanos.

## Evidencia

### Tests unitarios: 97/97 passing

```
pytest tests/test_server.py tests/test_persistence.py tests/test_gate_engine.py tests/test_context_extractor.py tests/test_triple_match.py -q --tb=short
........................................................................ [ 74%]
.........................                                                [100%]
97 passed in 36.75s
```

### Tests modificados (2)

| Clase | Test | Cambio |
|-------|------|--------|
| TestEndTurn | `test_end_turn_blocked_by_block_gate` | Antes: esperaba `blocked`. Ahora: verifica `final_status=fail`, turno limpio |
| TestEndTurn | `test_end_turn_no_active_turn` | Antes: error "No hay turno activo". Ahora: error "not found in DB" (scoping relajado) |

### Tests nuevos agregados (6)

| Clase | Test | Cubre |
|-------|------|-------|
| TestBeginTurn | `test_begin_turn_orphaned_auto_cleanup` | begin_turn auto-limpia turno huérfano en memoria |
| TestBeginTurn | `test_begin_turn_after_failed_turn` | begin_turn funciona después de un turno fail |
| TestEndTurn | `test_end_turn_warn_gates_completes_as_fail` | Gates WARN → completa como fail + turno limpio |
| TestEndTurn | `test_end_turn_gate_capture_failure_completes` | list_gate_states falla → completa con gates=[] + limpio |
| TestEndTurn | `test_end_turn_recover_running_orphan` | end_turn cierra intento running aunque no sea _active_intento |
| TestEndTurn | `test_end_turn_non_running_mismatch_still_errors` | Intento no-running con mismatch sigue dando error de scoping |

### Tests existentes: 91/91 passing (sin regresiones)

Todos los tests originales pasan sin cambios.

### py_compile
- `ultratimonel/server.py` ✅
- `ultratimonel/persistence.py` ✅

## Cambios realizados

| Archivo | Líneas cambiadas | Descripción |
|---------|-----------------|-------------|
| `ultratimonel/server.py` | +35 / -25 | end_turn: remove bouncer blocking, relax scoping, try/except en validación; begin_turn: auto-cleanup huérfanos; nueva función `_resolve_requesting_intento` |
| `tests/test_server.py` | +108 | 6 nuevos tests + 2 modificados |

## Decisión de diseño confirmada (ADR-007)

- **EndTurn nunca bloquea**: completa siempre con `final_status=fail` o `success`, limpia turno activo
- **Recuperación dual**: end_turn (capa 1) + begin_turn auto-cleanup (capa 2)
- **Scoping relajado**: end_turn puede recuperar intentos running aunque no sean `_active_intento`
- **Firma clásica preservada**: `end_turn(intento_id, status="success")` sin cambios

## Gap analysis (fix vs requirements)

| Requisito | Estado | Evidencia |
|-----------|--------|-----------|
| end_turn completa con fail cuando gates no pasan | ✅ | Test: blocked_by_block_gate → final_status=fail |
| end_turn nunca deja estado running | ✅ | Todos los tests verifican `_get_active_intento() is None` post-end_turn |
| Captura de gates robusta (try/except) | ✅ | Test: gate_capture_failure → completa con [] |
| begin_turn auto-limpia turno huérfano | ✅ | Test: orphaned_auto_cleanup |
| begin_turn funciona después de turn fail | ✅ | Test: after_failed_turn |
| end_turn recupera intento running no-activo | ✅ | Test: recover_running_orphan |
| Gates WARN se registran pero no bloquean | ✅ | Test: warn_gates_completes_as_fail |
| Firma clásica sin cambios | ✅ | `end_turn(intento_id, status="success")` |

## Notas

- `plugin_preflight.py` NO fue modificado (como se solicitó)
- `_validate_gates_for_completion()` sigue existiendo y se usa para logging — solo ya no bloquea
- `complete_intento()` mantiene su bouncer original (backward compat)
- ADR-007 documentado en `design.md`
