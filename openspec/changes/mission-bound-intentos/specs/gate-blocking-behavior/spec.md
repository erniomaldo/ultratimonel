# Gate Blocking Behavior — Spec Delta

## Requirement: Mandatory gate failure returns BLOCK

**REQ-001:** When a mandatory gate raises an exception or returns a failing state, `run_gate()` MUST return `BLOCK`, not `WARN`.

**Scenario:** Mandatory gate executor raises exception
**Given** a gate with `mandatory=True` (e.g. "1a", "1b", "1e")
**When** the gate's executor raises an exception (e.g. connection refused, timeout)
**Then** `run_gate()` MUST return `GateResult` with `state=BLOCK`
**And** the message MUST contain the exception details
**And** `aggregate()` MUST treat this as a blocking condition (overall=BLOCK)

**Scenario:** Non-mandatory gate failure returns WARN
**REQ-002:** When a non-mandatory gate raises an exception, `run_gate()` MUST return `WARN`, not `SKIP`.

**Given** a gate with `mandatory=False` (e.g. "1c" — collectives)
**When** the gate's executor raises an exception
**Then** `run_gate()` MUST return `GateResult` with `state=WARN`
**And** `aggregate()` MUST treat this as a warning condition (overall=WARN, not BLOCK)

**Scenario:** Aggregate respects mandatory vs non-mandatory severity
**Given** gates: 1a=PASS, 1b=BLOCK(mandatory), 1e=PASS
**When** `aggregate()` is called
**Then** overall MUST be `BLOCK`

**Given** gates: 1a=PASS, 1b=PASS, 1c=WARN(non-mandatory), 1e=PASS
**When** `aggregate()` is called
**Then** overall MUST be `WARN` (not BLOCK, not PASS)

**Given** gates: 1a=PASS, 1b=PASS, 1c=SKIP(non-mandatory), 1e=PASS
**When** `aggregate()` is called
**Then** overall MUST be `PASS` (SKIP is a soft pass)

## Implementation Reference

- `ultratimonel/gate_engine.py:125` — `result.state = BLOCK if config.mandatory else WARN`
- `ultratimonel/gate_engine.py:163-168` — aggregate severity ordering: BLOCK > WARN > PASS/SKIP
