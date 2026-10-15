# Delta for dashboard-authorize

> NEW capability. Base main spec does NOT exist yet: `cards-solo-ultratimonel` is verified but not archived, so all requirements are declared ADDED (no invented base).
>
> **Sequencing (M4)**: if `cards-solo-ultratimonel` archives first, its base spec becomes the baseline and this delta's ADDED-vs-MODIFIED split must be re-checked before apply. Requirement IDs `DASH1–DASH5` stay stable regardless.
>
> **Surface**: these are HTTP endpoints served by the human-facing dashboard (`dashboard_server.py`, ADR-5). They are **not** MCP tools and MUST NOT be part of the agent-facing tool catalog (DASH2). Cross-references: design **D10**, TCE2 (attempt budget), TT4 (telemetry reads), D3/TT1 (summary fallback).

## ADDED Requirements

### Requirement DASH1: Authorize Attempts Endpoint (budget grant)

`POST /api/checklist/{item_id}/authorize_attempts` SHALL accept a JSON body `{amount, granted_by}`, insert one row into `attempt_grants`, and bump `checklist_items.attempts_authorized` — thereby **arming** the quest's budget per TCE2. Grant insertion and the counter bump MUST happen in a **single transaction**: the endpoint MUST NEVER persist a grant row without the matching bump, nor a bump without its grant row.

**Input validation (all rejected without mutation):**

- `amount` MUST be an integer strictly greater than `0`. `0` and negative values are rejected.
- `item_id` MUST reference an existing quest/checklist item. An unknown `item_id` is rejected.
- `granted_by` MUST be a non-empty, non-whitespace string.
- The body MUST be valid JSON containing both fields.

**`{item_id}` naming**: it is the quest id (canonical `quest_id`; see design I1 mapping).

**Success response**: HTTP `200` with JSON `{item_id, amount, granted_by, attempts_authorized, attempts_used}` reflecting the post-grant budget.

#### Scenario: Valid grant inserts the ledger row and arms the budget

- GIVEN an existing quest with `attempts_authorized=0` (legacy/unbounded)
- WHEN `POST /api/checklist/{item_id}/authorize_attempts` is called with `{amount: 3, granted_by: "human"}`
- THEN one `attempt_grants` row is inserted
- AND `attempts_authorized` becomes `3` (the budget is armed for TCE2)
- AND the response reports the updated `attempts_authorized`/`attempts_used`

#### Scenario: amount of zero or negative is rejected

- GIVEN an existing quest
- WHEN the endpoint is called with `amount: 0` or a negative `amount`
- THEN the request is rejected with an explicit validation error
- AND no grant row is inserted and `attempts_authorized` is unchanged

#### Scenario: unknown item_id is rejected

- GIVEN no quest exists for the given id
- WHEN the endpoint is called with that `item_id`
- THEN the request is rejected as not-found
- AND no grant row is inserted and no budget is mutated

#### Scenario: empty granted_by is rejected

- GIVEN an existing quest
- WHEN the endpoint is called with an empty or whitespace-only `granted_by`
- THEN the request is rejected with an explicit validation error
- AND no grant row is inserted and no budget is mutated

#### Scenario: Grant and bump are atomic

- GIVEN the database becomes unavailable while the endpoint runs
- WHEN the grant transaction cannot complete
- THEN neither the `attempt_grants` row nor the `attempts_authorized` bump is persisted (no partial state, DASH5)

### Requirement DASH2: Authorize Is Human-Gated and Off the Agent Surface

The authorize capability SHALL be reachable **only** through the human-facing dashboard HTTP endpoint (DASH1). It MUST NOT be exposed as an MCP tool and MUST NOT be reachable through the agent-facing tool catalog. **No operation on the agent surface may increment `attempts_authorized`** — if an agent could self-grant budget, TCE2's attempt budget would be void.

#### Scenario: The agent tool catalog contains no grant operation

- GIVEN the agent-facing tool catalog
- WHEN it is enumerated
- THEN no tool performs an authorize/grant of attempt budget
- AND no tool increments `attempts_authorized`

#### Scenario: Budget can only be armed through the dashboard endpoint

- GIVEN a quest with no grants
- WHEN any agent-surface operation runs (including `begin_turn`/`end_turn` and any `deck_*`/sync tool)
- THEN `attempts_authorized` stays `0` (legacy/unbounded) or unchanged
- AND the first `attempts_authorized > 0` transition happens only via DASH1

### Requirement DASH3: Explicit Dashboard Reads

The dashboard SHALL expose read endpoints, all of which are explicit reads (the turn cycle never requires them, per TT4):

- `GET /api/missions/{id}` — extended with `attempts_authorized` and `attempts_used`.
- `GET /api/checklist/{item_id}/intentos` — extended with `summary`, `evidence`, and `closed_at`.
- `GET /api/bitacora?mission_id=` — **new**; returns the mission's `turn_bitacora` rows.

The bitácora endpoint is the explicit human-requested telemetry read named by TT4; no `begin_turn`/`end_turn` cycle depends on it.

#### Scenario: Mission detail exposes the attempt budget

- GIVEN a mission with quests carrying attempt counters
- WHEN `GET /api/missions/{id}` is called
- THEN each quest includes `attempts_authorized` and `attempts_used`

#### Scenario: Intento detail exposes summary, evidence and closure

- GIVEN a finalized intento
- WHEN `GET /api/checklist/{item_id}/intentos` is called
- THEN the intento includes `summary`, `evidence`, and `closed_at`

#### Scenario: Bitácora is served only on explicit request

- GIVEN a mission with appended bitácora rows
- WHEN `GET /api/bitacora?mission_id=` is called
- THEN the mission's rows are returned
- AND no normal `begin_turn → end_turn` cycle requires this call

### Requirement DASH4: `intentos.evidence` JSON Schema

`intentos.evidence` SHALL store a JSON object (TEXT column, design D2/D3). Its **minimal shape** is `{"summary_source": "caller" | "auto"}`; `summary_source` is required once the intento is finalized:

- `"auto"` when the server persisted the deterministic fallback summary of TT1/D3.
- `"caller"` when a caller-supplied summary was stored.

The object MAY carry additional reader-specific keys; readers MUST ignore unknown keys (forward-compatible). `evidence` MUST be valid JSON (or absent until `end_turn` writes it).

#### Scenario: Auto fallback marks the source

- GIVEN `end_turn` is called with an empty summary
- WHEN the server persists the fallback `auto:<final_status> gates=<p>/<t>`
- THEN `evidence.summary_source` is `"auto"`

#### Scenario: Caller summary marks the source

- GIVEN `end_turn` is called with a caller-supplied summary
- WHEN the server persists that summary
- THEN `evidence.summary_source` is `"caller"`

#### Scenario: Unknown evidence keys are tolerated

- GIVEN an `evidence` object with extra keys beyond `summary_source`
- WHEN a reader parses it
- THEN the reader ignores the unknown keys and still resolves `summary_source`

### Requirement DASH5: Dashboard Failure Modes Are Explicit and Non-Partial

When a required dependency (SQLite DB or the Deck bridge) is unavailable, dashboard endpoints SHALL fail with an explicit error and MUST NOT persist partial state. The **fail-closed** contract already established for Deck-first writes (MQM3) applies to these endpoints too.

#### Scenario: Dependency failure yields an explicit error, no partial write

- GIVEN the DB (or Deck, for a read/write that needs it) is unavailable
- WHEN a dashboard endpoint is called
- THEN the call fails with an explicit error
- AND no partial mutation is left behind (DASH1 grant/bump atomicity included)
