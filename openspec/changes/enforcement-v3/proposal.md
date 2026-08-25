# Proposal: Enforcement v3

## Summary

Incomplete plugin preflight enforcement with three critical issues causing reliability and deadlock problems in the ultratimonel MCP server's guard mechanism.

## Business Problem

The `ultratimonel-preflight` plugin has incomplete enforcement that leads to:
1. **Non-persistent turn counter** - Agent turn count resets on server restart, breaking per-session tracking
2. **Incomplete post-grace blocking** - Only a limited set of tools are blocked after grace period ends, not "fail all" pattern
3. **Chicken-and-egg deadlock** - `begin_turn` is in the restricted list; if gates fail after grace period, the mechanism to fix gates (begin_turn) becomes blocked

## Goals

1. Make turn counter persistent per session across server restarts
2. Implement proper "fail all" blocking pattern post-grace period
3. Remove deadlock by exempting `begin_turn` from gate-restricted tools list OR implement recovery path

## Non-Goals

- Modify the core guard logic for non-critical edge cases
- Add new gates or modify existing gate definitions
- Change the user-facing error messages significantly (keep Nikhil pattern)

## Risks & Implications

### Technical Debt
Current implementation uses module-level globals (`_turn_count`, `_last_gates_parsed`) that reset on any server restart. This breaks per-session tracking.

### Backward Compatibility
Changes to `TOOLS_REQUIRING_VERIFIED_GATES` could affect existing agent behavior during grace period transitions.

### Performance Impact
Persisting turn state requires additional I/O but should be minimal with SQLite WAL mode already configured.

## Success Criteria

1. Turn counter persists across server restarts per session
2. Post-grace period blocks ALL tools uniformly (not selective list)
3. No deadlock scenario where gate-fixing mechanism is blocked

## Dependencies

- `plugin_preflight.py` - Main plugin file with enforcement logic
- `persistence.py` - SQLite layer for state persistence  
- `server.py` - FastMCP server with begin_turn tool implementation