# Specification: Enforcement v3 - Plugin Preflight Guard Mechanism Fixes

## Purpose

Fix three critical issues in ultratimonel's `plugin_preflight.py` guard mechanism causing reliability and deadlock problems. Based on proposal.md requirements for persistent turn tracking, fail-all blocking, and deadlock prevention.

## Requirements

### R1: Persistent Turn Counter Per Session
- **R1.1** The turn counter MUST persist across server restarts per session.
- **R1.2** `_on_session_start` SHALL load persisted turn count from `session_turns` table or initialize to 0.
- **R1.3** `_pre_llm_call` SHALL increment and persist the new turn count after each turn.

### R2: Fail-All Blocking Post-Grace Period
- **R2.1** After GRACE_TURNS (default=3), ALL tools MUST be blocked if gates fail.
- **R2.2** The bouncer SHALL check `_turn_count > GRACE_TURNS` BEFORE gate status.
- **R2.3** Block condition: `_turn_count > GRACE_TURNS AND NOT all_gates_pass(SKIP/PASS)`.

### R3: Deadlock Prevention for begin_turn
- **R3.1** `begin_turn` MUST be exempt from `TOOLS_REQUIRING_VERIFIED_GATES`.
- **R3.2** Agent SHALL always recover by calling `begin_turn` to restart the turn cycle.

## Scenarios

### Scenario 1: Server Restart Preserves Turn Count
- GIVEN session "abc-123" has turn_count=5 persisted in SQLite
- WHEN server restarts and pre_llm_call fires for that session
- THEN _turn_count SHALL be restored to 5 from persistence
- AND gates execute against correct project context

### Scenario 2: Post-Grace Universal Block
- GIVEN GRACE_TURNS=3, turn_count=4, gates not all PASS/SKIP
- WHEN tool call triggers pre_tool_call bouncer
- THEN ALL tools MUST be blocked with unified message
- BUT begin_turn is exempt per R3.1

### Scenario 3: Gate Recovery Without Deadlock
- GIVEN gates fail after grace period (turn_count > GRACE_TURNS)
- WHEN agent calls begin_turn to fix gates
- THEN begin_turn SHALL NOT be blocked by bouncer
- AND agent can execute assert_gates/check_gate successfully

## Acceptance Criteria

### AC1: Turn Counter Persistence
- [ ] SQLite `session_turns` table exists with (session_id PK, turn_count, updated_at)
- [ ] `_on_session_start()` loads persisted count or defaults to 0
- [ ] `_pre_llm_call()` persists incremented count after each turn

### AC2: Fail-All Blocking Logic  
- [ ] Bouncer checks turn_count against GRACE_TURNS first
- [ ] If turn_count > GRACE_TURNS, block ALL tools uniformly (not selective list)
- [ ] Error message indicates grace period expiration clearly

### AC3: No Deadlock Path
- [ ] `begin_turn` removed from TOOLS_REQUIRING_VERIFIED_GATES set
- [ ] Agent can always call begin_turn post-grace to recover
- [ ] TC4 test passes (chicken-and-egg scenario)

## Data Model Additions

**New Table: session_turns**
```sql
CREATE TABLE IF NOT EXISTS session_turns (
    session_id TEXT PRIMARY KEY,
    turn_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

**Persistence Methods (persistence.py)**
- `get_turn_count(session_id) -> int` - returns 0 if not found
- `set_turn_count(session_id, count) -> bool` - persists and returns success

## Test Cases

| ID | Description | Expected Result |
|----|-------------|-----------------|
| TC1 | Server restart preserves turn count | Counter resumes from persisted value |
| TC2 | Tool call during grace period allowed | Tools execute even with failed gates (first 3 turns) |
| TC3 | Tool call post-grace with failed gates | ALL tools blocked uniformly |
| TC4 | begin_turn called post-grace with failed gates | begin_turn NOT blocked, agent recovers |
| TC5 | Multiple sessions have independent turn counts | Each session tracks own turn_count |