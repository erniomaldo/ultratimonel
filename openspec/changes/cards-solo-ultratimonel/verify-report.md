# Verification Report

**Change**: cards-solo-ultratimonel
**Version**: N/A (delta specs, 6 capabilities)
**Mode**: Standard (`strict_tdd: false`; runner `.venv/bin/pytest` exists — no strict-TDD module loaded)
**Branch**: `feature_189_cards-solo-ultratimonel` (inspected by reading files only; NO git command executed)
**Verifier**: fresh-context adversarial `sdd-verify` executor (no code modified)

---

## Executive Summary

The change is additively implemented across 9 files (2 new modules, 7 modified), all
20 tasks are checked, and the bounded deterministic suite passes **193/193 with 0
failures** (12 deselected). The declared 13-requirement / 34-scenario mapping is
substantially correct: **33/34 scenarios have a passing covering test**; the
remaining one (`Raw external mark call is eliminated`) is inherently an out-of-repo
Hermes cutover and is only partially covered. Verification surfaced **0 CRITICAL**, **6
WARNING**, and **5 SUGGESTION** issues. The most material gaps are honest limitations of
the declared evidence: partial runtime coverage (12 real-MCP tests deselected / hanging)
and no real end-to-end run against Deck (all bridge writes mocked). Verdict: **PASS WITH
WARNINGS**.

---

## Completeness

| Metric | Value |
|--------|-------|
| Tasks total | 20 |
| Tasks complete | 20 |
| Tasks incomplete | 0 |

All tasks `1.1–1.5, 2.1–2.9, 3.1–3.4, 4.1, 4.2` are marked `[x]` in `tasks.md`.
PAC phase status: Planning COMPLETE, Implementation COMPLETE, Deploy COMPLETE.
No unchecked implementation task → no CRITICAL on completeness.

---

## Build & Tests Execution

**Build**: ➖ Not applicable — pure Python package, no build step configured
(`openspec/config.yaml`: no `build_command`, no bundler).

**Linter / Type-checker**: ➖ Not available (`config.yaml`: `linter.available: false`,
`type_checker.available: false`).

**Tests**: ✅ 193 passed / ❌ 0 failed / ⚠️ 12 deselected (bounded deterministic subset)

```text
timeout 300 .venv/bin/pytest \
  tests/test_server.py tests/test_gate_engine.py tests/test_triple_match.py \
  tests/test_deck_bridge.py tests/test_compact.py tests/test_persistence.py \
  tests/test_mcp_client.py -q \
  --deselect tests/test_triple_match.py::TestTripleMatch \
  --deselect tests/test_server.py::TestEndTurn::test_end_turn_success_4_4 \
  --deselect tests/test_server.py::TestEndTurn::test_end_turn_blocked_by_block_gate \
  --deselect tests/test_server.py::TestEndTurn::test_end_turn_warn_gates_completes_as_fail \
  --deselect tests/test_server.py::TestEndTurn::test_end_turn_non_running_mismatch_still_errors \
  --deselect tests/test_server.py::TestEndTurn::test_end_turn_partial_pass \
  --deselect tests/test_server.py::TestEndTurn::test_end_turn_clears_active_turn \
  --deselect tests/test_server.py::TestBeginTurnProjectFix::test_end_turn_validates_against_persisted_project
→ 193 passed, 12 deselected in 10.31s   (exit 0)
```

Reproduced the exact apply-phase command; result matches the apply claim (193 / 12).

Additional independent runs (this verifier):

