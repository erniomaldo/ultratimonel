# Delta for turn-state-protocol

## ADDED Requirements

### Requirement: begin_turn Fails on a Done Quest

`begin_turn` MUST verify that the target quest is not complete before creating an intento. When the quest `done` value is `true`, the call MUST fail hard and MUST NOT create an intento or mutate any state.

**Tool input/output schema:**

- Input: `{ "mission_id": integer (required), "quest_id": integer (required), "work_description": string (optional) }`
- Success output: `{ "intento_id": integer, "mission_id": integer, "quest_id": integer, "status": string }`
- Failure output: `{ "error": string, "code": string, "quest_id": integer }`

#### Scenario: begin_turn fails on a done quest

- GIVEN a quest whose `done` value is `true`
- WHEN `begin_turn` is called for that quest
- THEN the call fails with a clear error
- AND no intento is created
- AND the quest remains `done=true`

#### Scenario: begin_turn succeeds on an open quest

- GIVEN a quest whose `done` value is `false`
- WHEN `begin_turn` is called
- THEN an intento is created
- AND the response contains the `intento_id` and the `quest_id`
- AND the quest remains `done=false`

### Requirement: end_turn Owns the Only false-to-true Transition

`end_turn` MUST perform the only quest `done` transition from `false` to `true`. `end_turn` MUST be the only operation that updates intento, item, or quest state. The server MUST NOT expose any additional tool that mutates quest state, and Hermes MUST NOT call raw external card-mark tools to update cards.

#### Scenario: end_turn completes the quest

- GIVEN an intento created by `begin_turn` for a quest with `done=false`
- WHEN `end_turn` is called
- THEN the quest `done` value becomes `true`
- AND the associated intento is finalized
- AND the quest state change happens only through `end_turn`

#### Scenario: No other tool transitions a quest

- GIVEN the full MCP tool surface
- WHEN the registered tools are enumerated
- THEN no tool other than `end_turn` sets a quest `done` value to `true`

#### Scenario: Raw external mark call is eliminated

- GIVEN the turn workflow
- WHEN a turn completes
- THEN no raw external Nextcloud item-mark call is issued
- AND all quest state changes are performed by `end_turn`

### Requirement: end_turn Remains a Wrapper

`end_turn` MUST preserve its current behavior and MUST additionally perform quest management behind the scenes. The change MUST NOT introduce new bottleneck tools that callers are required to invoke in sequence to complete a turn.

#### Scenario: Existing behavior preserved

- GIVEN a completed turn with a result
- WHEN `end_turn` is called
- THEN the pre-existing end-of-turn behavior still runs
- AND the response is returned successfully

#### Scenario: No new bottleneck tool

- GIVEN the turn workflow
- WHEN a turn is completed
- THEN no additional tool call beyond `end_turn` is required to manage the quest
- AND the quest transition is handled inside `end_turn`
