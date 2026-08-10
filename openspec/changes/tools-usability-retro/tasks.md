# Tasks: Tools Usability Retro (Card #147)

> **Change:** `tools-usability-retro` · **Date:** 2026-08-07
> **Inputs:** [proposal.md](./proposal.md) · [spec.md](./specs/tools-usability/spec.md) · [design.md](./design.md)
> **Branch:** `feature_147_tools-usability-retro` (working branch — no checkout needed)

---

## Review Workload Forecast

| Task | Files changed | Est. lines | Risk |
|------|--------------|------------|------|
| T1 — Persistence: `get_checklist_item_by_id` | 2 | ~30 | Low |
| T2 — `mission_list` light mode (`include_description`) | 1 | ~25 | Low |
| T3 — Tool: `mission_get` | 1 | ~25 | Low |
| T4 — Tool: `checklist_item_get` | 1 | ~22 | Low |
| T5 — Fix project in `begin_turn` + regression tests | 1 | ~70 | Medium |
| T6 — Integration tests | 1 | ~45 | Low |
| **Total** | **5 files** | **~217 lines** | — |

**Forecast: ~217 changed lines.** Under 400-line review budget. No chained PRs needed.

---

## Dependency Graph

```
T1 (persistence) ──► T3 (mission_get uses persistence.get_mission + list_checklist_items)
     │                                              ▲
     └──────────────────────────────────────────────┘
     (checklist_item_get in T4 also depends on get_checklist_item_by_id from T1)

T2 (mission_list light mode) — independent, can run parallel to T1
T3, T4 — independent of each other, both depend on T1
T5 (begin_turn fix) — independent of T1-T4
T6 (integration tests) — depends on T1+T2+T3+T4+T5
```

**Recommended sequential order:** T1 → T2/T3/T4 (parallel-safe) → T5 → T6

---

## Tasks

### T1 — Persistence: `get_checklist_item_by_id()`

**Files:** `ultratimonel/persistence.py`, `tests/test_persistence.py`

**What:** Add `get_checklist_item_by_id(checklist_item_id: int) -> Optional[dict]` to the persistence layer. Follow existing PK-query pattern (`get_session`, `get_intento`). Select explicit columns only (`id, mission_id, item_index, text, done`). Place immediately after `list_checklist_items` (line 795), inside the same `# ── checklist_items ──` block.

**How:**
1. In `persistence.py`, after line 795 (`return [dict(r) for r in rows]`), add:
   ```python
   def get_checklist_item_by_id(self, checklist_item_id: int) -> Optional[dict]:
       """Retrieve a single checklist item by its primary key."""
       with self._lock:
           with self._conn() as conn:
               row = conn.execute(
                   "SELECT id, mission_id, item_index, text, done"
                   " FROM checklist_items WHERE id = ?",
                   (checklist_item_id,),
               ).fetchone()
               return dict(row) if row else None
   ```
2. In `tests/test_persistence.py`, add class `TestChecklistItemById` with 2 tests:
   - `test_get_checklist_item_by_id`: upsert mission + item, query by ID, assert all fields match
   - `test_get_checklist_item_by_id_not_found`: query non-existent ID, assert returns `None`

**Done when:**
- [ ] `get_checklist_item_by_id` exists in persistence.py with explicit column SELECT
- [ ] Both tests pass (`python -m pytest tests/test_persistence.py::TestChecklistItemById -v`)
- [ ] No existing tests broken

---

### T2 — `mission_list`: add `include_description` light mode (F-TU-03, F-TU-07)

**Files:** `ultratimonel/server.py`, `tests/test_server.py`

**What:** Add optional `include_description: bool = True` parameter to `mission_list`. Default `True` preserves full payload for dashboard backward compatibility (F-TU-07). When `False`, strip each mission to `{id, title, status}` and omit `checklist_items` from response.

**How:**
1. In `server.py` line 1152, change signature:
   ```python
   def mission_list(project: str, include_description: bool = True) -> str:
   ```