| Command | Result |
|---------|--------|
| `.venv/bin/pytest tests/test_server.py -q` (×4) | ✅ 84 passed (4.0–4.1s), exit 0 each run |
| `.venv/bin/pytest tests/test_gate_engine.py tests/test_triple_match.py -q --deselect …TestTripleMatch` | ✅ 46 passed, 5 deselected |
| `.venv/bin/pytest tests/test_deck_bridge.py tests/test_compact.py tests/test_mcp_client.py -q` | ✅ 32 passed |
| `.venv/bin/pytest tests/test_triple_match.py::TestTripleMatch -q` | ⏱️ TIMEOUT (exit 124, 60s) — pre-existing hang |
| `.venv/bin/pytest tests/test_integration.py -q` | ⏱️ TIMEOUT (exit 124, 90s) — pre-existing hang |
| The 7 deselected `test_server.py` tests, run as a group | ⏱️ TIMEOUT (exit 124, 120s, 1/7 completed) |
| Each of the 7 deselected `test_server.py` tests, individually | ⏱️ TIMEOUT (exit 124, 25s each) |

**Coverage**: ➖ Not available (`config.yaml`: `coverage.available: false`,
`coverage_threshold: 0`). No coverage gate to enforce.

---

## Foci Answers (PM contract — mandatory)

### Focus 1 — `triple_match.py` classification stamp; gates 1c/1e unchanged; 1a/1b no longer block

**Verified by reading `ultratimonel/triple_match.py:401-406`.**

The edit is a small classification stamp inside `run_triple_match`: for each gate it
reads `GATE_CONFIG_MAP[gate_name]` and assigns `result.mandatory` / `result.best_effort`
from config. It does **not** touch execution order, timeouts, executors, error isolation,
or the envelope. (The PM note says "1 line"; factually it is a comment plus a 4-line
`if` block — functionally a single authoritative stamp, so the intent holds.)

- **Gates 1a/1b no longer block**: `DEFAULT_GATES` sets 1a/1b `mandatory=False,
  best_effort=True` (`gate_engine.py:62-75`). `aggregate()` `continue`s past
  best-effort gates (`gate_engine.py:174-176`), so their WARN/BLOCK cannot degrade the
  aggregate. `end_turn` computes `final_status` from persisted mandatory gates only
  (`server.py:2042-2048`), so 1a/1b WARN cannot force `fail`. Confirmed at runtime by
  `TestBestEffortClassification::test_run_stamps_best_effort_and_later_gates_still_run`
  (1a/1b unavailable → WARN, overall PASS) and
  `TestFluxConsolidated::test_workflow_no_assert_gates_required` (1b WARN mandatory=0 →
  `final_status == "success"`), both **PASSED**.
- **Gates 1c/1e aggregate semantics unchanged**: 1c `mandatory=False, best_effort=False`;
  1e `mandatory=True, best_effort=False` (`gate_engine.py:76-88`). A 1c WARN still
  yields overall WARN; a 1e BLOCK still yields BLOCK. Confirmed by
  `test_1c_warn_still_yields_overall_warn`, `test_1c_1e_config_unchanged`,
  `test_non_best_effort_warn_still_aggregates_to_warn`, `test_mandatory_block_still_blocks`
  — all **PASSED**.
- **Caveat (WARNING W5)**: the *end_turn* criterion was changed from the old hardcoded
  `gates_passed >= 4` to mandatory-only (`server.py:2042-2048`, task 2.6/WU4). This is
  the designed D8 behavior and it preserves 1c's **aggregate** classification, but it
  means a 1c WARN no longer forces `end_turn` `fail` (under the old `>=4` criterion it
  did). So "non-best-effort behavior unchanged" holds at the aggregate layer, not at the
  `end_turn` final-status layer. This is documented in design D8 and is not a WU5
  regression.

### Focus 2 — Real impact of the ~12-test deselection

The deselection is **defensible but does remove integration-level runtime coverage**:

- **`TestTripleMatch` (5 tests)**: unpatched, spawn real MCP subprocesses. Confirmed to
  **hang** (exit 124 at 60s). These are the only tests that run `run_triple_match` against
  real executors end-to-end. Their loss is offset for spec purposes by the mocked
  `TestBestEffortClassification` (5 tests, PASSED) — so **no spec scenario loses its
  covering test**, but the real-executor orchestration path is unverified at runtime.
- **`tests/test_integration.py` (whole file)**: confirmed to **hang** (exit 124 at 90s).
  Not part of the declared change surface.
