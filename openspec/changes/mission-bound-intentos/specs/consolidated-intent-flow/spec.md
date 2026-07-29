# Consolidated Intent Flow

## Requirement

**REQ-001:** The agent MUST replace the 5+ MCP call per-turn pattern (`assert_gates` → `record_intento` → `complete_gate` ×4) with a consolidated two-tool flow: `begin_turn` creates an intento scoped to the current mission and turn, and `end_turn` completes that turno-scoped intento. A single `intento_id` is returned by `begin_turn` and consumed only by `end_turn`.

## Scenarios

### Scenario 1: begin_turn creates intento with valid mission_id

**GIVEN** the agent has identified a real mission (Deck card) with a non-zero `mission_id`
**WHEN** the agent calls `begin_turn(mission_id=N)` where N > 0 and exists in missions
**THEN** an nuevo intento is created with `turno_actual` set to the current turn, `mission_id=N`, and a valid `intento_id` is returned

### Scenario 2: end_turn completes current turn intento

**GIVEN** `begin_turn` was called this turn and returned `intento_id=X`
**WHEN** the agent calls `end_turn(intento_id=X)` where X belongs to `turno_actual`
**THEN** the intento is marked completed successfully and no error is raised

### Scenario 3: end_turn rejects intento_id from previous turn (turn-scoped)

**GIVEN** a prior turn ended, incrementing `turno_actual` to T+1
**WHEN** the agent calls `end_turn(intento_id=Y)` where Y was created during turn T
**THEN** the call is rejected with an explicit error stating the intento does not belong to the current turn
