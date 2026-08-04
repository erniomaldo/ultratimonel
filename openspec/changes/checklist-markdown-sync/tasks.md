# Tasks: checklist-markdown-sync

## 1. Implementación

### 1.1 Fix en sync_tasks (server.py)
- **Descripción**: Agregar fallback de descripción desde card_detail antes del parseo markdown.
- **Ubicación**: `ultratimonel/server.py`, después de la obtención de card_detail (post-L970), antes de L972.
- **Cambio**: Insertar 2 líneas:
  ```python
  if not description and isinstance(card_detail, dict):
      description = card_detail.get("description", "") or ""
  ```

### 1.2 Tests unitarios (tests/test_server.py)
- **Descripción**: Agregar clase `TestSyncTasksMarkdownFallback` con dos tests:
  - `test_fallback_uses_card_detail_description`: mock de call_mcp_tool donde stacks no tiene description pero card_detail sí; verificar checklist_total/checklist_done parseados.
  - `test_stacks_description_takes_priority`: mock donde stacks SÍ tiene description; verificar que se usa la de stacks (regresión).

## 2. Verificación

### 2.1 Ejecutar suite de tests
- **Comando**: `.venv/bin/python -m pytest tests/test_server.py tests/test_persistence.py tests/test_gate_engine.py tests/test_context_extractor.py tests/test_triple_match.py -q --tb=short`
- **Expectativa**: todos los tests pasan, incluyendo los nuevos.
