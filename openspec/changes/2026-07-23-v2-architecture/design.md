# SDD: Ultratimonel v2 — Architecture, 12 MCP Tools, Schema v2, Dashboard

## 1. Architecture Overview

```
┌───────────────────────────────────────────────────────────────┐
│                  AGENT (Hermes / AnythingLLM / Codex)         │
└────────────────────────┬──────────────────────────────────────┘
                         │ MCP stdio
                         ▼
┌───────────────────────────────────────────────────────────────┐
│              ULTRATIMONEL v2 (FastMCP)                        │
│                                                               │
│   12 MCP tools:                                               │
│   ─ Core gates (3):                                           │
│     • assert_gates(message, session_id, sender)               │
│     • check_gate(name, session_id)                            │
│     • complete_gate(name, session_id, reason)                 │
│   ─ Sync Deck (3):  ← F-MG-15..17                             │
│     • sync_tasks(project) → missions table                    │
│     • sync_all() → all projects with deck_board_id            │
│     • mission_list(project) → missions + checklist_items      │
│   ─ Project maps (5):  ← F-MG-11..14                          │
│     • map_list(), map_add(...), map_remove(project)           │
│     • map_setup() → discover boards/collectives               │
│     • map_sync() → verify mapped boards still exist           │
│   ─ Dashboard (1):  ← F-MG-10                                 │
│     • server(action=start|status|restart|stop)                │
│                                                               │
│   ┌─────────────────────────────────────────────────────┐    │
│   │ Triple match coordinator: 1a → 1b → 1c → 1e          │    │
│   │  1a: AgentMemory.smart_search (MCP stdio)            │    │
│   │  1b: Checkpoint.get_state  (MCP stdio)               │    │
│   │  1c: Collectives.get_pages (MCP stdio)              │    │
│   │  1e: Deck.get_stacks      (MCP stdio)               │    │
│   └─────────────────────────────────────────────────────┘    │
│                                                               │
│   ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│   │ config_     │  │ persistence  │  │ dashboard_       │   │
│   │ loader.py   │  │   .py        │  │ server.py        │   │
│   │ (JSON ext)  │  │ (SQLite v2)  │  │ (http.server:3005)│   │
│   └─────────────┘  └──────────────┘  └──────────────────┘   │
└────────────────────────┬──────────────────────────────────────┘
                         │ MCP stdio (persistent subprocesses)
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
  ┌──────────┐     ┌──────────┐     ┌──────────┐
  │AgentMemory│    │Checkpoint│     │Nextcloud │
  │           │    │          │     │          │
  └──────────┘    └──────────┘     └─┬────────┘
                                     │
                          ┌──────────┼──────────┐
                          ▼          ▼          ▼
                    ┌────────┐ ┌────────┐ ┌────────┐
                    │Collect.│ │  Deck  │ │  Talk  │
                    └────────┘ └────────┘ └────────┘
```

**Cambios vs v1 (MVP):**
- +9 tools (sync_tasks, sync_all, mission_list, server, map_list, map_add, map_remove, map_setup, map_sync)
- +1 gate (1c — Collectives)
- +2 capas: config_loader.py (externaliza config) y dashboard_server.py (UI web)
- Persistencia migrada de schema v1 a v2 (con migración transparente)

## 2. MCP Tool Signatures (JSON Schema)

### `assert_gates(message, session_id, sender=None)`
**Input:** `{message: str, session_id: str, sender?: str}`  
**Response:**
```json
{
  "gates": [
    {"name": "1a", "state": "PASS", "message": "5 memories", "result_data": {...}},
    {"name": "1b", "state": "PASS", "message": "checkpoint found", "result_data": {...}},
    {"name": "1c", "state": "SKIP", "message": "No collective mapped", "result_data": {...}},
    {"name": "1e", "state": "PASS", "message": "16 cards on board 21", "result_data": {...}}
  ],
  "status": "PASS",
  "context": {"sender": "user", "topic": "...", "project": "ultratimonel", "session_id": "..."},
  "context_envelope": {
    "memory_snippets": [...],
    "checkpoint_state": {...},
    "steering_docs": [],
    "deck_cards": [...],
    "relevant_tools": [...]
  },
  "timestamp": "2026-07-23T..."
}
```

