# Apply Progress: cards-solo-ultratimonel

## Status

- **Change**: `cards-solo-ultratimonel`
- **Mode**: Standard (strict_tdd: false, test runner `.venv/bin/pytest`)
- **Batch**: WU5 of 5 (WU1 + WU2 + WU3 + WU4 + WU5 complete)
- **Overall**: `success` — all 20 tasks complete; change ready for `sdd-verify`
- **Branch**: `feature_189_cards-solo-ultratimonel` (no git operations performed)

## Work Unit Progress

| WU | Goal | Tasks | State |
|----|------|-------|-------|
| WU1 | SQLite v5 + Deck tool registration | 1.2, 1.4, 3.3 | done |
| WU2 | `deck_bridge.py` + `compact.py` + unit tests | 1.1, 1.3, 1.5 | done |
| WU3 | Mission/quest write tools in `server.py` | 2.1–2.4 | done |
| WU4 | `begin_turn` guard + `end_turn` wrapper + compact default | 2.5, 2.6, 2.9 | done |
| WU5 | `sync_task` + deprecation + best-effort gates + verification + cleanup | 2.7, 2.8, 3.1, 3.2, 3.4, 4.1, 4.2 | done |

> Work-unit boundary note (historical): the earlier WU3 batch table listed `2.8`
> under WU4. The orchestrator resolved WU4 to **exactly 2.5, 2.6, 2.9**; `2.8`
> was then assigned to **WU5** and is implemented in this batch.

## WU1 Scope

SQLite schema v4→v5 + Nextcloud Deck tool-name registration in `mcp_client`,
plus the WU1 tests.

| Task | Description | State |
|------|-------------|-------|
| 1.2 | `persistence.py`: `SCHEMA_VERSION` 4→5, `_migrate_v4_to_v5`, fresh-DB DDL, `set_quest_done`/`get_mission_by_deck_task` | done |
| 1.4 | `mcp_client.py`: register `deck_create_card`/`deck_create_stack` in `TOOL_NAMES["nextcloud"]` | done |
| 3.3 | `tests/test_persistence.py`: v4→v5 migration adds `deck_stack_id` without data loss | done |

## WU2 Scope

Two new **pure/testable** modules plus their unit tests. No `server.py` wiring,
no SQLite access, no WU3+ work.

| Task | Description | State |
|------|-------------|-------|
| 1.1 | `ultratimonel/compact.py`: pure `compact_gate`/`compact_gates`/`compact_mission`/`compact_quest` dropping `result_data` (D4) | done |
| 1.3 | `ultratimonel/deck_bridge.py`: Deck-first write bridge over `mcp_client.call_mcp_tool("nextcloud", …)` — `create_card`, `update_title`, `update_description` (quests preserved, D3), `append_quest`, `update_quest`, `complete_quest`, `extract_quests`; each returns `(value, err)`; never writes SQLite | done |
| 1.5 | `tests/test_compact.py` + `tests/test_deck_bridge.py` | done |

## WU3 Scope

The five deterministic mission/quest **write tools** in `server.py`, wired to the
WU2 `deck_bridge` (Deck-first) with a replica refresh only after Deck acks. No
`begin_turn`/`end_turn`/`sync_*` changes.

| Task | Description | State |
|------|-------------|-------|
| 2.1 | `mission_create(project, title, description="")`: resolve board + stack, `deck_bridge.create_card`, then `persistence.upsert_mission`; returns `{mission_id, deck_task_id, title, status}`; no quests | done |
| 2.2 | `mission_update_title(mission_id, title)`: unknown id → not-found error with **no** Deck call; known → `deck_bridge.update_title` then replica refresh; returns `{mission_id, title, status}` | done |
| 2.3 | `mission_update_description(mission_id, description)`: `deck_bridge.update_description` (D3, quests byte-identical), then replica refresh; returns `{mission_id, status}` | done |
| 2.4 | `quest_add(mission_id, title)` + `quest_update(quest_id, title=None, position=None)`: Deck-first, always `done=false`; **no** mark-complete tool | done |

Shared WU3 helpers added in `server.py` (module-level, not tools):
`_resolve_board_id` (project maps → `deck_board_id`), `_fetch_stacks`
(`deck_get_stacks`), `_resolve_stack_id` (mission `deck_stack_id` with a
`deck_get_stacks` fallback when `NULL`, preferring a pending/backlog stack on
create), and `_refresh_mission_replica`.

