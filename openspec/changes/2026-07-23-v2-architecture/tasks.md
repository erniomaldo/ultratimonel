# Task Breakdown: Ultratimonel v2 Architecture

> **Estado:** Todas las tasks marcadas `[x]` — implementación completa en commit `8620b67`.
> **Este change** documenta las tasks post-facto; no las ejecuta.
> **Próximo paso del PAC:** `sdd-verify` + `judgment-day` (Fase 2 — no incluido aquí).

---

## Phase 1 — Schema v2 Persistence

### 1.1 Migration v1 → v2
- [x] `_is_v1_style_missions_table()` en `persistence.py` — detecta schema preexistente
- [x] `_migrate_v1_to_v2()` — copia datos de `missions` v1 a v2, renombra tablas
- [x] DDL v2: `missions` (con `deck_task_id` como natural key), `checklist_items`, `intentos`
- [x] `actions` legacy preservada para retrocompatibilidad
- **Verify:** migración probada en DB de producción (20 proyectos, 111 misiones, 0 errores)

### 1.2 New persistence methods
- [x] `upsert_mission(deck_task_id, project, title, ...)` — idempotente via UNIQUE(deck_task_id)
- [x] `get_mission(mission_id)`
- [x] `list_missions(project)` — enriquece con `list_checklist_items()`
- [x] `upsert_checklist_item(mission_id, item_index, text, done)`
- [x] `list_checklist_items(mission_id)`
- [x] `create_intento(checklist_item_id)` / `complete_intento(intento_id, ...)`
- [x] `get_intento_with_gates(intento_id)`
- [x] `count_missions_by_project(project)` / `get_mission_counts_by_project()`
- **Verify:** tests en `tests/test_persistence.py` (5 tests `TestMissions` + `test_list_missions_for_project`)

### 1.3 Concurrency fix
- [x] `threading.Lock()` → `threading.RLock()` en `persistence.py` `__init__`
- [x] Comentario explicativo del por qué (composicición de métodos)
- **Verify:** test `test_list_missions_for_project` reproduce el escenario del deadlock

---

## Phase 2 — Gate 1c (Collectives) Integration

### 2.1 Triple match update
- [x] `_call_collective(context)` en `triple_match.py` — busca collective_id via `get_project_maps()`
- [x] SKIP graceful si proyecto no tiene collective mapeado
- [x] Filtro por `STEERING_DOC_TITLES` (visión, decisions, arquitectura, roadmap, página de inicio)
- [x] Secuencia actualizada: 1a → 1b → 1c → 1e
- **Verify:** `mcp__ultratimonel__assert_gates()` muestra 4 gates, 1c SKIP para ultratimonel (no collective)

### 2.2 Context envelope
- [x] Campo `steering_docs: []` agregado al envelope
- [x] Tests actualizados en `tests/test_triple_match.py`
- **Verify:** 16/16 tests `TestTripleMatch` pasan

---

## Phase 3 — 6 New MCP Tools

### 3.1 Deck sync tools
- [x] `sync_tasks(project)` — Deck → missions + checklist_items
- [x] `sync_all()` — itera todos los proyectos con `deck_board_id`
- [x] `mission_list(project)` — lista con checklist_items enriquecidos
- [x] Status mapping: backlog→pendiente, progreso→en_progreso, hecho→completada
- [x] Fallback a parsing de checkboxes markdown si Deck no devuelve `checklistItems`
- **Verify:** `mcp__ultratimonel__sync_all()` → 20 proyectos, 111 misiones, 0 errores (74.5s)

### 3.2 Project map tools
- [x] `map_list()` — lista todos los proyectos configurados
- [x] `map_add(project, patterns, deck_board_id?, collective_id?)` — alta/edición
- [x] `map_remove(project)` — baja
- [x] `map_setup()` — descubre boards/collectives disponibles
- [x] `map_sync()` — verifica que los boards mapeados aún existen
- **Verify:** `map_setup()` muestra 20 boards y 20 collectives conocidos, 0 unmapped (ya en producción)

### 3.3 Dashboard server tool
- [x] `server(action="start"|"status"|"restart"|"stop")` — controla el dashboard
- [x] Tracking de PID, port, URL
- **Verify:** `server(action="status")` → `{"running": true, "port": 3005, "pid": 51944, "url": "http://localhost:3005"}`

---

## Phase 4 — Dashboard Web UI

### 4.1 Backend (http.server stdlib)
- [x] `dashboard_server.py` — `http.server.HTTPServer` + `SimpleHTTPRequestHandler`, puerto 3005, cero dependencias externas
- [x] Endpoints REST: `/api/projects`, `/api/projects/{p}/missions`, etc.
- [x] Carga `project_maps.json` via `config_loader`
- **Verify:** `curl http://localhost:3005/api/projects` → JSON con 4+ proyectos

