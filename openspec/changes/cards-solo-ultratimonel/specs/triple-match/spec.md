# Delta for triple-match

## MODIFIED Requirements

### Requirement: Gate Orchestration and Best-Effort Classification

The triple match SHALL execute gates in sequence 1a -> 1b -> 1c -> 1e and compile their results into a single `context_envelope` containing memory snippets, checkpoint state, steering docs, and deck cards. Gate 1a (agentmemory) and Gate 1b (agentcheckpoint) SHALL leave the mandatory gate set and become best-effort. Failure or warning from 1a or 1b MUST NOT block turn success and MUST NOT force the `end_turn` final status to `fail`. Behavior of gates 1c and 1e and independent per-gate timeouts MUST be preserved.
(Previously: 1a and 1b were mandatory gates, and accumulated WARN states from them forced the `end_turn` final status to `fail`.)

#### Scenario: Full triple match succeeds

- GIVEN a message context with sender, topic, and project
- WHEN the triple match executes
- THEN gates 1a, 1b, 1c, and 1e return their context
- AND `context_envelope` contains all four data sets
- AND the overall status is `PASS`

#### Scenario: Best-effort gate warning does not block the turn

- GIVEN gate 1a returns `WARN`
- WHEN the triple match completes
- THEN the overall status remains `PASS`
- AND the turn succeeds
- AND the `end_turn` final status is not forced to `fail`

#### Scenario: Best-effort gate unavailable is non-blocking

- GIVEN gate 1b is unavailable
- WHEN the triple match completes
- THEN gate 1b is reported as best-effort without blocking
- AND later gates still execute
- AND the turn succeeds

#### Scenario: Existing failure isolation is preserved

- GIVEN gate 1a times out and gate 1e is unavailable
- WHEN the triple match completes
- THEN no gate failure prevents a subsequent gate from executing
- AND `context_envelope` contains the context produced by the gates that succeeded

#### Scenario: Non-best-effort behavior unchanged

- GIVEN gates 1c and 1e are configured as mandatory
- WHEN the triple match executes
- THEN their mandatory classification and failure handling are unchanged
