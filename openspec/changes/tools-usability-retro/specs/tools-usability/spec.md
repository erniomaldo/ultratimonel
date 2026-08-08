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
| F-TU-04 | `begin_turn` SHALL prefer the explicit `project` parameter over the context-extracted project and SHALL execute the gates (`run_triple_match`) against that resolved project; it SHALL fall back to `context["project"]` only when the explicit param is empty/unset | MUST |
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
The explicit `project` parameter wins over context extraction. The resolved project is computed BEFORE running the gates, and `context["project"]` is overwritten so gates 1c/1e execute against the resolved project (not the `"unknown"` fallback from `extract_context`). Regression: intento #234 — message not mentioning any known project + explicit `project="voy-rojo"` → gates 1c/1e silently SKIPped ("No collective/Deck board mapped for project unknown").

```python
# In begin_turn, BEFORE persistence and BEFORE run_triple_match(context):
resolved_project = project if project else context["project"]
context["project"] = resolved_project   # gates EXECUTE against the resolved project
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

### S7 — Regression: begin_turn Prefers Explicit Project (Persistence + Execution)
GIVEN Hermes calls `begin_turn(session_id="sess-x", project="voy-rojo", mission_id=5, checklist_item_id=10, message="some context extracting 'unknown'", sender="user")`
AND context extraction would resolve to `"unknown"`
WHEN `begin_turn` resolves `resolved_project` BEFORE running the gates and overwrites `context["project"]`
THEN `resolved_project` is `"voy-rojo"` (explicit param), NOT `"unknown"`
AND persisted intento has `project="voy-rojo"`
AND `run_triple_match` receives a context whose `project` is `"voy-rojo"`

### S8 — Regression: end_turn Gates Against Correct Project
GIVEN `begin_turn(project="voy-rojo", ...)` returned intento_id=70 with project correctly persisted as "voy-rojo"
WHEN `end_turn(intento_id=70)` is called
THEN gate validation runs against `"voy-rojo"` — NOT `"unknown"`

### S9 — Fallback: Empty Project Uses Context
GIVEN Hermes calls `begin_turn(session_id="sess-x", project="", mission_id=5, checklist_item_id=10, message="talk about ultratimonel", sender="user")`
AND context extraction resolves to `"ultratimonel"`
WHEN `begin_turn` executes
THEN `resolved_project` falls back to `"ultratimonel"` (from context) since explicit param is empty
AND gates execute against `"ultratimonel"` (`context["project"]` overwritten to `"ultratimonel"` before `run_triple_match`)

### S10 — Regression: Gates Execute Against Explicit Project (mensaje neutro + project explícito)
GIVEN Hermes calls `begin_turn(session_id="sess-x", project="voy-rojo", mission_id=5, checklist_item_id=10, message="neutral message not mentioning any project", sender="user")`
AND `extract_context` returns `context["project"]="unknown"`
WHEN `begin_turn` runs the gates via `run_triple_match(context)`
THEN `run_triple_match` receives a context with `project="voy-rojo"` (overwritten from the explicit param)
AND gates 1c/1e execute against the "voy-rojo" project maps (collective_id=6, deck_board_id=7) — NOT SKIP on `"unknown"`
AND `end_turn` validates against the persisted "voy-rojo" project (verified E2E in production, intento #236)
