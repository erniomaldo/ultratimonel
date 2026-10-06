# Delta for turn-state-protocol

> Base main spec does NOT exist yet: `cards-solo-ultratimonel` is verified but not archived, so all requirements are declared ADDED (no invented base). Extended by `turn-cycle-enforcement` and `turn-telemetry`.

## ADDED Requirements

### Requirement: begin_turn and end_turn Are the Only State Channel

`begin_turn` and `end_turn` SHALL be the only tools that mutate turn state. `begin_turn` MUST run, in order: quest guard → binding → attempt-budget check → telemetry checkpoint → gate execution → intento creation. `end_turn` MUST run, in order: binding validation → gate verdict → closure → telemetry append → intento completion.

#### Scenario: begin_turn runs its sub-steps in order

- GIVEN a valid open quest
- WHEN `begin_turn` is called
- THEN the guard, binding, budget and checkpoint sub-steps run before gate execution
- AND the intento is created last

#### Scenario: end_turn runs its sub-steps in order

- GIVEN a bound active intento
- WHEN `end_turn` is called
- THEN binding validation, the gate verdict, closure and the telemetry append run before completion
- AND the intento is finalized

#### Scenario: No other tool mutates turn state

- GIVEN the agent-facing tool catalog
- WHEN it is enumerated
- THEN only `begin_turn` and `end_turn` mutate turn state

### Requirement: begin_turn Fails on a Done Quest

`begin_turn` MUST fail hard when the target quest `done` value is `true`, and MUST NOT create an intento or mutate any state.

#### Scenario: Done quest blocks begin_turn

- GIVEN a quest whose `done` value is `true`
- WHEN `begin_turn` is called for that quest
- THEN the call fails with a clear `quest_done` error
- AND no intento is created
- AND the quest remains `done=true`

#### Scenario: Open quest allows begin_turn

- GIVEN a quest whose `done` value is `false`
- WHEN `begin_turn` is called
- THEN an intento is created
- AND the response contains the `intento_id` and `quest_id`

### Requirement: Internal Sub-steps Are Not Agent Calls

Telemetry and budget enforcement SHALL run inside `begin_turn`/`end_turn`. The agent MUST NOT invoke separate tools for checkpoint, bitácora or budget handling.

#### Scenario: One end_turn call covers closure and telemetry

- GIVEN an active turn
- WHEN `end_turn` is called once
- THEN closure and the telemetry append both happen inside that call
- AND no additional agent tool call is required
