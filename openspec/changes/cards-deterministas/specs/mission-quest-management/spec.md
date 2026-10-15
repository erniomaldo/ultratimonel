# Delta for mission-quest-management

> Base main spec does NOT exist yet: `cards-solo-ultratimonel` is verified but not archived, so all requirements are declared ADDED (no invented base). This change supersedes nothing from the sibling change; it extends it.
>
> **Sequencing (M4)**: if `cards-solo-ultratimonel` archives first, its base spec becomes the baseline and this delta's ADDED-vs-MODIFIED split must be re-checked before apply. Requirement IDs `MQM1–MQM4` stay stable regardless.

## ADDED Requirements

### Requirement MQM1: Card and Quest Editing Is a Turn Step

Card and quest editing SHALL be performed as an internal step of `begin_turn`/`end_turn`. Agents MUST NOT call `mcp__nextcloud__deck_*` for card operations; that channel is not part of the supported agent surface.

#### Scenario: Agent edits a card through the turn

- GIVEN an active turn bound to a quest
- WHEN the agent requests a card edit
- THEN the edit is applied as an internal turn step
- AND Deck is updated first through the internal bridge

#### Scenario: Raw Nextcloud deck tool is not used

- GIVEN the agent workflow
- WHEN a card operation is needed
- THEN no `mcp__nextcloud__deck_*` call is issued
- AND all card state changes flow through the turn tools

### Requirement MQM2: card_update_description Leaves the Agent Catalog

`card_update_description` SHALL NOT be exposed in the agent-facing catalog. It MUST remain callable internally as a turn sub-step and MUST NOT be deleted from the code.

#### Scenario: Tool absent from the agent catalog

- GIVEN the agent-facing tool catalog
- WHEN it is enumerated
- THEN `card_update_description` is absent

#### Scenario: Tool still available internally

- GIVEN an internal turn step that edits a card description
- WHEN the sub-step runs
- THEN `card_update_description` is callable internally

### Requirement MQM3: Deck-first Writes via the Internal Bridge

All card and quest writes MUST target Deck (the source of truth) first through the internal bridge, then refresh the local SQLite replica. The system MUST NOT perform local-only writes and MUST NOT defer Deck writes to a later sync.

#### Scenario: Write targets Deck first

- GIVEN a valid card or quest write request
- WHEN the write runs
- THEN Deck is updated through the internal bridge before the replica is refreshed
- AND the response is returned only after the Deck write is acknowledged

#### Scenario: Bridge unavailable causes explicit failure

- GIVEN the internal Deck bridge is unavailable
- WHEN a card or quest write runs
- THEN the call fails with a bridge-unavailable error
- AND no local-only write is persisted

### Requirement MQM4: Card Edit Preserves Title

A card description edit MUST NOT change the card title.

Server-owned titles follow design **D7**: the write boundary renders the Deck title as `#{id} {title}` after stripping any caller-supplied `#…` prefix. A description-only edit therefore strips and re-renders the `#{id}` prefix from the server model but leaves the human title text (`title`) untouched.

#### Scenario: Description edit keeps the title

- GIVEN a card with an existing title
- WHEN only its description is edited
- THEN the description is updated
- AND the title is unchanged

#### Scenario: Description-only edit strips then re-renders the id prefix (MQM4 × D7)

- GIVEN a Deck card whose title is `#42 Fix parser`
- WHEN only the description is edited through the internal bridge
- THEN the title is re-rendered as `#{id} {title}` (stripping any caller `#…`) from the stored title text
- AND the title remains `#42 Fix parser`