2. After `missions = persistence.list_missions(project)` (line 1162), add branching logic per ADR-2 design.md lines 85-104.
3. In `tests/test_server.py`, add class `TestMissionListLightMode` with 2 tests:
   - `test_default_returns_full_payload_backward_compatible`: call without param, assert description and checklist_items present
   - `test_include_description_false_returns_light_mode`: call with `include_description=False`, assert only `{id, title, status}`

**Done when:**
- [ ] Default call returns identical payload to current behavior (backward compatible)
- [ ] `include_description=False` returns lightweight payload without description/checklist_items
- [ ] Both tests pass (`python -m pytest tests/test_server.py::TestMissionListLightMode -v`)
- [ ] All existing `TestBeginTurn` and `TestMissions` tests still pass

---

### T3 — Tool: `mission_get(mission_id)` (F-TU-01, F-TU-05)

**Files:** `ultratimonel/server.py`, `tests/test_server.py`

**What:** Add new MCP tool `mission_get(mission_id: int)` that returns minimal fields `{id, title, checklist_item_ids}`. Reuses existing `persistence.get_mission()` (line 702) and `persistence.list_checklist_items()`. Place after `mission_list` (~line 1172), before `begin_turn`.

**How:**
1. In `server.py`, after the `mission_list` function (after line 1171), add:
   ```python
   @app.tool()
   def mission_get(mission_id: int) -> str:
       """Retrieve a single mission by ID with minimal fields."""
       mission = persistence.get_mission(mission_id)
       if not mission:
           return json.dumps({"error": f"Mission {mission_id} not found"})
       item_ids = [ci["id"] for ci in persistence.list_checklist_items(mission["id"])]
       return json.dumps({
           "id": mission["id"],
           "title": mission["title"],
           "checklist_item_ids": item_ids,
       }, ensure_ascii=False, default=str)
   ```
2. In `tests/test_server.py`, add class `TestMissionGet` with 2 tests (mocking `persistence.get_mission` and `persistence.list_checklist_items`):
   - `test_mission_get_returns_minimal_fields`: assert response has id/title/checklist_item_ids only, no description
   - `test_mission_get_not_found`: assert error message contains the ID

**Done when:**
- [ ] Tool registered with MCP (`@app.tool()` decorator present)
- [ ] Returns minimal fields only (no description, no nested items)
- [ ] Not-found returns `{"error": "Mission <id> not found"}`
- [ ] Both tests pass + all existing server tests still pass

---

### T4 — Tool: `checklist_item_get(checklist_item_id)` (F-TU-02, F-TU-06)

**Files:** `ultratimonel/server.py`, `tests/test_server.py`

**What:** Add new MCP tool `checklist_item_get(checklist_item_id: int)` that returns the full item record `{id, mission_id, item_index, text, done}` or a not-found error. Uses `persistence.get_checklist_item_by_id()` from T1. Place after `mission_get` (~line ~1185).

**How:**
1. In `server.py`, after `mission_get` (after line ~1185), add:
   ```python
   @app.tool()
   def checklist_item_get(checklist_item_id: int) -> str:
       """Retrieve a single checklist item by ID."""
       item = persistence.get_checklist_item_by_id(checklist_item_id)
       if not item:
           return json.dumps({"error": f"Checklist item {checklist_item_id} not found"})
       return json.dumps(item, ensure_ascii=False, default=str)
   ```
2. In `tests/test_server.py`, add class `TestChecklistItemGet` with 2 tests (mocking `persistence.get_checklist_item_by_id`):
   - `test_checklist_item_get_returns_item`: assert all fields match
   - `test_checklist_item_get_not_found`: assert error message contains the ID

**Done when:**
- [ ] Tool registered with MCP decorator
- [ ] Returns full item record on found
- [ ] Not-found returns `{"error": "Checklist item <id> not found"}`
- [ ] Both tests pass + all existing server tests still pass

---

### T5 — Fix project resolution in `begin_turn` + regression tests (F-TU-04, S7-S10)

**Files:** `ultratimonel/server.py`, `tests/test_server.py`