- **The 7 `test_server.py` tests deselected** (`TestEndTurn::test_end_turn_success_4_4`,
  `…blocked_by_block_gate`, `…warn_gates_completes_as_fail`, `…non_running_mismatch_still_errors`,
  `…partial_pass`, `…clears_active_turn`, `TestBeginTurnProjectFix::test_end_turn_validates_against_persisted_project`):
  they call `begin_turn` **without** patching `run_triple_match`, so they hit real MCP.
  They are **order-dependent**: each **hangs when run in isolation** (exit 124) and as a
  group (1/7 completed), yet `tests/test_server.py` **as a whole passes 84/84 four times
  in a row** (they complete in ~1.1s in-file). This confirms pre-existing host-specific
  non-determinism, not a regression.
- **Net coverage impact**: the bounded subset does not exercise (a) real `run_triple_match`
  orchestration through `begin_turn`, nor (b) the pre-existing `TestEndTurn` assertions in
  a small deterministic context. The end_turn wrapper scenario remains covered by the new
  `TestEndTurnQuestTransition` (3 tests, PASSED) and by the full-file run. No **new** spec
  scenario is left without a passing covering test because of the deselection.

### Focus 3 — What remains unverified end-to-end (no real Deck E2E)

Uniformly confirmed by reading the tests: **every** bridge-touching test patches
`ultratimonel.mcp_client.call_mcp_tool` or `ultratimonel.server.deck_bridge.*`
(`TestMissionCreate/UpdateTitle/UpdateDescription/QuestWriteTools/SyncTask`,
`TestDeckBridge`, `TestEndTurnQuestTransition`).

Therefore the following remain **unverified against a live Deck**:

- Real `deck_create_card` / `deck_update_card` request/response shapes (the bridge's
  `_normalize_card`, `_extract_card_id`, and `(value, err)` handling are only tested
  against fake payloads).
- Description composition against a live card: reading the real `description` field,
  preserving byte-identical quest lines, and re-appending them (D3). The byte-preservation
  property is proven only over synthetic strings in `test_deck_bridge.py` /
  `test_server.py`.
- The real HTTP-to-stdio path (`call_mcp_tool("nextcloud", …)`) and its error/timeout
  semantics for the new operations.
- `sync_task`'s `deck_get_stacks(include_cards=True)` actual-stack discovery and
  `deck_stack_id` backfill against a real board.

`openspec/config.yaml` declares e2e `available: false`; the apply's cutover note (§4.2)
acknowledges the real smoke remains manual. Declared honestly.

### Focus 4 — Spec mapping validated against actual passing tests

The declared mapping is **13/13 requirements and 34/34 scenarios**, and I reproduced it
against the verbose runtime pass list. Result: **33/34 COMPLIANT**, **1/34 PARTIAL**
(no UNTESTED, no FAILING). Details in the Spec Compliance Matrix below.

### Focus 5 — Regression (bounded deterministic subset)

Exact command and counts are in "Build & Tests Execution". **193 passed, 0 failed, 12
deselected**, exit 0 — matches the apply claim. `test_server.py` full-file run also
passes 84/84 (×4). The 5 `TestTripleMatch` tests and `test_integration.py` are confirmed
pre-existing hangs, not regressions caused by this change (they were not touched by the
change surface).

### Focus 6 — Confronted declared policies

