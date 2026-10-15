# Delta for turn-telemetry

> NEW capability. Base main spec does NOT exist yet: `cards-solo-ultratimonel` is verified but not archived, so all requirements are declared ADDED (no invented base).
>
> **Sequencing (M4)**: if `cards-solo-ultratimonel` archives first, its base spec becomes the baseline and this delta's ADDED-vs-MODIFIED split must be re-checked before apply. Requirement IDs `TT1–TT4` stay stable regardless.

## ADDED Requirements

### Requirement TT1: Internal Turn Telemetry Persistence

`begin_turn` SHALL persist a checkpoint record internally. `end_turn` SHALL persist a checkpoint record and append one entry to the append-only turn log (bitácora). The agent MUST NOT be required to invoke `mcp__agentmemory__*` or `mcp__checkpoint__*` to produce this telemetry.

**Contract (internal sub-steps, not agent tools):**

- `begin_turn` sub-step: checkpoint `{session_id, project, mission_id, quest_id}`.
- `end_turn` sub-step: checkpoint + one bitácora entry `{intento_id, final_status, gates_passed, timestamp}`.

**Summary fallback (design D3):** `end_turn(intento_id, summary="")` persists the caller-supplied summary when present, otherwise a deterministic fallback `auto:<final_status> gates=<p>/<t>` (`<p>`/`<t>` = gates passed/total). It records `evidence.summary_source="caller"` or `"auto"` accordingly (evidence schema: DASH4). `closed_at` is always set. This makes the summary mandatory at storage while keeping the proven 2-call signature compatible.

#### Scenario: begin_turn writes an internal checkpoint

- GIVEN a valid quest
- WHEN `begin_turn` is called
- THEN a checkpoint record is persisted internally
- AND no agent-facing telemetry write tool is invoked

#### Scenario: end_turn appends the bitácora entry

- GIVEN a turn bound to an intento
- WHEN `end_turn` closes the turn
- THEN a checkpoint record and one append-only bitácora entry are persisted internally

#### Scenario: No agent-facing telemetry write tool exists

- GIVEN the agent-facing tool catalog
- WHEN it is enumerated
- THEN no tool writes telemetry on behalf of the agent
- AND telemetry exists only as internal sub-steps of the turn calls

#### Scenario: Empty summary gets the deterministic auto fallback

- GIVEN an `end_turn` call with an empty summary
- WHEN the intento is persisted
- THEN its summary is `auto:<final_status> gates=<p>/<t>`
- AND `evidence.summary_source` is `"auto"`
- AND `closed_at` is set

#### Scenario: Caller summary is preserved

- GIVEN an `end_turn` call with a caller-supplied summary
- WHEN the intento is persisted
- THEN that summary is stored unchanged
- AND `evidence.summary_source` is `"caller"`

### Requirement TT2: Append-only Bitácora Integrity

The bitácora SHALL be append-only. The system MUST NOT update or delete previously written entries.

#### Scenario: Append preserves prior entries

- GIVEN an existing bitácora with N entries
- WHEN a new turn appends an entry
- THEN the previous N entries remain unchanged
- AND the new entry is appended at the end

### Requirement TT3: Best-effort Checkpoint/Memory Mirror (NOT the bitácora)

Only the **external checkpoint/memory mirror** is best-effort. When a checkpoint or memory-mirror write fails, the turn MUST still complete and that failure MUST NOT force the turn status to `fail`.

The **append-only bitácora write is explicitly out of scope of this requirement**: per design **D4/D8** it is part of the single closure transaction, together with marking the item done and completing the intento. This requirement does NOT authorize swallowing a bitácora failure.

**Transactional append failure mode (design D4):** if the `turn_bitacora` INSERT fails inside the closure transaction, the whole transaction rolls back — the checklist item is NOT marked done, the intento is NOT finalized, and `end_turn` returns a retryable error with the turn left open. There is never a closed item without its matching bitácora row (reconciles TT3 with D4; closes the "audit gap" risk).

#### Scenario: Checkpoint/memory-mirror failure does not block the turn

- GIVEN a turn reaching `end_turn` whose closure transaction has already committed
- WHEN the checkpoint/memory-mirror write raises an error
- THEN `end_turn` still returns success
- AND the failure is recorded as a non-blocking warning

#### Scenario: Bitácora append failure rolls back the closure (atomic, D4)

- GIVEN a turn reaching `end_turn`
- WHEN the `turn_bitácora` INSERT inside the closure transaction raises an error
- THEN the transaction rolls back: the item is NOT marked done and the intento is NOT finalized
- AND `end_turn` returns a retryable error with the turn still open
- AND no closed item is left without a matching bitácora row

### Requirement TT4: Telemetry Reads Are Explicit Only

Reading telemetry MUST NOT be required for the turn cycle. The agent MAY read telemetry only when the human explicitly requests it.

#### Scenario: Normal turn requires no telemetry read

- GIVEN a normal `begin_turn → work → end_turn` cycle
- WHEN the cycle runs
- THEN no telemetry read is required

#### Scenario: Human-requested read

- GIVEN an idle system
- WHEN the human explicitly asks for the bitácora or checkpoint history
- THEN the read is available on demand
