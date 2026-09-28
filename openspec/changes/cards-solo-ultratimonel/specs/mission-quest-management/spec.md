# Delta for mission-quest-management

## ADDED Requirements

### Requirement: Deterministic Mission Write Tools

The server SHALL expose deterministic mission write tools that operate on Deck-backed missions: `mission_create`, `mission_update_title`, and `mission_update_description`. Each tool MUST validate its inputs and MUST return a compact result containing mission identifiers, title, and state.

**Tool input/output schemas:**

- `mission_create`
  - Input: `{ "project": string (required), "title": string (required), "description": string (optional) }`
  - Output: `{ "mission_id": integer, "deck_task_id": integer, "title": string, "status": string }`
- `mission_update_title`
  - Input: `{ "mission_id": integer (required), "title": string (required) }`
  - Output: `{ "mission_id": integer, "title": string, "status": string }`
- `mission_update_description`
  - Input: `{ "mission_id": integer (required), "description": string (required) }`
  - Output: `{ "mission_id": integer, "status": string }`

`mission_update_description` MUST NOT modify the mission checklist or any quest.

#### Scenario: Create a mission

- GIVEN a valid project and title
- WHEN `mission_create` is called
- THEN a mission is created
- AND the response contains a `mission_id`, the resolved `deck_task_id`, the `title`, and a `status`
- AND the new mission has no quests

#### Scenario: Update a mission title

- GIVEN an existing mission identified by `mission_id`
- WHEN `mission_update_title` is called with a new title
- THEN the mission title is updated
- AND the response reflects the new `title`

#### Scenario: Update description does not touch the checklist

- GIVEN a mission with existing quests
- WHEN `mission_update_description` is called
- THEN the mission description is updated
- AND no quest is added, removed, or modified

#### Scenario: Reject an unknown mission

- GIVEN no mission exists for the supplied `mission_id`
- WHEN `mission_update_title` or `mission_update_description` is called
- THEN the call fails with a not-found error
- AND no Deck card is modified

### Requirement: Deterministic Quest Write Tools and No Mark-Complete Tool

The server SHALL expose deterministic quest write tools `quest_add` and `quest_update` operating on `checklist_items` rows. The server MUST NOT expose any tool that marks a quest completed. Both `quest_add` and `quest_update` MUST set `done=false`.

**Tool input/output schemas:**

- `quest_add`
  - Input: `{ "mission_id": integer (required), "title": string (required) }`
  - Output: `{ "quest_id": integer, "mission_id": integer, "title": string, "done": boolean }`
- `quest_update`
  - Input: `{ "quest_id": integer (required), "title": string (optional), "position": integer (optional) }`
  - Output: `{ "quest_id": integer, "title": string, "done": boolean }`

#### Scenario: Add a quest sets done false

- GIVEN an existing mission
- WHEN `quest_add` is called with a title
- THEN a new quest row is created
- AND the returned `done` value is `false`

#### Scenario: Update a quest resets done false

- GIVEN an existing quest whose `done` value is `true`
- WHEN `quest_update` is called
- THEN the quest fields are updated
- AND the returned `done` value is `false`

#### Scenario: No mark-complete tool exists

- GIVEN the full MCP tool surface
- WHEN the registered tools are enumerated
- THEN no tool exists that sets a quest `done` value to `true`
- AND the only path to `done=true` is `end_turn`

### Requirement: Deck Is the Source of Truth via the Internal Bridge

All mission and quest write tools MUST write against Nextcloud Deck (the source of truth) through the internal bridge. Local SQLite MUST be treated as a replica. The server MUST NOT perform local-only writes and MUST NOT defer Deck writes to a later sync.

#### Scenario: Write path targets Deck first

- GIVEN a valid mission write request
- WHEN a write tool is invoked
- THEN the change is applied to Deck through the internal bridge before the local replica is refreshed
- AND the response is returned only after the Deck write is acknowledged

#### Scenario: Bridge unavailable causes failure

- GIVEN the internal Deck bridge is unavailable
- WHEN a write tool is invoked
- THEN the call fails with an explicit bridge-unavailable error
- AND no local-only write is persisted
