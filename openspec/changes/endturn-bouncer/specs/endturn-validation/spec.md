# endturn-validation Specification

## Purpose
Server-side validation gate para `complete_intento()` que verifica el estado real de las gates en SQLite antes de permitir la completación de un intento.

## Requirements

### Requirement: Mandatory gates must be PASS/SKIP to complete

When `session_id` and `project` are provided, the system MUST query `list_gate_states(session_id, project)` and reject completion if any mandatory gate is in BLOCK or WARN state.

#### Scenario: All mandatory gates pass

- GIVEN `session_id` and `project` are provided
- AND all mandatory gates are PASS or SKIP in `gate_state`
- WHEN `complete_intento()` is called
- THEN the intento is completed successfully
- AND response contains `"status": "ok"`

#### Scenario: One mandatory gate is BLOCK

- GIVEN `session_id` and `project` are provided
- AND one mandatory gate has state BLOCK
- WHEN `complete_intento()` is called
- THEN the intento is NOT completed
- AND response contains `"status": "blocked"`
- AND the error includes the gate name and state

#### Scenario: Multiple mandatory gates fail

- GIVEN `session_id` and `project` are provided
- AND multiple mandatory gates are in BLOCK or WARN
- WHEN `complete_intento()` is called
- THEN ALL failing gates are listed in the error response

#### Scenario: Optional gate is BLOCK

- GIVEN `session_id` and `project` are provided
- AND a non-mandatory gate is in BLOCK
- WHEN `complete_intento()` is called
- THEN the intento IS completed
- AND non-mandatory gates are ignored

#### Scenario: No session_id provided

- GIVEN `session_id` is empty string
- WHEN `complete_intento()` is called
- THEN no validation is performed
- AND behavior is identical to previous implementation

#### Scenario: No project provided

- GIVEN `project` is empty string
- WHEN `complete_intento()` is called
- THEN no validation is performed
- AND behavior is identical to previous implementation

#### Scenario: Empty gates result

- GIVEN `session_id` and `project` have no matching gates in the database
- WHEN `complete_intento()` is called
- THEN the intento is completed
- AND an empty gate list passes validation