## WU4 Scope — turn protocol + compact output (§2.5, §2.6, §2.9)

### §2.5 `begin_turn` quest guard (design D5)

- Signature: `begin_turn(session_id, project, mission_id=0, quest_id=0, message="", sender="user", checklist_item_id=0)`.
  `quest_id` is the **canonical 4th positional parameter** (positionally
  compatible with the old `checklist_item_id`, kept as a **trailing alias**).
- **Step 0 guard runs before the orphan cleanup AND before gate execution.** It
  resolves `resolved_quest_id = quest_id or checklist_item_id`; when present it
  looks up the quest:
  - not found (`None`) → `{"error", "code": "missing_quest", "quest_id"}`.
  - `done` truthy → `{"error", "code": "quest_done", "quest_id"}`.
  Both short-circuit with **zero state mutation** (no orphan cleanup, no
  `extract_context`, no gates, no `create_intento`, no `upsert_gate_state`).
- Success payload also carries `mission_id` and `quest_id`.

### §2.6 `end_turn` wrapper (design D6) + mandatory criterion (D8 criterion part)

- Existing flow preserved (resolve intento → turn scoping → capture gates →
  validate → complete intento → clear active turn → return).
- **Quest closure** added via `_complete_quest_for_intento(intento)`, called
  before `complete_intento_with_gates`: resolves
  `mission_id`/`checklist_item_id`, resolves board/stack, calls
  `deck_bridge.complete_quest(...)` (`- [ ]` → `- [x]`), then refreshes the
  replica with `persistence.set_quest_done(quest_id, True)`. It is
  **UNCONDITIONAL** with respect to `final_status`. Deck-first: the replica is
  refreshed **only** after the Deck write acks (D1). Legacy intentos without
  `mission_id`/`checklist_item_id` skip the transition.
- **Completion criterion**: `final_status` is `"fail"` iff any **mandatory** gate
  is not in `{PASS, SKIP}`, else `"success"` (the old `gates_passed >= 4` is
  gone).
- **Compact output**: `gates` is `compact.compact_gates(final_gates)` —
  `{name, state, mandatory}` only, **no raw `result_data`**. Payload adds
  `quest_id`/`quest_done`; `gates_passed`/`gates_total` retained.

### §2.9 `mission_list` compact default (design D4)

- `mission_list(project, include_description=False)` — default is compact;
  each mission is `compact.compact_mission(m)` = `{id, title, status}`. The
  per-tool `include_description=True` opt-in returns the full payload.
- `checklist_item_get` returns `compact.compact_quest(item)` = `{id, text, done}`.
- **No global `verbose` flag** anywhere in the tool surface.

## WU5 Scope — `sync_task` + deprecation + best-effort gates + verification + cleanup

### §2.7 `sync_task` + `sync_all` deprecation (design D7)

- New `sync_task(mission_id)` in `server.py`. It resolves the mission, its
  board, and its stack internally, reads the authoritative card through
  `deck_bridge.read_card` (new public wrapper over `_read_card`), parses the
  description with `deck_bridge.extract_quests`, and refreshes **only** that
  mission's replica fields + quests. Output:
  `{"mission_id", "deck_task_id", "status", "quests_synced"}`. Unknown
  `mission_id` → not-found error with no Deck call and no replica write.
- **`deck_stack_id` backfill**: new
  `persistence.set_mission_deck_stack_id(mission_id, deck_stack_id)` is called
  after the replica refresh, closing the WU3/WU4-reported gap so future writes
  skip the extra `deck_get_stacks` lookup.
- **Stack resolution hardening** (new `_resolve_stack_for_card`): when
  `deck_stack_id` is `NULL` (every mission before its first `sync_task`), the
  card is located within `deck_get_stacks(include_cards=True)` so the *actual*
  stack is discovered (same shape `sync_tasks` consumes) before backfill;
  falls back to the pending/first-stack heuristic when the card is not found.
  With a populated `deck_stack_id`, the extra stacks call is skipped entirely.