**What:** Fix project resolution in `begin_turn` so the explicit `project` parameter wins over context extraction AND the gates EXECUTE against the resolved project (not the `"unknown"` fallback from `extract_context`). Add 5 regression tests covering persistence (S7, S8, S9) and gate execution (S9-ejecución, S10). Regression: intento #234 — 1c/1e SKIP silencioso por "unknown".

**How:**
1. In `begin_turn` (server.py), resolve the project BEFORE running the gates and overwrite `context["project"]` so `run_triple_match` executes against the resolved project:
   ```python
   resolved_project = project if project else context["project"]
   context["project"] = resolved_project   # gates 1c/1e execute against the resolved project
   ```
2. In `tests/test_server.py`, class `TestBeginTurnProjectFix` with 5 tests:
   - `test_explicit_project_wins_over_context`: mock extract→"unknown", pass project="voy-rojo", assert create_intento and upsert_gate_state called with "voy-rojo"
   - `test_empty_project_falls_back_to_context`: pass project="", context resolves to "ultratimonel", assert fallback works
   - `test_end_turn_validates_against_persisted_project`: simulate begin_turn persisting project="voy-rojo", call end_turn, assert gates validated against correct project
   - `test_gates_execute_against_explicit_project`: extract→"unknown", project="voy-rojo", assert `run_triple_match` received `context["project"] == "voy-rojo"` (S10 — gates execute against explicit project)
   - `test_gates_execute_with_fallback_to_context`: project="", extract→"ultratimonel", assert `run_triple_match` received `context["project"] == "ultratimonel"` (fallback at execution)

**Done when:**
- [ ] `resolved_project` computed BEFORE `run_triple_match` and `context["project"]` overwritten with it
- [ ] S7 test: explicit param wins over "unknown" context extraction (persistence)
- [ ] S8 test: end_turn gates run against persisted project, not "unknown"
- [ ] S9 test: empty string falls back to context extraction (persistence + execution)
- [ ] S10 test: `run_triple_match` receives `context["project"]` with the explicit project when extraction returns "unknown"
- [ ] Verified E2E in production: intento #236 — mensaje neutro + project='voy-rojo' → 1b checkpoint 'voy-rojo', 1c collective 6, 1e board 7 (no SKIP por "unknown")
- [ ] All existing `TestBeginTurn` tests still pass (especially `test_begin_turn_executes_fresh_gates`)
- [ ] No regression in any other server test

---

### T6 — Integration tests for new tools and project fix

**Files:** `tests/test_integration.py`

**What:** Add end-to-end integration tests that call the real MCP tools (via the test client) against a live SQLite DB. Covers: mission_get minimal fields, mission_list light mode, and begin_turn→end_turn project persistence.

**How:**
1. In `tests/test_integration.py`, add 3 test functions following the existing integration test patterns in the file:
   - `test_mission_get_returns_minimal_fields`: seed DB with mission+items, call via MCP client, assert response shape
   - `test_mission_list_light_mode_omits_description`: seed DB, call `mission_list(project, include_description=False)`, assert no description/checklist_items in response
   - `test_begin_turn_persists_explicit_project`: call `begin_turn(project="voy-rojo", ...)` with message that would extract "unknown", then `end_turn(intento_id)`, assert gates validated against "voy-rojo"

**Done when:**
- [ ] All 3 integration tests pass (`python -m pytest tests/test_integration.py -v -k "mission_get or light_mode or begins_turn_persists"`)
- [ ] Full test suite passes: `python -m pytest tests/ -v`

---

## Execution Order

| Step | Task | Depends on | Estimated effort |
|------|------|------------|-----------------|
| 1 | T1 — Persistence layer | None | ~15 min |
| 2 | T2 — mission_list light mode | None | ~20 min |
| 3 | T3 — mission_get tool | T1 | ~15 min |
| 4 | T4 — checklist_item_get tool | T1 | ~15 min |
| 5 | T5 — begin_turn project fix + regression tests | None | ~25 min |
| 6 | T6 — Integration tests | T1+T2+T3+T4+T5 | ~20 min |

**Total estimated: ~110 min. All tasks under 400-line review budget.**
