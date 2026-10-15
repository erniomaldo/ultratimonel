# Proposal: cards-deterministas

## Why

Hermes sibling agents STILL route all card work through `mcp__nextcloud__deck_*`,
and call `mcp__agentmemory__*` / `mcp__checkpoint__*` manually and compulsively.
PM decision: all of that MUST be resolved **internally between `begin_turn` and
`end_turn`**, without saturating the existing tools.

**Nextcloud (Deck) remains the ONE source of truth.** Write path stays **Deck-first
through the internal bridge** — the proven model is NOT altered. This change is
additive: it changes the agent-facing channel and telemetry, not the data origin.

> Guardrail: if any analysis pushes toward "ultratimonel as source of truth" or
> altering the Deck→sync model — **STOP and report**.

## What Changes

### Requirement traceability (1:1)

| # | Requirement | Change in this proposal |
|---|-------------|-------------------------|
| 1 | Cards ONLY via ultratimonel tools | Agents MUST NOT use `mcp__nextcloud__deck_*`. Remove `card_update_description` from the agent catalog; card editing becomes an internal step of `begin_turn`/`end_turn`. Deck stays source of truth, Deck-first via bridge (unchanged). |
| 2 | INTERNAL cycle telemetry | `begin_turn`/`end_turn` persist checkpoint + memory/append-only log (bitácora) **internally**. The agent MUST NOT call `mcp__agentmemory__*` / `mcp__checkpoint__*` to **write** (reads only on explicit human request). |
| 3 | Cycle enforcement | `begin_turn → work → end_turn` is the ONLY state channel: order validation, attempt budget, closure and binding enforced server-side. |

### Requirement sources (resolves I2 citations)

- Change-level requirements **1–3** above are defined by this proposal.
- Spec requirement tags (`TT1–TT4`, `TCE1–TCE4`, `TSP1–TSP3`, `MQM1–MQM4`) are defined in the four `specs/**/spec.md` deltas.
- Card-level requirements cited in `tasks.md` as `[Req N]` are **Card Deck #2389** requirement strings, tracked in PR #31 (the tracker). They are not restated here, to avoid drift (M5).

### In Scope
- Card editing internalized as a turn step; `card_update_description` out of the agent catalog.
- Append-only telemetry (checkpoint + bitácora) written inside `begin_turn`/`end_turn`.
- Server-side enforcement: order validation, attempt budget, closure, binding.

### Out of Scope
- Moving data origin off Deck; altering the proven Deck→sync model.
- **`enforcement v3`** (persistent attempt counter / fail-all post-grace) — own change.
- Redesigning working gates; new entities; destructive schema changes.

## Capabilities

### New Capabilities
- `turn-telemetry`: internal, append-only telemetry (checkpoint + bitácora) persisted inside `begin_turn`/`end_turn`; no agent-facing write tools.
- `turn-cycle-enforcement`: order validation, attempt budget, closure and binding for the `begin_turn → work → end_turn` cycle.
- `dashboard-authorize`: human-gated dashboard HTTP endpoints — attempt-budget authorize (arms TCE2) and explicit reads (missions attempts, intento summary/evidence, bitácora); **not** on the agent tool surface.

### Modified Capabilities
> Base definitions come from `cards-solo-ultratimonel` (pending archive).
- `mission-quest-management`: card/quest editing becomes a turn step; `card_update_description` leaves the agent catalog.
- `turn-state-protocol`: `begin_turn`/`end_turn` become the only state channel, with internal telemetry and budget sub-steps.

## Impact

