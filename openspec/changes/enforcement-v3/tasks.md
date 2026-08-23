# Tasks: Enforcement v3 - Plugin Preflight Guard Mechanism Fixes

## Review Workload Forecast

| File | Est. Changed Lines | Purpose |
|------|-------------------|---------|
| ultratimonel/persistence.py | ~50 lines | Add session_turns table DDL, get_turn_count/set_turn_count methods, _migrate_v3_to_v4() |
| ultratimonel/ultratimonel_client.py | ~20 lines | Add wrapper functions for turn count persistence |
| ultratimonel/plugin_preflight.py | ~50 lines | Modify hooks to use persistence, exempt begin_turn from bouncer |
| tests/test_persistence.py | ~50 lines | Unit tests for get_turn_count/set_turn_count and migration |
| tests/test_integration.py | ~60 lines | Integration tests for TC1-TC5 scenarios |

**Total Estimated Changed Lines: ~230** ✅ Under 400-line budget (D1)

---
<!-- REVIEW_GUARD_START -->
⚠️ **Budget Check**: Total < 400 lines → No chained PR needed. Changes are cohesive and fit in single review unit per phase.
<!-- REVIEW_GUARD_END -->

## Phase 1: Persistence Layer (persistence.py) ✅ TDD-Ready

### Task 1.1: Add session_turns Table Schema
**File**: `ultratimonel/persistence.py`
- [ ] Add `DDL_SESSION_TURNS` constant with table definition after DDL_V2
- [ ] Update `SCHEMA_VERSION` from 3 to 4
- [ ] Update `SCHEMA_DESCRIPTION` to "v4: session_turns table for persistent turn counting"

### Task 1.2: Implement Turn Count Methods ✅ RED Phase (TDD)
**File**: `ultratimonel/persistence.py`
- [ ] Implement `get_turn_count(session_id: str) -> int` method
  - Returns persisted count or 0 if not found
  - Thread-safe with existing `_lock` pattern
- [ ] Implement `set_turn_count(session_id: str, count: int) -> bool` method
  - INSERT OR REPLACE pattern with ON CONFLICT
  - Updates `updated_at` timestamp

### Task 1.3: Add Migration v3→v4 ✅ GREEN Phase (TDD)
**File**: `ultratimonel/persistence.py`
- [ ] Implement `_migrate_v3_to_v4(conn)` function
  - Creates session_turns table
  - Inserts schema_version record for v4

### Task 1.4: Update Database Initialization ✅ REFACTOR Phase (TDD)
**File**: `ultratimonel/persistence.py`
- [ ] Add elif branch in `_init_db()` for current_ver == 3 migration to v4
- [ ] Ensure fresh DB installs include session_turns table

---

## Phase 2: Client Layer (ultratimonel_client.py) ✅ TDD-Ready

### Task 2.1: Import Persistence Access
**File**: `ultratimonel/ultratimonel_client.py`
- [ ] Import or access the global persistence instance from server module

### Task 2.2: Add Turn Count Wrapper Functions
**File**: `ultratimonel/ultratimonel_client.py`
- [ ] Implement `get_turn_count(session_id: str) -> int` wrapper delegating to persistence layer
- [ ] Implement `set_turn_count(session_id: str, count: int) -> bool` wrapper

---

## Phase 3: Plugin Changes (plugin_preflight.py) ✅ TDD-Ready

### Task 3.1: Modify _on_session_start for Persistence Load
**File**: `ultratimonel/plugin_preflight.py`
- [ ] In `_on_session_start()`: load persisted turn_count from SQLite via ultratimonel_client.get_turn_count()
- [ ] Set module-global `_turn_count` with loaded value (default 0 if not found)

### Task 3.2: Modify _pre_llm_call for Turn Persistence ✅ TC1, TC5
**File**: `ultratimonel/plugin_preflight.py`
- [ ] In `_pre_llm_call()`: load fresh turn_count from persistence (not module global per R2.2)
- [ ] Increment the count locally: `_turn_count += 1`
- [ ] Persist new value via `ultratimonel_client.set_turn_count()`

### Task 3.3: Modify _gates_bouncer for Deadlock Prevention ✅ TC4
**File**: `ultratimonel/plugin_preflight.py`
- [ ] Add early return for `begin_turn`: if tool_name == "mcp__ultratimonel__begin_turn", return None (always allow) - prevents chicken-and-egg deadlock per R3.1
- [ ] Load turn_count from persistence in bouncer instead of module global

### Task 3.4: Implement Universal Blocking Post-Grace ✅ TC2, TC3
**File**: `ultratimonel/plugin_preflight.py`
- [ ] In `_gates_bouncer()`: check if `_turn_count > GRACE_TURNS` BEFORE gate status check (per R2.1)
- [ ] If post-grace AND gates not all PASS/SKIP: block ALL tools uniformly (not selective list per R2.3)
- [ ] Update error message to indicate grace period expiration clearly