- `sync_all` docstring now starts with `~~DEPRECATED~~` and points to
  `sync_task`; it remains registered and invocable (same marker pattern as
  `assert_gates`). `sync_tasks` is untouched.

### §2.8 gates 1a/1b best-effort (design D8)

- `gate_engine.GateConfig`/`GateResult` gained `best_effort: bool = False`.
- `DEFAULT_GATES`: 1a (`agentmemory`) and 1b (`agentcheckpoint`) are now
  `mandatory=False, best_effort=True`. 1c and 1e classification is unchanged
  (1c `mandatory=False, best_effort=False`; 1e `mandatory=True,
  best_effort=False`).
- `aggregate` ignores `WARN`/`BLOCK` from `best_effort` gates (their entry is
  still reported in `gate_dicts`); the accumulated-WARN-forces-`fail` behavior
  is removed for those two gates only. A non-best-effort WARN (e.g. 1c) still
  yields overall `WARN`.
- `run_gate` stamps `best_effort` from config.
- `triple_match.run_triple_match` now stamps each result's
  `mandatory`/`best_effort` from `GATE_CONFIG_MAP` at execution time — the
  single authoritative seam, so `begin_turn`, `assert_gates`, and `aggregate`
  all see 1a/1b as best-effort without duplicating logic.
  `_call_agentmemory`/`_call_checkpoint` still return `WARN` on failure; only
  their impact on the aggregate changed.
- **`triple_match.py` change confirmation**: no behavioral change to 1c/1e was
  needed. The only triple_match edit is the classification stamp; it does not
  alter gate execution, ordering, timeouts, or envelopes.

### §3.4 verification + task→scenario mapping

Run on the bounded deterministic subset (see Test Evidence). Mapping of the 13
requirements / 34 scenarios to tasks and tests is in the **Task → Spec Scenario
Mapping** section below.

### §4.1 cleanup (D10, D3)

- Public docstrings/comments aligned to `done`/`quest` vocabulary
  (`sync_tasks` docstring now describes quests as markdown checkbox lines;
  `quest_add`/`quest_update`/`end_turn`/`checklist_item_get` already used the
  term).
- `mission_update_description` is order-preserving (D3) and unchanged.
- Verified: the change introduces **no destructive DDL** (v4→v5 is only
  `ALTER TABLE missions ADD COLUMN deck_stack_id INTEGER`; the pre-existing
  guarded v1→v2 legacy `DROP TABLE missions` predates this change and is
  untouched), and **no `result_data`** in default tool outputs.

### §4.2 cutover note

- **Hermes cutover (out of repo scope)**: Hermes must prune the raw Nextcloud
  card tools so the Deck-first write path is the only writer. This repo cannot
  enforce Hermes config; the change keeps `sync_task`/`sync_tasks`/`sync_all`
  and the new write tools registered so the cutover is config-only.
- **Verified against a configured Deck bridge**: on this host a live
  `nextcloud-mcp-server` + `http-to-stdio` bridge is running. The Deck-first
  write path (`mission_create`/`update_*`/`quest_*`) and `sync_task` recovery
  are exercised deterministically with a mocked `mcp_client.call_mcp_tool`
  (ordering, backfill, and no-local-write-on-failure asserted); the
  unpatched real-MCP end-to-end smoke remains manual (e2e `available: false`).
