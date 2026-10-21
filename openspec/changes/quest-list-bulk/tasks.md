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
- [x] Proposal records the R4 decision and rationale
- [x] Spec has Given/When/Then scenarios and explicit schemas
- [x] Tasks grouped by phase with hierarchical numbering

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
- [x] `quest_list` registered with `@app.tool()`, type hints, PEP 8
- [x] Uses only the replica; never calls the bridge
- [x] `include_done=False` filters done quests; default includes them
- [x] Unknown mission returns `{"error": "Mission <id> not found"}`

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
- [x] All 5 tests pass
- [x] No existing `test_server.py` test breaks

---

### T4 — Integration: catalog assertion

**Files:** `tests/test_integration.py`

**What:** In the live-catalog test (`test_tools_listed`), assert `quest_list`
is exposed by the running server.

**Done when:**
- [x] `quest_list` asserted in the live MCP tool list
- [x] Full suite green: `.venv/bin/pytest`

---

## Execution Order

| Step | Task | Depends on |
|------|------|------------|
| 1 | T1 — artifacts | None |
| 2 | T2 — tool | T1 |
| 3 | T3 — unit tests | T2 |
| 4 | T4 — integration assertion | T2 |

---

## Status / Evidence (2026-10-21 — sdd-verify + judgment-day)

| Task | Status | Evidence |
|------|--------|----------|
| T1 — artifacts | ✅ | `proposal.md`, `specs/quest-list/spec.md`, `tasks.md` (this file) |
| T2 — `quest_list` tool | ✅ | `ultratimonel/server.py` (+33 lines); registered in catalog |
| T3 — unit tests | ✅ | `.venv/bin/pytest tests/test_server.py -k quest_list -q` → **5 passed**; `test_server.py` completo → **107 passed** |
| T4 — integration assert | ✅ | `quest_list` asserted in `test_tools_listed`; suite completa verde (abajo) |

**Acceptance evidence**

- **One-call real mission** — `quest_list(2389)` → `total=27` in ONE call;
  `include_done=False` → `total=13`; `quest_list(999999)` →
  `{"error": "Mission 999999 not found"}`.
- **Live catalog** — stdio `list_tools()` incluye `quest_list`.
- **Suite completa** — `.venv/bin/pytest` → **259 passed, 15 deselected in 12.27 s** (exit 0).
- **Tests de integración** — 15 marcados `integration`, excluidos por defecto
  (`pytest.ini`); se corren con env vivo:
  `pytest -m integration`.

**Blocker resuelto (era cuelgue, no cancel-scope)**

Diagnóstico real: el cuelgue no venía del fixture `anyio`. `call_mcp_tool`
levantaba el servidor `nextcloud` **sin argumentos** (`ULTRATIMONEL_NEXTCLOUD_ARGS`
vacío en el entorno de test), es decir un intérprete Python en blanco que nunca
responde `initialize`: 30 s de timeout × 1 reintento = **60 s por llamada**. Con
varios tests tocando gates, la suite parecía colgada.

Correcciones aplicadas en esta rama:

1. `tests/conftest.py` — fixture autouse que fija `call_mcp_tool` a
   `(None, "unavailable")` en todo test no marcado `integration`. Los unit tests
   ya no pueden spawnear servidores vivos por accidente.
2. `pytest.ini` — marker `integration` + `addopts = -m "not integration"`.
3. `tests/test_triple_match.py` — `TestTripleMatch` (5 tests que llaman
   `run_triple_match` sin mock) marcado `integration`.
4. `tests/test_integration.py` — dos tests obsoletos reparados:
   `test_begin_turn_persists_explicit_project` ahora usa misión/quest reales
   (el guard `missing_quest` rechaza `mission_id=0`) y
   `test_universal_blocking_post_grace` fija `_turn_count` y espera el mensaje
   vigente del bouncer.
5. Tests de performance con fórmula invertida
   (`/ iterations * iterations / 1000` → siempre pasaba): corregida a
   `/ iterations * 1000`.

**Veredicto judgment-day:** APPROVE. El cambio es puramente aditivo, reutiliza
`compact_quest`, no toca esquema ni bridge, y sus 5 unit tests cubren orden,
filtrado, error y registro en catálogo. Sin hallazgos bloqueantes.

**Changed lines (esta rama):** SDD 312 + código/tests 119 + harness 92 = **523**.
Excede el presupuesto de 400: corte natural ya aplicado y reportado
(**artefactos SDD | código+tests**); el harness de tests se separó como commit
propio para revisión aislada.
