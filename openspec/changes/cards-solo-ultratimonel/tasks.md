# Tasks: cards-solo-ultratimonel

Additive change: Deck stays the ONE source of truth; ultratimonel adds a deterministic, turn-aware write surface over the existing `mcp_client` path.

## PAC Phase Status

- Phase 1 — Planning: **COMPLETE** (proposal, 6 specs, design)
- Phase 2 — Implementation: **COMPLETE**
- Phase 3 — Deploy: **COMPLETE**

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | 1,800–2,600 (7 source files + 2 new modules + 6 test files) |
| 400-line budget risk | High |
| Chained PRs recommended | Yes |
| Suggested split | 5 work units → PR1 → PR2 → PR3 → PR4 → PR5 |
| Delivery strategy | chained |
| Chain strategy | feature-branch-chain |

```text
Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: High
```

### Suggested Work Units

| Unit | Goal | Likely PR | Notes |
|------|------|-----------|-------|
| 1 | SQLite v5 + mcp_client Deck tool registration | PR 1 | base `main`; additive schema + migration tests |
| 2 | `deck_bridge.py` + `compact.py` + unit tests | PR 2 | base PR 1; pure/testable, no server wiring |
| 3 | Mission/quest write tools in `server.py` | PR 3 | base PR 2; Deck-first then replica |
| 4 | `begin_turn` guard + `end_turn` wrapper | PR 4 | base PR 3; turn protocol + compact output |
| 5 | `sync_task`/deprecation + best-effort gates + regression tests | PR 5 | base PR 4 |

### Traceability

| Decision | Tasks | | Capability | Tasks |
|----------|-------|-|------------|-------|
| D1 | 1.3, 1.4 | | mission-quest-management | 1.3, 2.1–2.4, 3.1 |
| D2 | 1.3, 2.4 | | turn-state-protocol | 2.5, 2.6, 3.1 |
| D3 | 1.3, 2.3 | | deck-sync | 2.7, 3.1 |
| D4 | 1.1, 1.5, 2.9 | | compact-tool-outputs | 1.1, 1.5, 2.9, 3.1 |
| D5 | 2.5 | | mission-gate | 2.1–2.4, 2.7 |
| D6 | 2.6 | | triple-match | 2.8, 3.2 |
| D7 | 2.7 | | | |
| D8 | 2.8 | | | |
| D9 | 1.2 | | | |
| D10 | 2.4, 4.1 | | | |

## Phase 1: Foundation / Infrastructure

- [x] 1.1 Create `ultratimonel/compact.py`: pure `compact_gate`/`compact_gates`/`compact_mission`/`compact_quest` dropping `result_data` (D4). Done: pure, no I/O. Rollback: delete file.
- [x] 1.2 In `ultratimonel/persistence.py` bump `SCHEMA_VERSION` 4→5 (`persistence.py:42`), add `_migrate_v4_to_v5` with `ALTER TABLE missions ADD COLUMN deck_stack_id INTEGER`, fresh-DB DDL, and `set_quest_done`/`get_mission_by_deck_task` (D9, NF-GP-05). Done: reopen DB → `PRAGMA table_info(missions)` shows column, no data loss. Rollback: older server ignores unknown version.
- [x] 1.3 Create `ultratimonel/deck_bridge.py` over `mcp_client.call_mcp_tool("nextcloud", …)`: `create_card`, `update_title`, `update_description` (preserves quests, D3), `append_quest`, `update_quest`, `complete_quest`, `extract_quests`; each returns `(value, err)` (D1/D2). Done: bridge never writes SQLite. Rollback: delete file.
- [x] 1.4 Add `deck_create_card`/`deck_create_stack` to `TOOL_NAMES["nextcloud"]` in `ultratimonel/mcp_client.py` (`mcp_client.py:92`) (D1). Done: names resolve through existing `call_mcp_tool` path. Rollback: revert dict entries.
- [x] 1.5 Add `tests/test_compact.py` and `tests/test_deck_bridge.py`: serializers drop `result_data`; `extract_quests`; description preservation; bridge-unavailable leaves no local write. Done: pytest green. Rollback: delete files.

## Phase 2: Core Implementation

- [x] 2.1 Add `mission_create` tool in `ultratimonel/server.py` (Deck-first via bridge, then replica refresh) (Req 1). Done: returns `mission_id/deck_task_id/title/status`, no quests. Rollback: remove `@app.tool` fn.
- [x] 2.2 Add `mission_update_title` (unknown `mission_id` → not-found error, NO Deck call). Done: per spec scenario. Rollback: remove fn.
- [x] 2.3 Add `mission_update_description` using bridge `update_description` (D3). Done: quests byte-identical before/after. Rollback: remove fn.
- [x] 2.4 Add `quest_add` + `quest_update` (Deck-first, set `done=false`; NO mark-complete tool) (D2/D10). Done: tool surface enumerates no complete tool. Rollback: remove fns.
- [x] 2.5 Modify `begin_turn` (`server.py:1112`): resolve quest before ANY mutation; `done=true` → `{"error","code":"quest_done","quest_id"}` with no intento/gate write; `quest_id` canonical 4th param, `checklist_item_id` trailing alias (D5). Done: guard precedes orphan cleanup + gates. Rollback: restore signature.
- [x] 2.6 Wrap `end_turn` (`server.py:1266`): unconditional `- [ ]`→`- [x]` via bridge, replica refresh, compact output (no `result_data`); replace `gates_passed >= 4` (`server.py:1367`) with mandatory-gates check (D6/D8). Done: quest `done` becomes true only here. Rollback: restore current flow.
- [x] 2.7 Add `sync_task(mission_id)` (Deck read → parse → replica; report `quests_synced`), mark `sync_all` (`server.py:1008`) `~~DEPRECATED~~` but registered, retain `sync_tasks` (D7). Done: single mission only refreshed. Rollback: remove marker/tool.
- [x] 2.8 In `ultratimonel/gate_engine.py`: add `best_effort` to `GateConfig`/`GateResult`, set gates 1a/1b `mandatory=False, best_effort=True`, make `aggregate` (`gate_engine.py:136`) ignore their `WARN`/`BLOCK`; 1c/1e unchanged (D8). Confirm `triple_match.py` needs no change. Done: 1c WARN still yields WARN. Rollback: revert defaults.
- [x] 2.9 In `mission_list` (`server.py:1054`) default `include_description=False` and route read/list outputs through `compact.py`; no global `verbose` flag (D4). Done: compact default. Rollback: restore default.

## Phase 3: Testing / Verification

- [x] 3.1 Update `tests/test_server.py`: new tools registered, Deck called before replica upsert, `begin_turn` guard (no intento/no gate write), `end_turn` transition + compact payload, `sync_all` marker.
- [x] 3.2 Update `tests/test_gate_engine.py` and `tests/test_triple_match.py`: 1a/1b `WARN`/unavailable non-blocking (overall `PASS`, no forced `fail`); 1c/1e behavior unchanged.
- [x] 3.3 Update `tests/test_persistence.py`: v4→v5 migration adds `deck_stack_id` without data loss.
- [x] 3.4 Run `.venv/bin/pytest`; map every task to its spec scenario and confirm 13 requirements / 34 scenarios covered.

## Phase 4: Deploy / Cleanup

- [x] 4.1 Align public comments/docstrings to `done`/`quest` terminology; keep `mission_update_description` order-preserving (D10, D3). Done: no destructive DDL, no `result_data` in defaults.
- [x] 4.2 Cutover note: Hermes prunes raw Nextcloud card tools (out of repo scope); Deck-first write path and `sync_task` recovery verified against a configured bridge.