- **Rollback**: `git revert` removes the new tools and restores the prior MCP
  surface; `sync_all` is never removed so no caller must be undone; Deck data is
  never modified by rollback; the extra SQLite column is inert to older code.

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `ultratimonel/persistence.py` | Modified (WU1, WU5) | **WU1**: `SCHEMA_VERSION` 4→5, `deck_stack_id` column, `_migrate_v4_to_v5`, migration wiring, `get_mission_by_deck_task`, `set_quest_done`. **WU5**: new `set_mission_deck_stack_id(mission_id, deck_stack_id)` backfill helper. |
| `ultratimonel/mcp_client.py` | Modified (WU1) | Added `deck_create_card`/`deck_create_stack` to `TOOL_NAMES["nextcloud"]`. |
| `tests/test_persistence.py` | Modified (WU1) | v4→v5 migration + `deck_stack_id` + quest-helper tests. |
| `tests/test_mcp_client.py` | Created (WU1) | Deck tool name-resolution tests. |
| `ultratimonel/compact.py` | Created (WU2), Modified (WU4) | Pure compact serializers; `compact_gate` `gate_name` fallback. |
| `ultratimonel/deck_bridge.py` | Created (WU2), Modified (WU5) | Deck write bridge; **WU5**: new public `read_card` (used by `sync_task`). |
| `tests/test_compact.py` | Created (WU2) | 12 serializer-shape tests. |
| `tests/test_deck_bridge.py` | Created (WU2) | 18 parsing/preservation/ordering tests. |
| `ultratimonel/server.py` | Modified (WU3+WU4+WU5) | **WU3/WU4**: mission/quest tools, `begin_turn` guard, `end_turn` wrapper/compact, `mission_list` compact. **WU5**: `sync_task`, `_resolve_stack_for_card`, `sync_all` `~~DEPRECATED~~` marker, `best_effort` propagation, `sync_tasks` docstring terminology. |
| `ultratimonel/gate_engine.py` | Modified (WU5) | `best_effort` on `GateConfig`/`GateResult`; 1a/1b `mandatory=False, best_effort=True`; `aggregate` ignores best-effort `WARN`/`BLOCK`; `run_gate` stamps the flag. |
| `ultratimonel/triple_match.py` | Modified (WU5) | Stamp `mandatory`/`best_effort` from `GATE_CONFIG_MAP` in `run_triple_match`. No 1c/1e behavior change. |
| `tests/test_server.py` | Modified (WU3+WU4+WU5) | **WU4**: guard/transition/compact tests. **WU5**: `TestSyncToolSurface` (3), `TestSyncTask` (3); updated `test_workflow_no_assert_gates_required` for D8. |
| `tests/test_gate_engine.py` | Modified (WU5) | D8 classification test (rewritten) + `TestBestEffortAggregation` (5 tests). |
| `tests/test_triple_match.py` | Modified (WU5) | `TestBestEffortClassification` (5 tests). |
| `openspec/changes/cards-solo-ultratimonel/tasks.md` | Modified (WU5) | Marked `[x]` for 2.7, 2.8, 3.1, 3.2, 3.4, 4.1, 4.2 → **20/20 complete**; PAC phase status set to COMPLETE. |

## Test Evidence

Commands and results (exact):

1. **WU5 bounded deterministic subset** (all 7 target files, pre-existing
   real-MCP tests and the `TestTripleMatch` hang class deselected):
   ```
   timeout 200 .venv/bin/pytest \
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
   ```
   → **193 passed, 12 deselected in 10.50s**

2. **`tests/test_server.py` alone** (includes the 7 unpatched real-MCP tests):
   `.venv/bin/pytest tests/test_server.py -q` → **84 passed in 4.15s** (this run
   exposed no flake; the same real-MCP tests are non-deterministic on this host
   — see Issues).

3. **`tests/test_gate_engine.py` + `tests/test_triple_match.py`** (deselecting
   `TestTripleMatch`):
   `.venv/bin/pytest tests/test_gate_engine.py tests/test_triple_match.py -q --deselect tests/test_triple_match.py::TestTripleMatch`
   → **46 passed, 5 deselected in 0.10s**

4. **Fast unit files**:
   `.venv/bin/pytest tests/test_deck_bridge.py tests/test_compact.py tests/test_mcp_client.py -q`
   → **32 passed**;
   `.venv/bin/pytest tests/test_persistence.py -q` → **38 passed in 13.94s**.

5. **MCP surface enumeration** (via `TestSyncToolSurface` /
   `TestWriteToolSurface` / `TestCompactReadAndNoVerbose`): tool count **26**
   (WU4 baseline 25 + `sync_task`); `sync_task` and `sync_tasks` present;
   `sync_all` present with `~~DEPRECATED~~` in its description; no tool matches a
   mark-complete pattern; no tool exposes a `verbose` parameter;
   `mission_list.parameters.properties.include_description.default == False`.

6. **Full suite `.venv/bin/pytest`: NOT run.** Pre-existing hang /
   network-bound real-MCP spawns in `tests/test_integration.py`,
   `tests/test_triple_match.py::TestTripleMatch`, and the unpatched
   `TestEndTurn`/`TestBeginTurnProjectFix::test_end_turn_validates_against_persisted_project`
   tests in `tests/test_server.py` (a live Nextcloud MCP + agentmemory/checkpoint
   servers are running on this host; `triple_match.HTTP_TIMEOUT = 300.0`). Out
   of scope per the bounded-subset instruction.

