# Delta for deck-sync

## ADDED Requirements

### Requirement: sync_task Recovers One Mission

The server SHALL expose `sync_task`, which recovers exactly one mission by its local `mission_id`, resolves the Deck `deck_task_id` internally, and refreshes that mission's fields and quests. `sync_task` MUST be explicitly invoked and MUST NOT sync any other mission.

**Tool input/output schema:**

- Input: `{ "mission_id": integer (required) }`
- Output: `{ "mission_id": integer, "deck_task_id": integer, "status": string, "quests_synced": integer }`

#### Scenario: Recover a single mission

- GIVEN a mission identified by a local `mission_id` that was altered in Deck
- WHEN `sync_task` is called with that `mission_id`
- THEN the mission fields and quests are refreshed from Deck
- AND the response reports the resolved `deck_task_id`
- AND no other mission is refreshed

#### Scenario: Unknown local mission id

- GIVEN no mission exists for the supplied `mission_id`
- WHEN `sync_task` is called
- THEN the call fails with a not-found error
- AND no replica rows are modified

### Requirement: sync_tasks Is Retained

The server SHALL retain the existing `sync_tasks` tool with its current contract.

#### Scenario: sync_tasks remains available

- GIVEN the MCP tool surface
- WHEN `sync_tasks` is invoked
- THEN it performs its existing bulk sync behavior
- AND it is not removed or deprecated

### Requirement: sync_all Is Deprecated but Registered

The server SHALL keep `sync_all` registered and invocable while marking it `~~DEPRECATED~~`. `sync_all` MUST NOT be removed from the tool surface.

#### Scenario: sync_all is deprecated and retained

- GIVEN the MCP tool surface
- WHEN `sync_all` is invoked
- THEN it still executes
- AND its description contains the `~~DEPRECATED~~` marker
- AND the tool remains registered

#### Scenario: Deprecation points to sync_task

- GIVEN the deprecation of `sync_all`
- WHEN a caller inspects the tool surface
- THEN `sync_task` is available as the explicit single-mission recovery path
