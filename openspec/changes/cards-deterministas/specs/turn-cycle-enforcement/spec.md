# Delta for turn-cycle-enforcement

> NEW capability. Base main spec does NOT exist yet: `cards-solo-ultratimonel` is verified but not archived, so all requirements are declared ADDED (no invented base).

## ADDED Requirements

### Requirement: Single State Channel and Order Validation

The cycle `begin_turn → work → end_turn` SHALL be the only state channel. State-mutating work MUST NOT occur before `begin_turn` or after `end_turn`.

#### Scenario: Work before begin_turn is rejected

- GIVEN no active turn
- WHEN a state-mutating tool is called before `begin_turn`
- THEN the call is rejected with a clear error
- AND no state is mutated

#### Scenario: Duplicate begin_turn is rejected

- GIVEN an active turn already started in the same response
- WHEN a second `begin_turn` is issued
- THEN the second call is rejected
- AND the original turn remains active

#### Scenario: State tool after end_turn is rejected

- GIVEN `end_turn` just closed the turn
- WHEN another state-mutating tool is called before the next `begin_turn`
- THEN the call is rejected until a new turn starts

### Requirement: Attempt Budget

Each quest SHALL have a bounded attempt budget. When the budget is exhausted, further attempts MUST fail hard with a clear error and MUST NOT mutate state.

#### Scenario: Attempt within budget is allowed

- GIVEN a quest whose attempts used is below the budget
- WHEN `begin_turn` is called
- THEN the attempt is created

#### Scenario: Exhausted budget blocks hard

- GIVEN a quest whose attempts used equals the budget
- WHEN a new attempt is requested
- THEN the call fails with a budget-exhausted error
- AND no intento is created and no state is mutated

#### Scenario: Budget resets for a new quest or turn

- GIVEN a quest with an exhausted budget
- WHEN a different quest (or a reset turn) starts
- THEN the attempt counter starts from zero

### Requirement: Closure Ownership

`end_turn` SHALL be the only operation that closes a quest (`done` false→true) and finalizes the intento. Closure MUST be unconditional to the turn result; the success/fail verdict MUST be recorded on the intento, not on the quest.

#### Scenario: end_turn closes the quest

- GIVEN a turn bound to a quest with `done=false`
- WHEN `end_turn` is called
- THEN the quest `done` becomes `true`
- AND the intento is finalized with its own verdict

#### Scenario: No other tool closes a quest

- GIVEN the full agent-facing tool catalog
- WHEN it is enumerated
- THEN no tool other than `end_turn` sets a quest `done` to `true`

### Requirement: Binding Validation

`begin_turn` SHALL bind the intento to `{session_id, project, mission_id, quest_id}`. `end_turn` MUST reject an intento whose binding does not match the active turn, and MUST recover an orphaned `running` intento as `fail`.

#### Scenario: Matching binding closes the turn

- GIVEN an active intento whose binding matches the request
- WHEN `end_turn` is called
- THEN the turn closes normally

#### Scenario: Mismatched binding is rejected

- GIVEN an intento whose binding does not match the active turn
- WHEN `end_turn` targets it
- THEN the call is rejected with a binding-mismatch error

#### Scenario: Orphaned running intento is recovered

- GIVEN a `running` intento with no matching active turn
- WHEN a new turn starts
- THEN the orphan is completed as `fail`
- AND the system remains recoverable