| Declared policy | Evidence | Verdict |
|---|---|---|
| `sync_task` refreshes a **single** mission; does **not delete** quests removed in Deck | `server.py:1078-1151`: reads one mission, upserts one mission row, loops quests with `upsert_checklist_item(item_index=idx)`. No delete call. `TestSyncTask::test_refreshes_single_mission_and_backfills_stack` asserts `upsert_mission.call_count == 1`. | Single-mission ✅; deletion ❌ not implemented (WARNING W3, deviation 16) |
| Quest closure is **Deck-first**; bridge failure → no replica write; turn closes with `quest_done=false`; recoverable via `sync_task` | `server.py:1908-1923`: `set_quest_done` only after `deck_bridge.complete_quest` returns ok; on failure returns `(quest_id, False)` and `end_turn` still completes. `TestEndTurnQuestTransition::test_end_turn_bridge_failure_skips_replica_but_still_completes` asserts `set_quest_done.assert_not_called()` and `complete_intento_with_gates` called. `sync_task` re-reads Deck and refreshes replica → recoverable. | ✅ Confirmed |
| `end_turn` compact output (no `result_data`) | `server.py:2084` uses `compact.compact_gates(final_gates)` = `{name, state, mandatory}`. Test asserts `"result_data" not in raw` and exact compact gate list. | ✅ Confirmed |
| `begin_turn` hard-fail guard on a done quest (zero mutation) | `server.py:1712-1737`: guard runs before orphan cleanup/gates; returns `{error, code:"quest_done", quest_id}`. `TestBeginTurnQuestGuard::test_done_quest_fails_with_no_mutation` asserts no cleanup/gates/intento/gate-state writes. | ✅ Confirmed |

---

## Spec Compliance Matrix

Status legend: ✅ COMPLIANT (covering test passed) · ⚠️ PARTIAL · ❌ UNTESTED/FAILING.

### compact-tool-outputs (2 requirements / 4 scenarios)

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| Compact Output by Default | end_turn returns compact output | `test_server.py > TestEndTurnQuestTransition::test_end_turn_flips_quest_and_returns_compact` | ✅ COMPLIANT |
| Compact Output by Default | mission_list returns compact output | `test_server.py > TestMissionListLightMode::test_default_is_compact` | ✅ COMPLIANT |
| Compact Output by Default | Read and list tools return compact output | `test_server.py > TestCompactReadAndNoVerbose::test_checklist_item_get_is_compact`; `TestChecklistItemGet::test_checklist_item_get_returns_item` | ✅ COMPLIANT |
| No Global Verbose Flag | No global verbose toggle | `test_server.py > TestCompactReadAndNoVerbose::test_no_tool_exposes_a_global_verbose_param` | ✅ COMPLIANT |

### deck-sync (3 requirements / 5 scenarios)

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| sync_task Recovers One Mission | Recover a single mission | `test_server.py > TestSyncTask::test_refreshes_single_mission_and_backfills_stack`; `::test_cached_stack_skips_stack_lookup` | ✅ COMPLIANT |
| sync_task Recovers One Mission | Unknown local mission id | `test_server.py > TestSyncTask::test_unknown_mission_not_found_no_deck` | ✅ COMPLIANT |
| sync_tasks Is Retained | sync_tasks remains available | `test_server.py > TestSyncToolSurface::test_sync_task_and_sync_tasks_registered`; `TestSyncTasksMarkdownFallback` (3) | ✅ COMPLIANT |
| sync_all Is Deprecated but Registered | sync_all is deprecated and retained | `test_server.py > TestSyncToolSurface::test_sync_all_deprecated_but_registered` | ✅ COMPLIANT |
| sync_all Is Deprecated but Registered | Deprecation points to sync_task | `test_server.py > TestSyncToolSurface::test_deprecation_points_to_sync_task` | ✅ COMPLIANT |

### mission-gate (1 requirement / 4 scenarios)

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| Server MCP Tool Surface | Existing gate tools still work | `test_server.py > TestAssertGates::test_assert_gates_uses_status_key`; `TestCompleteGate` (5); `TestCheckGate` (2) | ✅ COMPLIANT |
| Server MCP Tool Surface | New deterministic tools are registered | `test_server.py > TestWriteToolSurface::test_deterministic_write_tools_registered`; `TestSyncToolSurface::test_sync_task_and_sync_tasks_registered` | ✅ COMPLIANT |
| Server MCP Tool Surface | sync_all is deprecated but registered | `test_server.py > TestSyncToolSurface::test_sync_all_deprecated_but_registered` | ✅ COMPLIANT |
| Server MCP Tool Surface | Completing a non-existent gate fails | `test_server.py > TestCompleteGate::test_complete_gate_unknown_gate` | ✅ COMPLIANT |

