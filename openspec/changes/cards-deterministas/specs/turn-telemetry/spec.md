# Delta for turn-telemetry

> NEW capability. Base main spec does NOT exist yet: `cards-solo-ultratimonel` is verified but not archived, so all requirements are declared ADDED (no invented base).

## ADDED Requirements

### Requirement: Internal Turn Telemetry Persistence

`begin_turn` SHALL persist a checkpoint record internally. `end_turn` SHALL persist a checkpoint record and append one entry to the append-only turn log (bitácora). The agent MUST NOT be required to invoke `mcp__agentmemory__*` or `mcp__checkpoint__*` to produce this telemetry.

**Contract (internal sub-steps, not agent tools):**

- `begin_turn` sub-step: checkpoint `{session_id, project, mission_id, quest_id}`.
- `end_turn` sub-step: checkpoint + one bitácora entry `{intento_id, final_status, gates_passed, timestamp}`.

#### Scenario: begin_turn writes an internal checkpoint

- GIVEN a valid quest
- WHEN `begin_turn` is called
- THEN a checkpoint record is persisted internally
- AND no agent-facing telemetry write tool is invoked

#### Scenario: end_turn appends the bitácora entry

- GIVEN a turn bound to an intento
- WHEN `end_turn` closes the turn
- THEN a checkpoint record and one append-only bitácora entry are persisted internally

#### Scenario: No agent-facing telemetry write tool exists

- GIVEN the agent-facing tool catalog
- WHEN it is enumerated
- THEN no tool writes telemetry on behalf of the agent
- AND telemetry exists only as internal sub-steps of the turn calls

### Requirement: Append-only Bitácora Integrity

The bitácora SHALL be append-only. The system MUST NOT update or delete previously written entries.

#### Scenario: Append preserves prior entries

- GIVEN an existing bitácora with N entries
- WHEN a new turn appends an entry
- THEN the previous N entries remain unchanged
- AND the new entry is appended at the end

### Requirement: Best-effort Telemetry Failure

Telemetry persistence SHALL be best-effort. When a checkpoint or bitácora write fails, the turn MUST still complete and the failure MUST NOT force the turn status to `fail`.

#### Scenario: Telemetry failure does not block the turn

- GIVEN a turn reaching `end_turn`
- WHEN the telemetry persistence raises an error
- THEN `end_turn` still completes the turn
- AND the failure is recorded as a non-blocking warning

### Requirement: Telemetry Reads Are Explicit Only

Reading telemetry MUST NOT be required for the turn cycle. The agent MAY read telemetry only when the human explicitly requests it.

#### Scenario: Normal turn requires no telemetry read

- GIVEN a normal `begin_turn → work → end_turn` cycle
- WHEN the cycle runs
- THEN no telemetry read is required

#### Scenario: Human-requested read

- GIVEN an idle system
- WHEN the human explicitly asks for the bitácora or checkpoint history
- THEN the read is available on demand
