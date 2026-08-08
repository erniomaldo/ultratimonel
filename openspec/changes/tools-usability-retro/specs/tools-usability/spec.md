# Tools Usability — Lightweight Lookups & Project Resolution Fix

> **Capability ID:** `tools-usability` · **Updated:** 07 Aug 2026 · **Change:** Card #147

## Purpose

Provide Hermes with lightweight mission/item lookup tools, an opt-in light mode for `mission_list`, and fix the `begin_turn` project-resolution bug causing `end_turn` gates to validate against "unknown" instead of the explicit project.

## Requirements

### Functional

| ID | Requirement | Priority |
|----|-------------|----------|
| F-TU-01 | The server SHALL expose `mission_get(mission_id)` returning minimal fields: id, title, checklist_item_ids only (no description, no nested items) | MUST |
| F-TU-02 | The server SHALL expose `checklist_item_get(checklist_item_id)` returning a single item by ID or a clear "not found" error | MUST |
| F-TU-03 | `mission_list` SHALL accept optional `include_description`; when `false`, omit `description` and skip nested `checklist_items`. Default is `true` per F-TU-07. | MUST |
| F-TU-04 | `begin_turn` SHALL prefer the explicit `project` parameter over context-extracted project; fall back to `context["project"]` only when the explicit param is empty/unset | MUST |
| F-TU-05 | `mission_get` with a non-existent ID SHALL return `{"error": "Mission <id> not found"}` | MUST |
| F-TU-06 | `checklist_item_get` with a non-existent ID SHALL return `{"error": "Checklist item <id> not found"}` | MUST |
| F-TU-07 | Default behavior of `mission_list` SHALL remain full payload (backward compatible with dashboard consumers); include_description=false is an opt-in for lightweight mode | MUST |

### Non-Functional

| ID | Requirement | Priority |
|----|-------------|----------|
| NF-TU-01 | `mission_get` and `checklist_item_get` SHALL complete in under 5 ms each | MUST |
| NF-TU-02 | `mission_list(project, include_description=false)` SHALL return significantly smaller payloads than full mode | SHOULD |

## Tool Specifications

### `mission_get(mission_id: int)`
Returns `{id, title, checklist_item_ids}` or error if not found. No description, no nested items.

### `checklist_item_get(checklist_item_id: int)`
Returns `{id, mission_id, item_index, text, done}` or error if not found.

### `mission_list(project: str, include_description: bool = True)`
**Full mode (default, backward compatible — F-TU-07):** Current behavior — payload includes `description` and nested `checklist_items` for each mission.
**Light mode (`include_description=false`, opt-in):** `{project, missions: [{id, title, status}], total}` per mission. No description, no nested items.

### `begin_turn` Project Resolution Fix
At server.py:1255, change `resolved_project = context["project"]` to prefer explicit param:
```python
resolved_project = project if project else context["project"]
```

## Scenarios

### S1 — mission_get Happy Path
GIVEN mission id=123 exists with title "Sprint Planning" and items [456, 457]
WHEN `mission_get(mission_id=123)` is called
THEN response is `{id: 123, title: "Sprint Planning", checklist_item_ids: [456, 457]}` — no description or nested items

### S2 — mission_get Not Found
GIVEN no mission id=9999 exists
WHEN `mission_get(mission_id=9999)` is called
THEN response contains error `"Mission 9999 not found"`

### S3 — checklist_item_get Happy Path
GIVEN item id=456 exists (mission_id=123, index=1, text="Review backlog", done=0)
WHEN `checklist_item_get(checklist_item_id=456)` is called
THEN response is `{id: 456, mission_id: 123, item_index: 1, text: "Review backlog", done: 0}`

### S4 — checklist_item_get Not Found
GIVEN no item id=9999 exists
WHEN `checklist_item_get(checklist_item_id=9999)` is called
THEN response contains error `"Checklist item 9999 not found"`

### S5 — mission_list Full Mode (Default, Backward Compatible)
GIVEN project "voy-rojo" has 3 missions with descriptions and nested items in DB
WHEN `mission_list(project="voy-rojo")` is called without `include_description`
THEN response contains all 3 missions with full payload (description + nested checklist_items) — identical to current behavior

### S6 — mission_list Light Mode (Opt-in)
GIVEN project "voy-rojo" has full-data missions in DB
WHEN `mission_list(project="voy-rojo", include_description=false)` is called
THEN response contains all 3 missions, each with only `{id, title, status}` — no description, no checklist_items

### S7 — Regression: begin_turn Prefers Explicit Project
GIVEN Hermes calls `begin_turn(session_id="sess-x", project="voy-rojo", mission_id=5, checklist_item_id=10, message="some context extracting 'unknown'", sender="user")`
AND context extraction would resolve to `"unknown"`
WHEN `begin_turn` executes step 4 (server.py:1255)
THEN `resolved_project` is `"voy-rojo"` (explicit param), NOT `"unknown"`
AND persisted intento has `project="voy-rojo"`

### S8 — Regression: end_turn Gates Against Correct Project
GIVEN `begin_turn(project="voy-rojo", ...)` returned intento_id=70 with project correctly persisted as "voy-rojo"
WHEN `end_turn(intento_id=70)` is called
THEN gate validation runs against `"voy-rojo"` — NOT `"unknown"`

### S9 — Fallback: Empty Project Uses Context
GIVEN Hermes calls `begin_turn(session_id="sess-x", project="", mission_id=5, checklist_item_id=10, message="talk about ultratimonel", sender="user")`
AND context extraction resolves to `"ultratimonel"`
WHEN `begin_turn` executes
THEN `resolved_project` falls back to `"ultratimonel"` (from context) since explicit param is empty