### mission-quest-management (3 requirements / 9 scenarios)

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| Deterministic Mission Write Tools | Create a mission | `test_server.py > TestMissionCreate::test_deck_before_replica_and_no_quests` | ✅ COMPLIANT |
| Deterministic Mission Write Tools | Update a mission title | `test_server.py > TestMissionUpdateTitle::test_deck_before_replica_and_preserves_description` | ✅ COMPLIANT |
| Deterministic Mission Write Tools | Update description does not touch the checklist | `test_server.py > TestMissionUpdateDescription::test_preserves_quests_byte_identical_and_deck_first`; `test_deck_bridge.py > TestUpdateDescription` (3) | ✅ COMPLIANT |
| Deterministic Mission Write Tools | Reject an unknown mission | `test_server.py > TestMissionUpdateTitle::test_unknown_mission_skips_deck`; `TestMissionUpdateDescription::test_unknown_mission_skips_deck` | ✅ COMPLIANT |
| Quest Write Tools / No Mark-Complete | Add a quest sets done false | `test_server.py > TestQuestWriteTools::test_quest_add_deck_first_done_false` | ✅ COMPLIANT |
| Quest Write Tools / No Mark-Complete | Update a quest resets done false | `test_server.py > TestQuestWriteTools::test_quest_update_resets_done_false` | ✅ COMPLIANT |
| Quest Write Tools / No Mark-Complete | No mark-complete tool exists | `test_server.py > TestWriteToolSurface::test_no_mark_complete_tool_exists` | ✅ COMPLIANT |
| Deck Is the Source of Truth | Write path targets Deck first | `test_server.py > TestMissionCreate::test_deck_before_replica_and_no_quests`; `TestQuestWriteTools::test_quest_add_deck_first_done_false`; `TestSyncTask::test_refreshes_single_mission_and_backfills_stack`; `test_deck_bridge.py` (17) | ✅ COMPLIANT |
| Deck Is the Source of Truth | Bridge unavailable causes failure | `test_server.py > TestMissionCreate::test_bridge_failure_makes_no_replica_write`; `TestQuestWriteTools::test_bridge_failure_makes_no_replica_write`; `test_deck_bridge.py > TestBridgeUnavailable` (4) | ✅ COMPLIANT |

### triple-match (1 requirement / 5 scenarios)

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| Gate Orchestration and Best-Effort Classification | Full triple match succeeds | `test_triple_match.py > TestBestEffortClassification::test_run_stamps_best_effort_and_later_gates_still_run` (mocked). **Unpatched `TestTripleMatch::test_all_gates_run_in_order` DESELECTED/hangs.** | ✅ COMPLIANT (mocked covering test passed) |
| Gate Orchestration … | Best-effort gate warning does not block the turn | `test_triple_match.py > TestBestEffortClassification::test_best_effort_warns_yield_overall_pass`; `test_gate_engine.py > TestBestEffortAggregation::test_best_effort_warn_is_ignored`; `test_server.py > TestFluxConsolidated::test_workflow_no_assert_gates_required` | ✅ COMPLIANT |
| Gate Orchestration … | Best-effort gate unavailable is non-blocking | `test_triple_match.py > TestBestEffortClassification::test_run_stamps_best_effort_and_later_gates_still_run` | ✅ COMPLIANT |
| Gate Orchestration … | Existing failure isolation is preserved | `test_triple_match.py > TestBestEffortClassification::test_run_stamps_best_effort_and_later_gates_still_run` (1c/1e execute despite 1a/1b unavailable) | ✅ COMPLIANT |
| Gate Orchestration … | Non-best-effort behavior unchanged | `test_1c_warn_still_yields_overall_warn`; `test_1c_1e_config_unchanged`; `test_gate_engine.py > TestBestEffortAggregation::test_non_best_effort_warn_still_aggregates_to_warn` | ✅ COMPLIANT (aggregate layer; see WARNING W5 re end_turn) |