### `check_gate(name, session_id)` / `complete_gate(name, session_id, reason)`
Sin cambios vs v1.

### `sync_tasks(project)` (NUEVA)
**Input:** `{project: str}`  
**Response:** `{project, board_id, synced: int, errors: [str], total_errors: int}`
Lee Deck del board mapeado a `project`, upserta en `missions` + `checklist_items`.

### `sync_all()` (NUEVA)
**Response:** `{status, projects_synced, total_synced, total_errors, details: {project: {status, synced, errors}}}`
Sincroniza todos los proyectos con `deck_board_id` mapeado.

### `mission_list(project)` (NUEVA)
**Response:** `{project, missions: [...], total}`
Cada mission incluye `checklist_items: [...]` (enriquecido via `list_checklist_items`).

### `server(action)` (NUEVA)
**Input:** `{action: "start"|"status"|"restart"|"stop"}`  
**Response:** `{action, running, port, pid, url, script}` (start devuelve la URL completa)

### `map_list() / map_add() / map_remove() / map_setup() / map_sync()` (NUEVAS)
Gestión de `project_maps.json` vía MCP (alternativa a editar el archivo directamente).

## 3. SQLite Schema (v2)

```sql
-- Heredado de v1 (sin cambios):
CREATE TABLE sessions (...)        -- contexto por session_id
CREATE TABLE gate_state (...)      -- estado por gate por session+project
CREATE TABLE gate_logs (...)       -- auditoría de transiciones
CREATE TABLE checkpoints (...)     -- snapshots de triple-match
CREATE TABLE schema_version (...)  -- migraciones

-- v1 missions deprecada — reemplazada por v2:
-- (migración automática: ALTER TABLE missions ADD COLUMN deck_task_id INTEGER)

-- NUEVAS en v2:
CREATE TABLE missions (
  id INTEGER PRIMARY KEY,
  deck_task_id INTEGER NOT NULL,  -- natural key (FK a Deck card)
  project TEXT NOT NULL,
  title TEXT NOT NULL,
  description TEXT DEFAULT '',
  status TEXT DEFAULT 'pendiente', -- pendiente | en_progreso | completada
  checklist_total INTEGER DEFAULT 0,
  checklist_done INTEGER DEFAULT 0,
  last_sync TEXT DEFAULT CURRENT_TIMESTAMP,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(deck_task_id)            -- idempotencia de sync
);

CREATE TABLE checklist_items (
  id INTEGER PRIMARY KEY,
  mission_id INTEGER NOT NULL REFERENCES missions(id) ON DELETE CASCADE,
  item_index INTEGER NOT NULL,
  text TEXT NOT NULL,
  done INTEGER DEFAULT 0,
  UNIQUE(mission_id, item_index)
);

CREATE TABLE intentos (
  id INTEGER PRIMARY KEY,
  checklist_item_id INTEGER NOT NULL REFERENCES checklist_items(id) ON DELETE CASCADE,
  started_at TEXT DEFAULT CURRENT_TIMESTAMP,
  completed_at TEXT,
  gates_passed INTEGER DEFAULT 0,
  gates_total INTEGER DEFAULT 4
);

-- actions se mantiene para retrocompatibilidad (v1 → v2):
-- upsert_action() legacy apunta a missions via session_id
```

**Migración v1 → v2** (en `persistence.py`):
1. Detectar schema v1 con `_is_v1_style_missions_table()` (chequea si `missions` tiene columna `session_id`)
2. Si v1: crear tabla `missions_v2` con schema nuevo, copiar datos, renombrar
3. Aplicar DDL v2 (CREATE TABLE checklist_items, intentos)

## 4. Concurrency Model — RLock Fix

**Problema (pre-fix):** `threading.Lock()` no es reentrante.

```python
def list_missions(self, project):
    with self._lock:                          # outer acquires lock
        with self._conn() as conn:
            rows = conn.execute(...)
            for r in rows:
                d["checklist_items"] = self.list_checklist_items(d["id"])  # ← nested call
                #                                                                              │
                def list_checklist_items(self, mission_id):                                    
                #     with self._lock:           # ← DEADLOCK: same thread, same lock          
                #                                                                              │

```

