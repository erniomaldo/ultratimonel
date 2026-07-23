# mission-gate sync tools (delta)

> **Status:** Active · **Updated:** 23 Jul 2026
> **Change:** v2-architecture (delta for tools missed in F-MG-10..14)
> **Code commit:** 8620b67

## Purpose
Documents the 3 Deck-sync MCP tools that exist in `server.py` but were not covered by F-MG-10..14 (which only enumerate the dashboard control + project map tools). These belong to the mission-gate spec because they are part of the 9-new-tools batch and implement the Deck → missions synchronization.

## Functional Requirements

### F-MG-15 — `sync_tasks(project)`
The server SHALL expose a `sync_tasks(project: str)` tool that:
- Looks up the project's `deck_board_id` from `project_maps.json` via `config_loader.get_project_maps()`
- Fetches all stacks and cards from that Deck board via `mcp_nextcloud_deck_get_stacks` + `mcp_nextcloud_deck_get_card`
- For each card, extracts the title, description, and checklist items
- Maps the stack title to a mission status (`backlog`/`pendiente`/`to do` → `pendiente`, `progreso`/`in progress`/`doing` → `en_progreso`, `hecho`/`done`/`completada`/`completado` → `completada`, default `pendiente`)
- Upserts into `missions` table (idempotent via `deck_task_id` UNIQUE constraint)
- Upserts into `checklist_items` table for each card's checklist (from Deck's `checklistItems` field or markdown checkboxes fallback)
- Returns JSON `{project, board_id, synced: int, errors: [str], total_errors: int}`

### F-MG-16 — `sync_all()`
The server SHALL expose a `sync_all()` tool that:
- Iterates all projects in `project_maps.json` that have a `deck_board_id` configured
- Calls `sync_tasks(project)` for each
- Aggregates results: `{status, projects_synced, total_synced, total_errors, details: {project: {status, synced, errors}}}`

### F-MG-17 — `mission_list(project)`
The server SHALL expose a `mission_list(project: str)` tool that:
- Lists all missions in the `missions` table for the given project
- Each mission MUST include its `checklist_items: [...]` enriched via `list_checklist_items(mission_id)`
- Returns JSON `{project, missions: [...], total: int}`

## Scenarios (Given/When/Then)

### S-MG-15 — sync_tasks creates mission from Deck card
**GIVEN** project "lectura-rapida" has `deck_board_id: 10` and the board has 9 cards
**WHEN** `sync_tasks(project="lectura-rapida")` is called
**THEN** 9 rows SHALL be upserted into `missions` with `project="lectura-rapida"`
**AND** the response SHALL include `synced: 9, total_errors: 0`

### S-MG-16 — sync_all skips projects without deck_board_id
**GIVEN** project "ultratimonel" has `deck_board_id: null`
**WHEN** `sync_all()` is called
**THEN** "ultratimonel" SHALL be skipped (not in details)
**AND** projects with `deck_board_id` set SHALL appear in details

### S-MG-17 — mission_list includes checklist_items
**GIVEN** a mission has 3 checklist items (2 done, 1 pending)
**WHEN** `mission_list(project)` is called for the project's slug
**THEN** the returned mission object SHALL have `checklist_items: [{index, text, done}, ...]` with 3 entries
**AND** 2 of them SHALL have `done: 1` and 1 SHALL have `done: 0`

## Non-Functional Requirements

### NF-MG-05 — sync_tasks is idempotent
Calling `sync_tasks(project)` multiple times with no Deck changes SHALL not create duplicate missions. The `UNIQUE(deck_task_id)` constraint guarantees this. Calling it after a Deck edit SHALL update the existing row (title, description, status, checklist counts) without changing the `id`.

### NF-MG-06 — sync_all returns within 120 seconds for 20 projects
Observed: 20 projects sync in 74.5s. The 300s `HTTP_TIMEOUT` (per NF-TM-03) gives 4x headroom. If a sync cycle exceeds 120s, investigate per-project slowness rather than raising the global timeout.

## Files Affected
- `ultratimonel/server.py` — registers `sync_tasks`, `sync_all`, `mission_list` (lines ~620, ~880, ~930)

## Verification
- `mcp__ultratimonel__sync_all()` → 20 projects, 111 missions, 0 errors (74.5s)
- `mcp__ultratimonel__mission_list(project="ultratimonel")` → 16 missions with checklist_items populated
- `mcp__ultratimonel__sync_tasks(project="voy-rojo")` → 27 missions synced