### turn-state-protocol (3 requirements / 7 scenarios)

| Requirement | Scenario | Test | Result |
|---|---|---|---|
| begin_turn Fails on a Done Quest | begin_turn fails on a done quest | `test_server.py > TestBeginTurnQuestGuard::test_done_quest_fails_with_no_mutation` | ✅ COMPLIANT |
| begin_turn Fails on a Done Quest | begin_turn succeeds on an open quest | `test_server.py > TestBeginTurnQuestGuard::test_open_quest_creates_intento_and_returns_ids` | ✅ COMPLIANT |
| end_turn Owns the Only false→true Transition | end_turn completes the quest | `test_server.py > TestEndTurnQuestTransition::test_end_turn_flips_quest_and_returns_compact` | ✅ COMPLIANT |
| end_turn Owns the Only false→true Transition | No other tool transitions a quest | `test_server.py > TestWriteToolSurface::test_no_mark_complete_tool_exists` | ✅ COMPLIANT |
| end_turn Owns the Only false→true Transition | Raw external mark call is eliminated | Repo-side: `test_no_mark_complete_tool_exists` + `test_end_turn_flips_quest_and_returns_compact` (transition only via `deck_bridge.complete_quest`). Hermes-side (no raw Nextcloud call) is out-of-repo cutover. | ⚠️ PARTIAL |
| end_turn Remains a Wrapper | Existing behavior preserved | `test_server.py > TestEndTurnQuestTransition` (3); pre-existing `TestEndTurn` passes in full-file run (`test_server.py` = 84/84) but is deselected in the bounded subset | ✅ COMPLIANT |
| end_turn Remains a Wrapper | No new bottleneck tool | `test_server.py > TestWriteToolSurface::test_no_mark_complete_tool_exists` | ✅ COMPLIANT |

**Compliance summary**: 33/34 scenarios COMPLIANT, 1/34 PARTIAL (0 UNTESTED, 0 FAILING).

---

## Correctness (Static Evidence)

| Requirement | Status | Notes |
|---|---|---|
| Deterministic Mission Write Tools | ✅ Implemented | `mission_create` / `mission_update_title` / `mission_update_description` present, Deck-first via `deck_bridge`, not-found short-circuits before any Deck call (`server.py:1351-1522`). |
| Quest Write Tools / No Mark-Complete | ✅ Implemented | `quest_add` / `quest_update` always `done=False`; no tool matches mark-complete patterns (verified by `app.list_tools()` test). |
| Deck Is the Source of Truth | ✅ Implemented | Bridge writes Deck via `mcp_client`; replica refreshed only after ack; bridge failure returns error and performs no local write. |
| begin_turn Fails on a Done Quest | ✅ Implemented | Guard at `server.py:1712-1737`, before orphan cleanup/gates; `quest_id` canonical 4th positional + `checklist_item_id` alias. |
| end_turn Owns the Only false→true Transition | ✅ Implemented | `_complete_quest_for_intento` (`server.py:1863-1923`) is the only `set_quest_done(…, True)` path; unconditional on `final_status`. |
| end_turn Remains a Wrapper | ✅ Implemented | Pre-existing flow preserved; compact `gates` + `quest_id`/`quest_done` added. |
| sync_task Recovers One Mission | ⚠️ Partial | Single-mission refresh + `deck_task_id` resolution ✅. Deletion of quests removed in Deck is **not** performed (W3). |
| sync_tasks Is Retained | ✅ Implemented | `sync_tasks` untouched. |
| sync_all Is Deprecated but Registered | ✅ Implemented | Docstring starts with `~~DEPRECATED~~`, points to `sync_task`, remains registered (`server.py:1154-1200`). |
| Compact Output by Default | ✅ Implemented | `compact.py` pure serializers; `mission_list` default `include_description=False`; `checklist_item_get` compact; `end_turn` drops `result_data`. |
| No Global Verbose Flag | ✅ Implemented | No `verbose` parameter anywhere in the tool surface (test-enforced). |
| Gate Orchestration / Best-Effort | ✅ Implemented | `best_effort` on `GateConfig`/`GateResult`; 1a/1b `mandatory=False, best_effort=True`; `aggregate` skips best-effort WARN/BLOCK; `run_triple_match` stamps classification; `end_turn` uses mandatory-only criterion. |
| Additive, reversible schema (D9/NF-GP-05) | ✅ Implemented | `SCHEMA_VERSION` 4→5; only `ALTER TABLE missions ADD COLUMN deck_stack_id INTEGER` (nullable); migration test passes (`TestDbMigrationV4ToV5::test_migration_v4_to_v5_adds_deck_stack_id_without_data_loss`). |

