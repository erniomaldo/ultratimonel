# project-maps (new spec)

> **Status:** Active · **Updated:** 23 Jul 2026
> **Change:** v2-architecture
> **Code commit:** 8620b67

## Purpose
Externalize project configuration (regex patterns, deck_board_id, collective_id) to a JSON file. Deprecates the hardcoded `KNOWN_PROJECTS` dict that existed in v1.

## Functional Requirements

### F-PM-01 — project_maps.json schema
`project_maps.json` SHALL be a JSON object where:
- Keys are project slugs (e.g., "ultratimonel", "lectura-rapida")
- Values are objects with:
  - `patterns: list[str]` — case-insensitive substrings to match in the message
  - `deck_board_id: int` — Nextcloud Deck board ID
  - `collective_id: int | null` — Nextcloud Collective ID (null if no collective)

### F-PM-02 — Default location
The default path SHALL be `~/.hermes/ultratimonel/project_maps.json`. Overridable via `ULTRATIMONEL_PROJECT_MAPS` env var.

### F-PM-03 — Hot reload
`reload_project_maps()` SHALL re-read the file from disk. `get_project_maps()` returns the cached dict. After `map_add()` or `map_remove()`, the cache SHALL be invalidated.

### F-PM-04 — Graceful degradation
If `project_maps.json` is missing or malformed, `load_project_maps()` SHALL return `{}` and log a warning. The MCP server SHALL continue to function (no project will match, so all gates become SKIP for that case).

### F-PM-05 — Pattern matching
`is_known_project(project_slug)` SHALL return True if `project_slug` is a key in the loaded maps. Used by `assert_gates()` to decide whether to persist or skip.

## Non-Functional Requirements

### NF-PM-01 — Gitignored
`project_maps.json` SHALL be in `.gitignore` because it contains machine-specific Nextcloud IDs.

### NF-PM-02 — Template provided
A `project_maps.json.template` SHALL be committed to the repo as an example.

## API Contract (for the 5 map_* tools)

| Tool | Signature | Behavior |
|------|-----------|----------|
| `map_list()` | `() → {projects: [...]}` | Read from cache |
| `map_add(project, patterns, deck_board_id?, collective_id?)` | `(str, list[str], int?, int?) → {status, project}` | Write + reload cache |
| `map_remove(project)` | `(str) → {removed: bool, reason?}` | Write + reload cache (idempotent) |
| `map_setup()` | `() → {deck_boards, collectives, current_maps}` | Read from Nextcloud + cache |
| `map_sync()` | `() → {verified: [...], stale: [...]}` | Cross-check cache against Nextcloud |

## Files Affected
- `ultratimonel/config_loader.py` (new, +84 lines)
- `ultratimonel/context_extractor.py` (refactored, +89 / -85)
- `ultratimonel/triple_match.py` (uses `get_project_maps()`)
- `project_maps.json.template` (new)
- `~/.hermes/ultratimonel/project_maps.json` (runtime, gitignored)

## Verification
- `mcp__ultratimonel__map_list()` returns 20 projects
- `mcp__ultratimonel__map_add(project="test", patterns=["test"])` succeeds, `map_list()` now includes "test"
- Malformed JSON → server continues, logs warning