### 4.2 Frontend
- [x] `dashboard/index.html` — UI estática estilo NES
- [x] `dashboard/app.js` — fetch + render, sin framework
- [x] Headers anti-caché para evitar servir versión vieja
- **Verify:** Dashboard abre en navegador con proyectos listados

---

## Phase 5 — Config Externalization

### 5.1 config_loader.py
- [x] Carga `project_maps.json` (path via env o default)
- [x] `load_project_maps() → dict`
- [x] `reload_project_maps()` — recarga desde disco (sin cache)
- [x] Manejo de JSON malformado: devuelve `{}` + logging
- **Verify:** tests en `tests/test_config_loader.py` (pendiente; warning del verify anterior)

### 5.2 context_extractor.py update
- [x] Deprecación de `KNOWN_PROJECTS` hardcodeado
- [x] Carga proyectos via `config_loader.load_project_maps()`
- [x] `is_known_project(project)` helper
- [x] `get_project_maps()` helper
- **Verify:** 11/11 tests `TestExtractContext` pasan con proyectos reales

### 5.3 project_maps.json.template
- [x] Template de ejemplo para que el usuario sepa la estructura
- **Verify:** archivo presente en repo

---

## Phase 6 — Timeout + HTTP

### 6.1 HTTP_TIMEOUT
- [x] `triple_match.py`: `HTTP_TIMEOUT = 40.0` → `300.0`
- [x] Comentario documentando la decisión (300s = headroom para 50+ proyectos)
- [x] Override via `ULTRATIMONEL_TIMEOUT` env
- **Verify:** 20 proyectos sincronizan en 74.5s (bien debajo del timeout)

### 6.2 mcp_client.py minor
- [x] `deck_get_card` agregado a `TOOL_NAMES["nextcloud"]`
- **Verify:** `sync_tasks()` ahora puede llamar `deck_get_card` para detalles

---

## Phase 7 — Test Suite Update

### 7.1 test_persistence.py — TestMissions
- [x] Reescritura de 4 tests legacy a firma v2
- [x] Nuevo test `test_list_missions_for_project` que reproduce el deadlock
- [x] 5/5 tests pasan
- **Verify:** `pytest tests/test_persistence.py` → 20/20 PASS

### 7.2 test_context_extractor.py
- [x] `test_known_project_nocturno` y `test_known_project_messagens` reemplazados
- [x] Nuevos tests con `lectura-rapida` y `voy-rojo` (proyectos reales)
- [x] 11/11 tests pasan
- **Verify:** `pytest tests/test_context_extractor.py` → 11/11 PASS

---

## Phase 8 — Documentation Sync

### 8.1 openspec/specs/*
- [x] `mission-gate/spec.md` sincronizado (4 gates, 12 tools)
- [x] `triple-match/spec.md` sincronizado (1a→1b→1c→1e)
- [x] `gate-persistence/spec.md` sincronizado (schema v2)
- [x] `soul-enforce/spec.md` sincronizado (fecha)
- **Verify:** fecha de los archivos = 23 jul 2026

### 8.2 docs/
- [x] `README.md` actualizado (menciona 12 tools)
- [x] `docs/01-plan-general.md` — gate 1c mencionado
- [x] `docs/02-triple-match.md` — 4 gates, no 3
- [x] `docs/05-preflight-flow.md` — diagrama con 1c incluido
- **Verify:** grep "1c\|Collectives" en docs/* → presente

### 8.3 Cambio pendiente (fuera de scope)
- [ ] Nextcloud Collective 17 (Inicio, Arquitectura, Decisiones) — actualmente dice "3 tools", debería decir "12 tools"
- [ ] ADR D-008 (RLock), D-009 (12 tools), D-010 (puerto 3005 vs 9999) en la página Decisiones
- [ ] Roadmap Fase 1.1 marcar como "completada" y 2.1 también

---

## Resumen

| Phase | Tasks | Status |
|-------|-------|--------|
| 1 — Schema v2 | 12 | ✅ |
| 2 — Gate 1c | 5 | ✅ |
| 3 — 6 New tools | 12 | ✅ |
| 4 — Dashboard | 6 | ✅ |
| 5 — Config | 8 | ✅ |
| 6 — HTTP/timeout | 4 | ✅ |
| 7 — Tests | 8 | ✅ |
| 8 — Docs | 7 | ✅ |
| **TOTAL** | **62** | **59 ✅, 3 ⏳ (fuera de scope)** |