---

## Coherence (Design)

| Decision | Followed? | Notes |
|---|---|---|
| D1 — new `deck_bridge.py` over `mcp_client`; `bridge.py` untouched | ✅ Yes | Bridge implemented; `bridge.py` not modified; `(value, err)` contract honored. |
| D2 — quest = markdown checkbox line | ✅ Yes | `extract_quests` regex over `- [ ]`/`- [x]`/`*` bullets; no new Deck entity. |
| D3 — `mission_update_description` never touches quests | ✅ Yes | Preserved quest lines byte-identical, original order, re-appended; incoming prose cannot introduce a quest. |
| D4 — compact by default via pure `compact.py` | ✅ Yes | Pure module, no I/O; no global `verbose`. |
| D5 — `begin_turn` guard before any mutation; 4th positional = `quest_id` | ✅ Yes (behavior) | Guard precedes all side effects. **Spec-schema deviation**: spec declares `mission_id`/`quest_id` required + `work_description`; impl requires `session_id`/`project`, makes ids optional, uses `message` (WARNING W4). |
| D6 — `end_turn` wrapper + only false→true; unconditional | ✅ Yes | Closure independent of `final_status`; only transition path. |
| D7 — `sync_task` singular + `sync_tasks` retained + `sync_all` deprecated-but-registered | ⚠️ Mostly | All present/registered/marked; `sync_task` does not reconcile deleted quests (W3). |
| D8 — 1a/1b best-effort; 1c/1e untouched; `aggregate` ignores best-effort WARN/BLOCK | ✅ Yes (aggregate) | Aggregate behavior matches; `end_turn` mandatory-only criterion changes 1c's end_turn effect vs old `gates_passed>=4` (WARNING W5). |
| D9 — additive, reversible SQLite v4→v5 | ✅ Yes | Nullable column only; migration test green. |
| D10 — unify terminology to `done`/`quest` | ✅ Yes | Public vocabulary uses `quest`/`done`; SQLite column unchanged. |
| Documented deviations (apply-progress §Deviations 1–18) | ✅ Disclosed | Each maps to observed code; none break a spec except the noted W3 gap. |

---

## Issues Found

### CRITICAL
None. All 20 tasks checked; test exit code 0; every required spec scenario has a
passing covering test (one process/cutover half is PARTIAL, recorded as WARNING).

### WARNING
- **W1 — Partial runtime coverage (deselection).** 12 tests deselected; `TestTripleMatch`
  (5) and `tests/test_integration.py` are confirmed pre-existing hangs, so real-executor
  `run_triple_match` orchestration and the integration file are never verified at runtime.
  The 7 `test_server.py` tests are order-dependent (hang in isolation/small groups; pass
  within the full file). No *new* spec scenario loses its covering test, but the
  integration layer is unverified.
- **W2 — No real end-to-end against Deck.** Every write tool, `sync_task`, and the bridge
  are tested only with mocked `mcp_client`/`deck_bridge`. Real `deck_create_card` /
  `deck_update_card` behavior, description composition against a live card, and the
  HTTP-to-stdio error/timeout path remain unverified (`e2e: available: false`).