### Task 3.5: Remove begin_turn from Restricted Set ✅ AC3.1
**File**: `ultratimonel/plugin_preflight.py`
- [ ] Remove `"mcp__ultratimonel__begin_turn"` from `TOOLS_REQUIRING_VERIFIED_GATES` set (per R3.1)

---

## Phase 4: Unit Tests (tests/test_persistence.py) ✅ GREEN/REFACTOR Phases (TDD)

### Task 4.1: Test Turn Count Persistence Methods ✅ TC1, TC5
**File**: `tests/test_persistence.py`
- [ ] Add `TestTurnCount` class with tests for get_turn_count/set_turn_count
- [ ] `test_get_turn_count_missing_session()` - returns 0 for non-existent session
- [ ] `test_set_and_get_turn_count()` - persist and retrieve correctly
- [ ] `test_multiple_sessions_independent()` - each session has independent turn count

### Task 4.2: Test Migration v3→v4 ✅ REFACTOR Phase (TDD)
**File**: `tests/test_persistence.py`
- [ ] Add `test_migration_v3_to_v4()` - simulate migration from v3 to v4
- [ ] Verify session_turns table exists after migration

---

## Phase 5: Integration Tests (tests/test_integration.py) ✅ TDD Pattern

### Task 5.1: Test Server Restart Preserves Turn Count ✅ TC1
**File**: `tests/test_integration.py`
- [ ] Add test for turn_counter_persists_across_sessions scenario
- [ ] Verify counter resumes from persisted value after "server restart"

### Task 5.2: Test begin_turn Exemption Post-Grace ✅ TC4
**File**: `tests/test_integration.py`
- [ ] Add test_begin_turn_exempt_from_bouncer() - verify no deadlock scenario
- [ ] Assert begin_turn is NOT blocked even with failed gates post-grace

### Task 5.3: Test Universal Blocking Post-Grace ✅ TC2, TC3
**File**: `tests/test_integration.py`
- [ ] Add test_universal_blocking_post_grace() - verify ALL tools blocked uniformly
- [ ] Verify error message indicates grace period expiration clearly

---

## Phase 6: Documentation & Verification (docs/04-soul-enforcement.md)

### Task 6.1: Update Enforcement Documentation ✅ AC Verification
**File**: `docs/04-soul-enforcement.md`
- [ ] Document v3 changes to plugin_preflight guard mechanism
- [ ] Add section on persistent turn counting per session

### Task 6.2: Verify No Regressions ✅ Acceptance Criteria Check
**File**: (no file change)
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Verify all existing tests pass after changes
- [ ] Document any findings in commit message

---

## Task Dependencies Graph

```
Phase 1 (Persistence Layer) ──┐
                              ├──> Phase 3.2, 3.4, 3.5 (Plugin Changes)
Phase 2 (Client Wrappers) ────┘
                               │
Phase 1-2 ──> Phase 3 (Plugin) ──> Phase 4 (Unit Tests)
                                    │
                                    ├──> Phase 5.1 (TC1 - restart persistence)
                                    ├──> Phase 5.2 (TC4 - deadlock prevention)  
                                    └──> Phase 5.3 (TC2/TC3 - universal blocking)

Phase 6 runs after all phases complete + tests pass
```

---

## TDD Pattern Markers

This project uses pytest with fixture-based testing. The following test cases from spec.md are mapped:

| Test Case | Scenario | Location |
|-----------|----------|----------|
| TC1 | Server restart preserves turn count | Phase 4.2, 5.1 |
| TC2 | Tool call during grace period allowed | Phase 3.4, 5.3 (implicit) |
| TC3 | Tool call post-grace with failed gates | Phase 3.4, 5.3 |
| TC4 | begin_turn called post-grace with failed gates | Phase 3.3, 3.5, 5.2 |
| TC5 | Multiple sessions have independent turn counts | Phase 1.2, 4.1 |

---

## Estimated Effort

- **Phase 1 (Persistence Layer)**: 2 hours
  - Schema changes: 30 min
  - Methods implementation: 45 min
  - Migration logic: 30 min
  - Unit tests: 15 min

- **Phase 2 (Client Wrappers)**: 1 hour
  - Wrapper functions: 30 min
  - Integration with plugin: 30 min

- **Phase 3 (Plugin Changes)**: 2 hours
  - _on_session_start modification: 45 min
  - _pre_llm_call modification: 30 min
  - _gates_bouncer fix + begin_turn exemption: 45 min

- **Phase 4-5 (Tests)**: 2.5 hours
  - Unit tests (TDD cycle): 1.5 hours
  - Integration tests: 1 hour

- **Phase 6 (Documentation/Cleanup)**: 0.5 hours

**Total Estimated Effort: ~8 hours**