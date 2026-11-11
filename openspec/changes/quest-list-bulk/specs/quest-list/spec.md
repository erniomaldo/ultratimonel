# Delta for quest-list

## ADDED Requirements

### Requirement: Single-Call Mission Checklist Read

The server SHALL expose a read-only MCP tool `quest_list` that returns the
complete checklist of a mission in **one** invocation. The response MUST list
every quest as its `id`, `text`, and `done` state, in checklist order
(`item_index` ascending). `quest_list` MUST be a pure read from the local
replica: it MUST NOT contact Deck or Nextcloud, MUST NOT change the schema, and
MUST NOT mark any quest as completed. The tool MUST be registered with the same
`@app.tool()` pattern as the existing read tools.

**Tool input/output schemas:**

- `quest_list`
  - Input: `{ "mission_id": integer (required), "include_done": boolean (optional, default true) }`
  - Output (found):
    ```json
    {
      "mission_id": 12,
      "quests": [
        { "id": 101, "text": "Primer paso", "done": false },
        { "id": 102, "text": "Segundo paso", "done": true }
      ],
      "total": 2
    }
    ```
  - `done` MUST be a JSON boolean. `total` is the number of quests returned
    (after filtering).
  - Output (not found): `{ "error": "Mission <mission_id> not found" }`

#### Scenario: Full checklist in one call

- GIVEN a mission with three quests, two pending and one done
- WHEN `quest_list(mission_id)` is called once
- THEN the response contains all three quests as `{id, text, done}`
- AND the quests appear in checklist order
- AND each `done` value is a JSON boolean

#### Scenario: include_done true includes completed quests

- GIVEN a mission whose checklist mixes pending and done quests
- WHEN `quest_list(mission_id, include_done=true)` (or the default) is called
- THEN every quest is returned, including the ones already done

#### Scenario: include_done false omits completed quests

- GIVEN a mission whose checklist mixes pending and done quests
- WHEN `quest_list(mission_id, include_done=false)` is called
- THEN only the pending quests are returned
- AND the completed quests are absent from the response

#### Scenario: Unknown mission fails without mutation

- GIVEN no mission exists for the supplied `mission_id`
- WHEN `quest_list` is called
- THEN the response is `{"error": "Mission <mission_id> not found"}`
- AND no quest state is written and no Deck card is touched

#### Scenario: Registered in the tool catalog

- GIVEN the server tool catalog
- WHEN the registered tools are enumerated
- THEN `quest_list` is present

#### Scenario: Read-only — never completes a quest

- GIVEN a mission with pending quests
- WHEN `quest_list` is called
- THEN no quest `done` flag changes
- AND the only path to `done=true` remains `end_turn`