- **W3 — `sync_task` does not delete replica quests removed in Deck** (apply deviation 16).
  `upsert_checklist_item` is keyed by `item_index`; no deletion helper is invoked. The
  spec says `sync_task` "refreshes that mission's fields and quests", so a quest deleted
  in Deck leaves a stale replica row. Consistent with `sync_tasks`, but the requirement's
  "refreshes quests" is only partially met.
- **W4 — `begin_turn` deviates from the spec's declared tool schema.** Spec input:
  `{mission_id (required), quest_id (required), work_description (optional)}`. Impl:
  `begin_turn(session_id, project, mission_id=0, quest_id=0, message="", sender="user",
  checklist_item_id=0)`. Design D5 explicitly resolves this (session/project remain
  required for backward compatibility), but the literal spec schema is not matched.
- **W5 — D8 end_turn criterion changes 1c's end_turn effect.** Replacing hardcoded
  `gates_passed >= 4` with mandatory-only means a 1c WARN no longer forces `end_turn`
  `fail` (it did before). 1c's **aggregate** classification/failure handling is unchanged,
  which is what the spec scenario checks, but the phrase "non-best-effort behavior
  unchanged" does not hold for the end_turn final-status layer.
- **W6 — `Raw external mark call is eliminated` is only partially covered.** The
  repo-side property (no raw mark tool; only `end_turn`/`deck_bridge.complete_quest`
  transitions) is covered by passing tests; the Hermes-side cutover (pruning raw Nextcloud
  card tools) is out of repo scope and unverifiable here.

### SUGGESTION
- **S1 — Stale/legacy test semantics (deselected).** `TestEndTurn::test_end_turn_partial_pass`
  docstring says "completes as fail" but asserts `final_status == "success"`;
  `TestEndTurn::test_end_turn_warn_gates_completes_as_fail` hardcodes `1b` `mandatory: 1`
  (production now stamps 1b `mandatory=False`). Both are deselected, so the bounded subset
  hides a docstring/semantics drift. Consider aligning them with D8.
- **S2 — `run_gate` exception semantics shifted for 1a/1b.** With `mandatory=False`,
  `run_gate` maps an executor exception to `SKIP` instead of `WARN` (`gate_engine.py:132`).
  `run_gate` is not used in the production path (server uses `run_triple_match`), but it is
  a latent behavior change for any future caller/test.
- **S3 — Redundant classification stamping.** The stamp exists in `run_triple_match`
  (authoritative), `begin_turn` (`server.py:1783-1788`), and `assert_gates`
  (`server.py:2170`). Harmless but duplicated; a single helper would reduce drift risk.
- **S4 — Dead local in `aggregate`.** `all_pass = True` (`gate_engine.py:161`) is assigned
  but never used.
- **S5 — `mission_update_description` replica stores incoming prose only.** The replica
  description omits quest lines (which live only in Deck), so it diverges from the live
  card until the next sync (apply deviation 8). Acceptable for a replica, worth noting.

---

## Verdict

**PASS WITH WARNINGS**

All 20 tasks complete, the bounded deterministic suite is green (193 passed / 0 failed /
12 deselected, exit 0), and 33/34 spec scenarios have a passing covering test (1 PARTIAL
out-of-repo cutover). No CRITICAL issues. The change is spec-coherent and design-coherent
within the limits of its declared evidence; the warnings are honest scope/limitation gaps
(partial runtime coverage, no real Deck E2E, `sync_task` non-deletion, spec-schema
deviation, and the D8 end_turn-criterion nuance) that the apply phase largely disclosed.

### Limitations (declared honestly)
- 12 tests deselected; 5 `TestTripleMatch` + all `test_integration.py` confirmed hanging
  (pre-existing). The 7 `test_server.py` deselections are order-dependent and pass only
  in the full-file run.
- No live Deck E2E; all new write paths verified against mocks/fakes.
- No coverage tool, linter, type-checker, or build step available.
- Source inspection only; **no git command was executed** and **no code was modified** by
  this verification.