| Area | Impact | Description |
|------|--------|-------------|
| `ultratimonel/server.py` | Modified | `begin_turn`/`end_turn` internalize card edit + telemetry + enforcement; tool surface loses `card_update_description` |
| `ultratimonel/plugin_preflight.py` | Modified | Drop `card_update_description` guidance (L166); block raw `deck_*` card usage |
| `ultratimonel/deck_bridge.py` | Reused (dep) | Deck-first writes through the proven bridge; not altered |
| `ultratimonel/persistence.py` | Modified | Append-only bitácora table + attempt-budget counters; additive DDL only (NF-GP-05) |
| `openspec/changes/plugin-preflight-sync/specs/plugin-preflight/spec.md` | Modified | Req-6 message no longer points to `card_update_description` |
| `README.md` / `README.en.md` | Modified | Tool table updated to the new agent surface |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Removing `card_update_description` breaks existing Hermes callers | Med | Keep it internal (callable by turn tools); update catalog + plugin message |
| Telemetry write failing blocks the turn | Med | Best-effort, non-blocking (aligns with `cards-solo-ultratimonel` Req 6) |
| Attempt budget too strict → stuck turns | Med | Configurable bound + clear error; orchestrator picks next quest |
| Overlap with `cards-solo-ultratimonel` / `enforcement-v3` | Med | Explicit supersede/defer notes above; no duplicate scope |
| Deck ↔ SQLite replica drift | Med | Deck-first via bridge; `sync_task` recovery |

## Rollback Plan

- Git-revert the change commit: surface and turn logic are additive, so reverting restores the prior MCP catalog.
- `card_update_description` remains in code (only leaves the catalog), so no caller contract is lost.
- No destructive DDL; any migration is additive (NF-GP-05) and reverts safely. There is **no `SCHEMA_AHEAD` symbol** (verified: it is only *named* at `persistence.py:195` as the gate-persistence spec contract). The real mechanism: older code tolerates the unknown `schema_version` row, and re-running the additive `ALTER TABLE … ADD COLUMN` is idempotent because `_migrate_v4_to_v5` (`persistence.py:190-199`) swallows the `sqlite3.OperationalError` on an existing column. Proven by the S1 downgrade test (task 1.4).
- Deck is never mutated by rollback; data stays canonical.

## Dependencies

- `cards-solo-ultratimonel` (pending archive) — base capability definitions for `mission-quest-management` and `turn-state-protocol`.
- `ultratimonel/deck_bridge.py` internal Deck write bridge (proven precedent).
- `enforcement-v3` deferred to its own change.

## Confirmed Decisions (PM)

- Escalate this as change `cards-deterministas` (Card Deck #2389): editing as a `begin_turn`/`end_turn` step + attempt budget + bitácora.
- Deck remains the ONE source of truth; write path is Deck-first via the internal bridge (unchanged).
- Telemetry is internal and append-only; agents stop writing to `agentmemory`/`checkpoint` manually.
- `enforcement v3` and any data-origin change stay out of this change.
- **PR strategy (preflight #3)**: `chained-pr` — **Feature Branch Chain** with tracker
  `feature_2389_cards-deterministas` and 5 child PRs ≤400 changed lines each.
  No `size:exception`. This decision does not alter the scope above.

## Success Criteria

Each criterion states its measurement, so the review can be answered point by point.

- [ ] Agents issue **zero** `mcp__nextcloud__deck_*` card calls and **zero** manual `agentmemory`/`checkpoint` writes. **Measured by**: `plugin_preflight` block counters for `deck_*` card ops = 0 allowed over the soak window, plus a log grep for raw calls = 0.
- [ ] `card_update_description` absent from the agent catalog. **Measured by**: `tools/list` enumeration test asserting the tool is absent and still importable internally (`test_server.py`).
- [ ] `begin_turn`/`end_turn` persist checkpoint + append-only bitácora internally. **Measured by**: integration test asserting one `turn_bitacora` row per closed turn and prior rows unchanged (TT1/TT2).
- [ ] Order, attempt budget, closure and binding validations enforced server-side. **Measured by**: hard-fail tests (no mutation) for order/binding/budget plus the success-vs-fail closure tests (TCE1–TCE4).
- [ ] Deck remains the source of truth; rollback restores the prior surface without data loss. **Measured by**: the S1 downgrade test (open the v6 DB with v5 code, pre-existing data intact) and a green full suite after `git revert`.
