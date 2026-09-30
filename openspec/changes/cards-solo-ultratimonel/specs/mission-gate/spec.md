# Delta for mission-gate

## MODIFIED Requirements

### Requirement: Server MCP Tool Surface

The server SHALL expose its existing gate and mapping tools: `assert_gates`, `check_gate`, `complete_gate`, `server`, `map_list`, `map_add`, `map_remove`, `map_setup`, and `map_sync`. The server SHALL additionally register the deterministic mission and quest tools `mission_create`, `mission_update_title`, `mission_update_description`, `quest_add`, and `quest_update`, plus `sync_task`, and SHALL retain `sync_tasks`. `sync_all` SHALL remain registered and invocable with a `~~DEPRECATED~~` marker in its description; it MUST NOT be removed.
(Previously: the surface exposed only gate and mapping tools, with no deterministic mission/quest write tools and no documented sync-tool lifecycle.)

#### Scenario: Existing gate tools still work

- GIVEN a message and session context
- WHEN `assert_gates` is called
- THEN the configured gates are evaluated
- AND the response contains the per-gate results
- AND the overall status reflects the gate states

#### Scenario: New deterministic tools are registered

- GIVEN the MCP tool surface
- WHEN the registered tools are enumerated
- THEN `mission_create`, `mission_update_title`, `mission_update_description`, `quest_add`, and `quest_update` are present
- AND `sync_task` and `sync_tasks` are present

#### Scenario: sync_all is deprecated but registered

- GIVEN the MCP tool surface
- WHEN `sync_all` is inspected
- THEN its description contains the `~~DEPRECATED~~` marker
- AND it remains registered and invocable

#### Scenario: Completing a non-existent gate fails

- GIVEN a gate name that does not exist in configuration
- WHEN `complete_gate` is called with that name
- THEN the call returns a gate-not-found error
- AND no gate state changes
