# Tasks: quest-list-bulk (Card Deck #194)

> **Change:** `quest-list-bulk` · **Date:** 2026-10-18
> **Inputs:** [proposal.md](./proposal.md) · [spec.md](./specs/quest-list/spec.md)
> **Branch:** `feature_194_quest-list` (current branch — no checkout)
> **Rules:** `openspec/config.yaml` (PEP 8, type hints, MCP compliance)

---

## Review Workload Forecast

| Task | Files | Est. lines | Risk |
|------|-------|-----------|------|
| T1 — SDD artifacts (proposal + spec + tasks) | 3 | ~200 | None |
| T2 — `quest_list` tool | 1 | ~30 | Low |
| T3 — Unit tests (`TestQuestList`) | 1 | ~90 | Low |
| T4 — Integration catalog assertion | 1 | ~2 | Low |
| **Total** | **6** | **~320** | — |

**Forecast: ~320 changed lines (incl. artifacts).** Under the 400-line budget.
No chained PRs needed. Natural cut if exceeded: `artefactos SDD | código+tests`.

---

## Dependency Graph

```
T1 (artifacts) ─┐
T2 (tool) ──────┼─► T3 (unit tests)
                └─► T4 (integration catalog)
```

Recommended order: T1 → T2 → T3 → T4.

---

## Tasks

### T1 — SDD artifacts

**Files:** `openspec/changes/quest-list-bulk/proposal.md`,
`specs/quest-list/spec.md`, `tasks.md`

**What:** Document intent, scope, the R4 symmetry decision (not implemented —
see proposal), RFC 2119 spec with explicit input/output schemas, and these task
phases. `design.md` omitted: the only real decision (R4) is recorded in the
proposal per the contract.

**Done when:**
- [ ] Proposal records the R4 decision and rationale
- [ ] Spec has Given/When/Then scenarios and explicit schemas
- [ ] Tasks grouped by phase with hierarchical numbering

---

### T2 — Tool: `quest_list(mission_id, include_done=True)`

**Files:** `ultratimonel/server.py`

**What:** Add a read-only tool after `checklist_item_get` (before the mission /
quest write-tools section). Reuse `persistence.get_mission()`,
`persistence.list_checklist_items()` (already `ORDER BY item_index`) and the
pure `compact.compact_quest()` serializer. No new persistence method, no bridge,
no schema change.

**How:** Resolve the mission with `get_mission`; on miss return
`{"error": "Mission <id> not found"}`. Otherwise map `list_checklist_items`
rows through `compact.compact_quest` → `{id, text, done}`, drop done quests when
`include_done=False`, and return
`{"mission_id", "quests", "total"}` via `json.dumps(..., ensure_ascii=False,
default=str)`. Source of truth for the exact code is the code slice
(`ultratimonel/server.py`).

**Done when:**
- [ ] `quest_list` registered with `@app.tool()`, type hints, PEP 8
- [ ] Uses only the replica; never calls the bridge
- [ ] `include_done=False` filters done quests; default includes them
- [ ] Unknown mission returns `{"error": "Mission <id> not found"}`

---

### T3 — Unit tests: `TestQuestList`

**Files:** `tests/test_server.py`

**What:** Add `TestQuestList` (mock `ultratimonel.server.persistence`) covering
the spec scenarios:

- `test_quest_list_returns_full_checklist`: N quests, order preserved, `done` bool
- `test_quest_list_include_done_true_includes_done`: default and explicit True
- `test_quest_list_include_done_false_omits_done`: only pending returned
- `test_quest_list_mission_not_found`: error message contains the id; no mutation
- `test_quest_list_registered_in_catalog`: `quest_list` present in the catalog

**Done when:**
- [ ] All 5 tests pass
- [ ] No existing `test_server.py` test breaks

---

### T4 — Integration: catalog assertion

**Files:** `tests/test_integration.py`

**What:** In the live-catalog test (`test_tools_listed`), assert `quest_list`
is exposed by the running server.

**Done when:**
- [ ] `quest_list` asserted in the live MCP tool list
- [ ] Full suite green: `.venv/bin/pytest`

---

## Execution Order

| Step | Task | Depends on |
|------|------|------------|
| 1 | T1 — artifacts | None |
| 2 | T2 — tool | T1 |
| 3 | T3 — unit tests | T2 |
| 4 | T4 — integration assertion | T2 |

---

## Status / Evidence (2026-10-18, current branch — inline, no git)

| Task | Status | Evidence |
|------|--------|----------|
| T1 — artifacts | ✅ | `proposal.md`, `specs/quest-list/spec.md`, `tasks.md` |
| T2 — `quest_list` tool | ✅ | `ultratimonel/server.py` (+33 lines); registered in catalog |
| T3 — unit tests | ✅ | `pytest tests/test_server.py::TestQuestList -v` → **5 passed** |
| T4 — integration assert | ⚠️ | assert added; `test_integration.py` cannot execute here (see blocker) |

**Acceptance evidence**

- **One-call real mission** — `quest_list(2389)` → `total=27` in ONE call
  (mission "#…cards…" from the project DB); `include_done=False` → `total=13`;
  `quest_list(999999)` → `{"error": "Mission 999999 not found"}`.
- **Live catalog** — stdio client `list_tools()` → 27 tools, `quest_list` present.
- **Tests** — `.venv/bin/pytest --ignore=tests/test_integration.py`
  → `256 passed in 613.87s`.
- **⚠️ Blocker (pre-existing, not caused by this change)** — `.venv/bin/pytest`
  hangs in `tests/test_integration.py`. The `client_session` fixture raises
  `RuntimeError: Attempted to exit cancel scope in a different task than it was
  entered in` (pytest-asyncio 1.4.0 + module-scoped `anyio` fixture with a
  function-scoped `event_loop`). Reproduces on `test_server_initializes` alone
  (a test that does not touch `quest_list`) and on the unmodified fixture.

**Changed lines:** SDD artifacts 312 + code/tests 119 = **431** → exceeds the
400 budget; natural cut applied and reported: **SDD artifacts (312) | code+tests (119)**.