## Task → Spec Scenario Mapping (§3.4)

13 requirements / 34 scenarios across 6 delta specs. Every requirement and
scenario maps to a task and to at least one passing test (or, for
process/cutover-only scenarios, to a documented artifact).

### compact-tool-outputs (2 reqs / 4 scenarios)

| Scenario | Task | Evidence |
|----------|------|----------|
| Compact Output by Default → end_turn compact | 2.6 | `TestEndTurnQuestTransition::test_end_turn_flips_quest_and_returns_compact` (no `result_data`) |
| Compact Output by Default → mission_list compact | 2.9 | `TestMissionListLightMode::test_default_is_compact` |
| Compact Output by Default → read/list compact | 2.9 | `TestChecklistItemGet::test_checklist_item_get_returns_item`, `TestCompactReadAndNoVerbose::test_checklist_item_get_is_compact` |
| No Global Verbose Flag → no toggle | 2.9 | `TestCompactReadAndNoVerbose::test_no_tool_exposes_a_global_verbose_param` |

### deck-sync (3 reqs / 5 scenarios)

| Scenario | Task | Evidence |
|----------|------|----------|
| sync_task Recovers One Mission → single mission | 2.7 | `TestSyncTask::test_refreshes_single_mission_and_backfills_stack`, `test_cached_stack_skips_stack_lookup` |
| sync_task Recovers One Mission → unknown id | 2.7 | `TestSyncTask::test_unknown_mission_not_found_no_deck` |
| sync_tasks Is Retained → remains available | 2.7 | `TestSyncToolSurface::test_sync_task_and_sync_tasks_registered`, `TestSyncTasksMarkdownFallback` (3) |
| sync_all Is Deprecated but Registered → retained | 2.7 | `TestSyncToolSurface::test_sync_all_deprecated_but_registered` |
| sync_all Is Deprecated but Registered → points to sync_task | 2.7 | `TestSyncToolSurface::test_deprecation_points_to_sync_task` |

### mission-gate (1 req / 4 scenarios)

| Scenario | Task | Evidence |
|----------|------|----------|
| Server MCP Tool Surface → existing gate tools work | 3.1 | `TestCompleteGate`, `TestCheckGate`, `TestAssertGates` |
| Server MCP Tool Surface → new tools registered | 2.1–2.4, 2.7 | `TestWriteToolSurface::test_deterministic_write_tools_registered`, `TestSyncToolSurface::test_sync_task_and_sync_tasks_registered` |
| Server MCP Tool Surface → sync_all deprecated | 2.7 | `TestSyncToolSurface::test_sync_all_deprecated_but_registered` |
| Server MCP Tool Surface → non-existent gate fails | 3.1 | `TestCompleteGate::test_complete_gate_unknown_gate` |

### mission-quest-management (3 reqs / 9 scenarios)

| Scenario | Task | Evidence |
|----------|------|----------|
| Deterministic Mission Write Tools → create | 2.1 | `TestMissionCreate` (Deck-first, no quests) |
| Deterministic Mission Write Tools → update title | 2.2 | `TestMissionUpdateTitle::test_deck_before_replica_and_preserves_description` |
| Deterministic Mission Write Tools → description keeps checklist | 2.3 | `TestMissionUpdateDescription::test_preserves_quests_byte_identical_and_deck_first` |
| Deterministic Mission Write Tools → reject unknown | 2.2, 2.3 | `TestMissionUpdateTitle::test_unknown_mission_skips_deck`, `TestMissionUpdateDescription::test_unknown_mission_skips_deck` |
| Quest Write Tools / No Mark-Complete → add done=false | 2.4 | `TestQuestWriteTools::test_quest_add_deck_first_done_false` |
| Quest Write Tools / No Mark-Complete → update resets done | 2.4 | `TestQuestWriteTools::test_quest_update_resets_done_false` |
| Quest Write Tools / No Mark-Complete → no complete tool | 2.4 | `TestWriteToolSurface::test_no_mark_complete_tool_exists` |
| Deck Is Source of Truth → write Deck first | 2.1–2.4, 2.7 | `TestMissionCreate` ordering, `TestSyncTask` ordering, `TestDeckBridge` (17) |
| Deck Is Source of Truth → bridge unavailable fails | 1.3, 2.1, 2.4 | `TestMissionCreate::test_bridge_failure_makes_no_replica_write`, `TestQuestWriteTools::test_bridge_failure_makes_no_replica_write`, `TestDeckBridge` |

