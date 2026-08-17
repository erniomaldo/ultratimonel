# Tasks: Assert Gates Deprecation (Card #150) — Retrospective

> **Change:** `assert-gates-deprecation` · **Date:** 2026-08-13
> **Inputs:** [proposal.md](./proposal.md) · [spec.md](./specs/assert-gates-deprecation/spec.md) · [design.md](./design.md)
> **Type:** Retrospective — the diff is already applied in the working tree on `main`; tasks below are marked `[x]` to trace 1:1 with the real diff.

---

## Review Workload Forecast

| Task | Files changed | Est. lines | Risk |
|------|--------------|------------|------|
| T1 — Move `assert_gates` to legacy section + deprecate docstring | 1 (server.py) | ~215 (move: ~105 removed + ~110 added) | Low |
| T2 — README.md count/documentation corrections | 1 | ~12 | Low |
| T3 — README.en.md count/documentation corrections | 1 | ~12 | Low |
| T4 — Retrospective SDD artifacts | 4 (this change) | ~430 (docs only, not code) | Low |
| **Total (code+docs)** | **3 files** | **~239 changed lines** | — |

**Forecast: ~239 changed lines (server.py move + READMEs), matching `git diff --stat` minus the dashboard-astro-migration change.** Under 400-line review budget for code/docs. Single PR (C2). No chained PRs needed. Dashboard-astro-migration excluded (separate PR).

---

## Tasks

### T1 — Move `assert_gates` to legacy section + deprecate docstring (F-AGD-01..05, S1..S4) — DONE

**Files:** `ultratimonel/server.py`

**What:** Relocate the `assert_gates` handler from its original position in "Tool handlers" to the "Legacy / archived tools" section (after `end_turn`), and prefix its docstring with the `~~DEPRECATED~~` marker plus replacement guidance. Signature and body unchanged.

**How (as applied in the diff):**
1. Removed the original `@app.tool() def assert_gates(...)` block (~lines 173–273).
2. Added it after `end_turn` under the existing header `# ── Legacy / archived tools ──` (~line 1408), with updated module docstring reference (`~~DEPRECATED~~ run all gates (use begin_turn)` at line 5).
3. New docstring at line 1419: `"""~~DEPRECATED~~ Run all pre-flight gates and return structured results.` with `use begin_turn() instead (consolidated 2-call flow: begin_turn → trabajo → end_turn)` and warning that the plugin bouncer treats it as the gate step.
4. Kept signature `(message: str, session_id: str, sender: str = "user")` and all 5 execution steps (context, triple match, aggregate, persist, respond) byte-identical.

**Done when (verified):**
- [x] `assert_gates` still registered with `@app.tool()` at line 1413–1414
- [x] Docstring starts `~~DEPRECATED~~` and says `use begin_turn() instead` (line 1419–1422)
- [x] Located under `# ── Legacy / archived tools ──` header (line ~1408)
- [x] `@app.tool()` count == 20; DEPRECATED docstrings == 3 (assert_gates, record_intento, complete_intento)
- [x] Signature and body unchanged (diff shows pure move + docstring edit)
- [x] Module docstring header updated (line 5)

---

### T2 — README.md count/documentation corrections (F-AGD-06..08, S5..S7) — DONE

**Files:** `README.md`

**What:** Correct the tool inventory from 18 (16 active + 2 legacy) to **20 (17 active + 3 legacy)** in all locations; move `assert_gates` from "Núcleo (Gates)" to "Legacy / Archivadas"; add `mission_get` and `checklist_item_get` rows to the Misiones section.

**How (as applied in the diff):**
1. Architecture diagram: `(18 tools)` → `(20 tools)`.
2. Feature table: `18 tools MCP | 16 activas + 2 legacy` → `20 tools MCP | 17 activas + 3 legacy`.
3. Tools section intro: `18 tools MCP: 16 activas + 2 legacy` → `20 tools MCP: 17 activas + 3 legacy`.
4. Removed `assert_gates` row from `### 🧠 Núcleo (Gates)`.
5. Added rows for `mission_get(mission_id)` and `checklist_item_get(checklist_item_id)` to the Misiones table (after `mission_list`).
6. Added `assert_gates` row to `### 🗄️ Legacy / Archivadas` with `~~DEPRECATED~~ — usa begin_turn() en su lugar ...`.
7. Project tree: `18 tool handlers (16 activas + 2 legacy)` → `20 tool handlers (17 activas + 3 legacy)`.

**Done when (verified):**
- [x] No remaining "18" / "16 active" references for the tool count
- [x] "20 tools MCP" + "17 activas + 3 legacy" present in diagram, feature table, tools section
- [x] `assert_gates` present in legacy table, absent from core gates table
- [x] `mission_get` / `checklist_item_get` documented in Misiones section

---

### T3 — README.en.md count/documentation corrections (F-AGD-06..08, S5..S7) — DONE

**Files:** `README.en.md`

**What:** Same corrections as T2 in English: count 18 → 20 (17 active + 3 legacy), `assert_gates` to legacy table, `mission_get` / `checklist_item_get` rows added.

**How (as applied in the diff):**
1. Architecture diagram: `(18 tools)` → `(20 tools)`.
2. Feature table: `18 MCP tools | 16 active + 2 legacy` → `20 MCP tools | 17 active + 3 legacy`.
3. Tools section intro: `18 MCP tools: 16 active + 2 legacy` → `20 MCP tools: 17 active + 3 legacy`.
4. Removed `assert_gates` from `### 🧠 Core (Gates)`.
5. Added `mission_get(mission_id)` and `checklist_item_get(checklist_item_id)` rows to the Missions table.
6. Added `assert_gates` to `### 🗄️ Legacy / Archived` with `~~DEPRECATED~~ — use begin_turn() instead ...`.
7. Project tree: `18 tool handlers (16 active + 2 legacy)` → `20 tool handlers (17 active + 3 legacy)`.

**Done when (verified):**
- [x] No remaining "18" / "16 active" references
- [x] "20 MCP tools" + "17 active + 3 legacy" present in all locations
- [x] `assert_gates` in legacy table, absent from core
- [x] `mission_get` / `checklist_item_get` documented in Missions section

---

### T4 — Retrospective SDD artifacts for this change — DONE

**Files:** `openspec/changes/assert-gates-deprecation/{proposal,design,tasks}.md`, `.../specs/assert-gates-deprecation/spec.md`

**What:** Create retrospective SDD artifacts describing the applied diff (Card #150): proposal with problem/scope/context, spec with RFC 2119 + GIVEN/WHEN/THEN requirements verified against the repo, design with ADRs, and this task trace.

**Done when (verified):**
- [x] All 4 artifacts exist under `openspec/changes/assert-gates-deprecation/`
- [x] Every requirement in spec.md is checkable via grep/tests against the working tree
- [x] No reference to dashboard-astro-migration content

---

## Execution Order

| Step | Task | Depends on | Status |
|------|------|------------|--------|
| 1 | T1 — server.py deprecation | None | Done (working tree) |
| 2 | T2 — README.md corrections | T1 | Done (working tree) |
| 3 | T3 — README.en.md corrections | T1 | Done (working tree) |
| 4 | T4 — Retrospective artifacts | T1+T2+T3 | Done (this change) |

**Total: all tasks complete.** No further apply work required.
