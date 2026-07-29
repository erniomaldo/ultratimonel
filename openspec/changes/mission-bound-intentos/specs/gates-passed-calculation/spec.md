# Dynamic Gates Passed Calculation — Spec Delta

## Requirement: end_turn() calculates gates_passed from real gate states

**REQ-001:** `end_turn()` MUST calculate `gates_passed` dynamically by reading the actual gate states from persistence, NOT use a hardcoded value (e.g. 0).

**Scenario:** All gates PASS — gates_passed equals total
**Given** a session with 4 gates all in PASS state stored in persistence
**When** `end_turn(intento_id)` is called
**Then** `gates_passed` passed to `complete_intento()` MUST equal `4` (or the count of PASS+SKIP gates)
**And** `persistence.list_gate_states()` MUST be called with the intento's session_id and project

**Scenario:** Some gates PASS, some SKIP — sum includes both
**REQ-002:** The `gates_passed` count MUST include gates in both `PASS` and `SKIP` states.

**Given** a session with gates: 1a=PASS, 1b=PASS, 1c=SKIP, 1e=PASS
**When** `end_turn(intento_id)` is called
**Then** `gates_passed` MUST equal `4` (3 PASS + 1 SKIP)

**Given** a session with gates: 1a=PASS, 1b=BLOCK, 1c=WARN, 1e=PASS
**When** `end_turn(intento_id)` is called
**Then** `gates_passed` MUST equal `2` (only PASS and SKIP count; BLOCK and WARN do not)

**Scenario:** No gate states stored — gates_passed is zero
**Given** a session with no prior gate states in persistence
**When** `end_turn(intento_id)` is called
**Then** `gates_passed` MUST equal `0`
**And** the intento MUST still complete successfully (no crash)

**Scenario:** Hardware-fixed — gates_passed=0 no longer occurs as default
**The bug:** Previously, `end_turn()` passed `gates_passed=0` hardcoded to `complete_intento()`, regardless of actual gate results. This meant even when all 4 gates passed, the intento recorded 0 gates passed.
**Fix:** `end_turn()` now reads `list_gate_states(session_id, project)` and counts PASS+SKIP states dynamically.

## Implementation Reference

- `ultratimonel/server.py:1434-1435` — dynamic calculation:
  ```python
  gate_states = persistence.list_gate_states(intento["session_id"], intento["project"])
  gates_passed = sum(1 for g in gate_states if g.get("state") in ("PASS", "SKIP"))
  ```
