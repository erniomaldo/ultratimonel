# dashboard (new spec)

> **Status:** Active · **Updated:** 23 Jul 2026
> **Change:** v2-architecture
> **Code commit:** 8620b67

## Purpose
A web UI for browsing projects, missions, checklists, intentos, and gate state. Read-only initially; does not modify any data. The dashboard reads from the same SQLite DB that the MCP server writes to.

## Functional Requirements

### F-DB-01 — Hierarchical navigation
The dashboard SHALL expose a hierarchical view: Project → Mission → Checklist → Intento → Gates. The user can click through each level.

### F-DB-02 — Project list
The dashboard SHALL list all projects with `mission_count` and `last_activity` (timestamp of the most recent mission `last_sync`).

### F-DB-03 — Mission list per project
For a given project, the dashboard SHALL list all missions with `checklist_done` / `checklist_total` progress.

### F-DB-04 — Mission detail
For a given mission, the dashboard SHALL show: title, description, status, full checklist with done/pending items.

### F-DB-05 — Intento detail with gate timeline
For a given intento, the dashboard SHALL show: started_at, completed_at, gates_passed/total, and per-gate transition log (timeline).

## Non-Functional Requirements

### NF-DB-01 — Port 3005 by default
The dashboard server SHALL listen on port 3005 by default. Configurable via `ULTRATIMONEL_DASHBOARD_PORT` env var.

### NF-DB-02 — Process isolation
The dashboard SHALL run as a separate process (subprocess of the MCP server, or independently). It SHALL NOT use the MCP stdio transport.

### NF-DB-03 — Read-only
The dashboard SHALL NOT write to SQLite. It MAY read from the same DB file. There is no "edit" or "create" action in the UI.

### NF-DB-04 — No external dependencies
The dashboard backend uses `http.server` from the Python standard library (no FastAPI, no uvicorn, no starlette). The frontend is vanilla JS (no React, Vue, etc.). The NES aesthetic is handcrafted CSS.

## API Endpoints (REST)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/projects` | GET | List projects with counts |
| `/api/projects/{p}/missions` | GET | Missions for a project |
| `/api/missions/{id}` | GET | Mission detail + checklist |
| `/api/checklist/{item_id}/intentos` | GET | Intentos for a checklist item |
| `/api/intentos/{id}` | GET | Intento detail with gates |
| `/api/intentos/{id}/gate/{name}/logs` | GET | Gate transition timeline |

## Files Affected
- `ultratimonel/dashboard_server.py` (new, +462 lines)
- `ultratimonel/dashboard/__init__.py` (new, empty)
- `ultratimonel/dashboard/index.html` (new, +551 lines)
- `ultratimonel/dashboard/app.js` (new, +573 lines)

## Verification
- `curl http://localhost:3005/api/projects` → JSON with 4+ projects
- Browser opens `http://localhost:3005` and shows project list
- Click through to a mission → see checklist items
- Click through to an intento → see gate timeline