### triple-match (1 req / 5 scenarios)

| Scenario | Task | Evidence |
|----------|------|----------|
| Full triple match succeeds | 2.8 | `TestBestEffortClassification::test_run_stamps_best_effort_and_later_gates_still_run` |
| Best-effort warning does not block | 2.8 | `TestBestEffortClassification::test_best_effort_warns_yield_overall_pass`, `TestBestEffortAggregation` |
| Best-effort gate unavailable non-blocking | 2.8 | `test_run_stamps_best_effort_and_later_gates_still_run` (1a/1b unavailable) |
| Existing failure isolation preserved | 2.8 | `test_run_stamps_best_effort_and_later_gates_still_run` (later gates execute) |
| Non-best-effort behavior unchanged | 2.8 | `test_1c_warn_still_yields_overall_warn`, `test_1c_1e_config_unchanged` |

### turn-state-protocol (3 reqs / 7 scenarios)

| Scenario | Task | Evidence |
|----------|------|----------|
| begin_turn Fails on a Done Quest → fails on done | 2.5 | `TestBeginTurnQuestGuard::test_done_quest_fails_with_no_mutation` |
| begin_turn Fails on a Done Quest → succeeds on open | 2.5 | `TestBeginTurnQuestGuard::test_open_quest_creates_intento_and_returns_ids` |
| end_turn Owns false→true → completes the quest | 2.6 | `TestEndTurnQuestTransition::test_end_turn_flips_quest_and_returns_compact` |
| end_turn Owns false→true → no other tool transitions | 2.4, 2.6 | `TestWriteToolSurface::test_no_mark_complete_tool_exists` |
| end_turn Owns false→true → raw mark call eliminated | 2.6, 4.2 | `test_end_turn_flips_quest_and_returns_compact` + §4.2 cutover note |
| end_turn Remains a Wrapper → existing behavior preserved | 2.6 | `TestEndTurnQuestTransition` + pre-existing `TestEndTurn` |
| end_turn Remains a Wrapper → no new bottleneck tool | 2.6 | `TestWriteToolSurface::test_no_mark_complete_tool_exists` |

**Coverage**: 13/13 requirements, 34/34 scenarios mapped (process/cutover
scenarios 4.2/raw-mark resolved by the §4.2 cutover note plus the `end_turn`
test).

## Deviations from Design

1. **WU1 migration chain correction** (necessary side effect of the version
   bump). `_migrate_v3_to_v4` now records literal `4`; the v3 branch chains
   v3→v4→v5. Additive only.
2. **WU1 pre-existing gap left untouched.** The v1/v2 migration branches still do
   not create `session_turns`; that gap predates this change.
3. **WU2 `extract_quests` adds `line_no`** per the design Interfaces section;
   `done` is a `bool` (D10 public vocabulary).
4. **WU2 quest mutation reads the card once** and reuses title + lines.
5. **WU2 `update_description` intentionally omits** checkbox lines in incoming
   prose (no hard-fail path).
6. **WU3 `mission_create` stack selection** prefers a pending/backlog-titled
   stack; deterministic choice not named in the design.
7. **WU3/WU4 did NOT persist `deck_stack_id` on write**; **WU5's `sync_task`
   backfill closes this** via `set_mission_deck_stack_id`.
8. **WU3 `mission_update_description` replica refresh stores the incoming prose**
   (bridge keeps Deck quests byte-identical).
9. **WU3 `quest_update` `position` semantics** defaults to the replica
   `item_index`; no cross-line reordering.
10. **WU4 `end_turn` quest closure is skipped for legacy intentos** whose
    `mission_id`/`checklist_item_id` are absent/zero.
11. **WU4 quest closure is Deck-first**: if the bridge write fails, the replica
    `set_quest_done` is NOT written (D1); the turn still completes with
    `quest_done=false`, recoverable via a later `sync_task` (WU5).