**Fix:**
```python
self._lock = threading.RLock()  # reentrant — same thread can acquire multiple times
```

**Por qué RLock y no refactor de queries:** La composición de métodos es legítima (`list_missions` enriquece con `list_checklist_items`). Refactorizar para usar una sola conexión complicaría el código sin beneficio. RLock es la solución idiomática en Python para este patrón.

## 5. Config Externalization

`config_loader.py` carga `project_maps.json` (path via env `ULTRATIMONEL_PROJECT_MAPS`, default `~/.hermes/ultratimonel/project_maps.json`).

```json
{
  "ultratimonel": {
    "patterns": ["ultratimonel"],
    "deck_board_id": 21,
    "collective_id": null
  },
  "lectura-rapida": {
    "patterns": ["lectura rapida", "lectura"],
    "deck_board_id": 10,
    "collective_id": 1
  }
  // ... 18 proyectos más
}
```

`context_extractor.py` ya no tiene `KNOWN_PROJECTS` hardcodeado. `triple_match.py` llama a `reload_project_maps()` cuando necesita refrescar (e.g., después de `map_add`).

## 6. Dashboard — API REST

Puerto 3005 (env `ULTRATIMONEL_DASHBOARD_PORT`).

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/projects` | GET | Lista proyectos con `mission_count` |
| `/api/projects/{p}/missions` | GET | Misiones de un proyecto (con `checklist_items`) |
| `/api/missions/{id}` | GET | Detalle de mission |
| `/api/checklist/{item_id}/intentos` | GET | Intentos de un checklist item |
| `/api/intentos/{id}` | GET | Detalle de intento + gates |
| `/api/intentos/{id}/gate/{name}/logs` | GET | Timeline de transiciones de un gate |

Frontend en `dashboard/app.js` + `dashboard/index.html` (vanilla JS, sin framework, estilo NES).

## 7. Dependencies

- `fastmcp` (ya)
- `httpx` (ya)
- `http.server` (stdlib) — dashboard usa `HTTPServer` + `SimpleHTTPRequestHandler` + `socketserver`. Cero dependencias externas para el dashboard.
- **No nuevas** dependencias

## 8. Affected Files (delta vs commit anterior)

| Archivo | Tipo | Líneas |
|---------|------|--------|
| `ultratimonel/persistence.py` | refactor + RLock + 4 métodos nuevos | +509 / -36 |
| `ultratimonel/server.py` | 9 nuevos tools | +666 / -28 |
| `ultratimonel/context_extractor.py` | externalización | +89 / -85 |
| `ultratimonel/triple_match.py` | gate 1c + timeout | +27 / -7 |
| `ultratimonel/config_loader.py` | nuevo | +84 |
| `ultratimonel/dashboard_server.py` | nuevo | +462 |
| `ultratimonel/dashboard/app.js` | nuevo | +573 |
| `ultratimonel/dashboard/index.html` | nuevo | +551 |
| `tests/test_persistence.py` | v2 fixtures | +49 / -15 |
| `tests/test_context_extractor.py` | proyectos reales | +19 / -9 |
| `README.md` + `docs/*` | sync | +73 |
| **TOTAL** | | **+3,384 / -397** |

## 9. PAC Compliance Status

| PAC Rule | Status |
|----------|--------|
| "Artefactos completos = PRD aprobado" | ✅ Este change completa proposal + design + tasks + specs |
| "feature_{id}_{nombre}" branch | ✅ Rama `feature_v2-architecture` creada |
| "Validación Obligatoria: Nunca saltar `judgment-day`" | ⏳ Pendiente (Fase 2 del PAC) |
| "Triple Persistencia" en cada paso | ✅ Checkpoint + AgentMemory + Deck card |
| "Si el alcance cambia, actualizar la propuesta. Si es un intento diferente, crear nueva card" | ✅ Una sola card (#126) para todo el change |
| "Toda card DEBE tener `#{id}`" | ✅ Título "#126 SDD v2-architecture..." |
