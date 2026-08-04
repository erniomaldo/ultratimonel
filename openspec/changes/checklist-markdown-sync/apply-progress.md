# Apply Progress: checklist-markdown-sync

## Estado: completado ✅

### Task 1.1 — Fix en sync_tasks
- **Estado**: ✅ completado
- **Archivo**: `ultratimonel/server.py` (~L971)
- **Cambio**: Agregado fallback de descripción desde card_detail antes del parseo markdown

### Task 1.2 — Tests unitarios
- **Estado**: ✅ completado
- **Archivo**: `tests/test_server.py`
- **Tests agregados**: 3 (TestSyncTasksMarkdownFallback)
  - test_fallback_uses_card_detail_description ✅
  - test_stacks_description_takes_priority ✅
  - test_neither_has_description_no_crash ✅

### Task 2.1 — Ejecutar suite de tests
- **Estado**: ✅ completado
- **Comando**: `.venv/bin/python -m pytest tests/test_server.py tests/test_persistence.py tests/test_gate_engine.py tests/test_context_extractor.py -q --tb=short`
- **Resultado**: 90 passed (test_triple_match omitido — hace llamadas de red reales, cuelga)