12. **WU4 mandatory criterion zero-evidence case**: an empty `final_gates` yields
    `"success"`.
13. **WU4 `mission_get` is unchanged** (already minimal; compacting would drop
    `checklist_item_ids`).
14. **WU5 `sync_task` stack resolution** adds `_resolve_stack_for_card` to
    locate the card's *actual* stack via `deck_get_stacks(include_cards=True)`
    when `deck_stack_id` is `NULL` (design's data flow assumed the column was
    already populated). With the column populated, the extra call is skipped.
    This makes the first recovery correct instead of guessing the pending stack.
15. **WU5 `sync_task` preserves the mission `status`** rather than deriving it
    from the stack title: `deck_get_card` carries no stack context and the design
    data flow for `sync_task` lists only fields + quests. Stack-derived status
    refresh remains the job of bulk `sync_tasks`.
16. **WU5 `sync_task` quest refresh is upsert-by-index** (mirrors `sync_tasks`);
    quest rows removed in Deck are not deleted from the replica, matching the
    existing bulk behavior (no delete helper is in scope).
17. **WU5 classification stamp lives in `run_triple_match`**, not in
    `begin_turn` alone, so `assert_gates`/`aggregate` share the same
    best-effort view. `triple_match.py` therefore DID change (one stamp),
    contrary to the "none expected" note in §2.8 — no 1c/1e behavior changed.
18. **WU5 updated a pre-existing test** (`test_workflow_no_assert_gates_required`)
    to the new D8 semantics: a best-effort 1b WARN no longer forces overall
    `WARN`/`fail`. This is a direct consequence of §2.8, not new scope.

## Issues Found

- **Unpatched real-MCP tests are non-deterministic on this host.** A live
  Nextcloud MCP + agentmemory/checkpoint stack is running; the pre-existing
  `TestEndTurn` (6 tests) and
  `TestBeginTurnProjectFix::test_end_turn_validates_against_persisted_project`
  call `begin_turn` → unpatched `run_triple_match` and can take up to
  `HTTP_TIMEOUT=300s`. They are deselected from the bounded deterministic subset
  (12 deselected total incl. `TestTripleMatch`). Test #27 (`test_end_turn_partial_pass`)
  hung in a combined run before deselection; the same file passed 84/84 in
  isolation. This is pre-existing infrastructure behavior, not a WU5 regression.
- `sync_task` does not delete replica quest rows removed in Deck (deviation 16),
  consistent with `sync_tasks`. A future change could reconcile deletions.
- **HARD RULE honored**: no git command of any kind was executed (not even
  read-only). Changes were reviewed by reading the files directly. No commit,
  push, checkout, or branch operation performed.

## Remaining Tasks

- **None.** tasks.md is at **20/20 complete**. Next phase is `sdd-verify` (not
  run by this executor) and then `sdd-archive`.

## Workload / PR Boundary

- **Mode**: chained PR slice
- **Chain strategy**: `feature-branch-chain`
- **Current work unit**: WU5 — `sync_task` + deprecation + best-effort gates +
  verification + cleanup
- **Parent/base for this slice**: the WU4 slice branch (tracker chain). Per
  `feature-branch-chain`, WU5's child PR targets the immediate previous slice
  (WU4), never `main` directly.
- **Boundary**: starts from the current tracker tip (already contains
  WU1–WU4) and ends with: `sync_task` + `_resolve_stack_for_card` + `read_card`
  + `set_mission_deck_stack_id`, the `sync_all` `~~DEPRECATED~~` marker, the
  `best_effort` gate classification (gate_engine + the `run_triple_match`
  stamp), the WU5 tests, the terminology pass, and this cutover note. Closes the
  change's task list (20/20).
- **Review budget impact**: `gate_engine.py` (~30 lines), `triple_match.py`
  (~10), `server.py` (~130 incl. `sync_task`/helper), `deck_bridge.py` (~12),
  `persistence.py` (~15), `tests/test_server.py` (~140), `tests/test_gate_engine.py`
  (~55), `tests/test_triple_match.py` (~110). Self-contained slice; rollback is
  `git revert` with Deck data and the replica schema unaffected.
