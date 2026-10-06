# Design: cards-deterministas

## Context

Card #2389 (mission #2389): deterministic card management — card editing as a
`begin_turn`/`end_turn` step, attempt budget, and an append-only log (bitácora).

Verified facts driving this design (read from the live code, not guessed):

- Schema is `SCHEMA_VERSION = 5` (`persistence.py:42`). `intentos` has **no**
  `summary`/`evidence`/`closed_at`; `checklist_items` has **no**
  `attempts_authorized`/`attempts_used`; there is **no** `attempt_grants` and
  **no** `turn_bitacora` table.
- `begin_turn` (`server.py:1737`) already runs: quest guard (done/missing) →
  orphan cleanup → 4 gates → `create_intento`. Binding is the in-memory
  `_active_intento` + `_resolve_requesting_intento`; there is **no** attempt budget.
- `end_turn` (`server.py:2050`) completes the intento and closes the quest in
  Deck via `_complete_quest_for_intento`; it does **not** require a summary and
  does **not** append a turn log.
- `card_update_description` (`server.py:2372`) is an `@app.tool()`; it is the
  last raw Deck write on the agent surface and is pointed to by
  `plugin_preflight.py:166`.
- Titles are **not** server-owned: any caller can write an arbitrary title.
- The canonical dashboard is the Astro build (`dashboard-astro/dist/`, ADR-5);
  legacy `dashboard/` serves only staging ports (`dashboard_server.py:6-11`).
- `deck_bridge.py` already provides `update_description`, `complete_quest`,
  `extract_quests` etc. — the internal Deck write path is proven.

## Goals / Non-Goals

**Goals**: internalize card editing as a turn step; drop `card_update_description`
from the agent catalog; internal append-only telemetry; enforce order, attempt
budget, closure and binding; server-owned `#{id} {title}`; dashboard authorize +
summaries + bitácora.

**Non-Goals**: moving the data origin off Deck; altering the Deck→sync model;
`enforcement v3`; redesigning gates; destructive schema changes.

## Architecture Decisions

### D1: Attempt budget = per-quest counters + an append-only `attempt_grants` ledger

| Option | Tradeoff | Decision |
|--------|----------|----------|
| Per-quest counters on `checklist_items` + `attempt_grants` ledger | O(1) budget reads at `begin_turn`; grants are auditable and drive the UI/bitácora | **Chosen** |
| Counters on `missions` | Budget is a per-quest concept; mission-level blurs the model | Rejected |
| Ledger only (derive counters by SUM) | Every `begin_turn` pays an aggregate query; race-prone | Rejected |

**Choice**: `checklist_items.attempts_authorized`, `checklist_items.attempts_used`
(integers, default 0); `attempt_grants` rows record each authorization.
**Rationale**: spec TCE2 needs a bounded, per-quest budget read cheaply at
`begin_turn`; the ledger gives the dashboard an audit trail and the bitácora its
"who authorized what, when".

### D2: `intentos` gains `summary`, `evidence`, `closed_at` (additive)

**Choice**: additive columns `summary TEXT`, `evidence TEXT` (JSON), `closed_at TEXT`.
**Alternatives**: a separate `intento_details` table (extra join for every read;
overkill), reusing `gates_detail` for summary (conflates concerns).
**Rationale**: req 1 of #2389 names these columns explicitly; additive DDL is
reversible (NF-GP-05).

### D3 (decision point): `end_turn` summary is mandatory at storage, optional at the call

| Option | Tradeoff | Decision |
|--------|----------|----------|
| `end_turn(intento_id, summary: str = "")` with a deterministic auto-fallback when empty | Keeps the proven 2-call signature; every intento still ends with a non-null summary | **Chosen** |
| New required `summary` parameter | Breaks existing callers (`SOUL.md`, plugin, tests) — violates "additive, don't break the cycle" | Rejected |
| Reject `end_turn` when summary is empty | Hard-blocks the current turn cycle; turns can deadlock | Rejected |

**Choice**: `summary` is an optional new parameter. When empty, the server
persists a deterministic fallback `auto:<final_status> gates=<p>/<t>` and marks
`evidence.summary_source="auto"`; a caller-supplied summary sets
`summary_source="caller"`. `closed_at` is always set.
**Rationale**: makes the summary mandatory at the persistence layer (req 3)
without breaking any existing caller — the exact compatibility requirement the
contract calls out.

### D4: `end_turn` closure is atomic; external telemetry stays best-effort

**Choice**: append the `turn_bitacora` row **and** mark the item done **and**
complete the intento in a **single SQLite transaction**. Only the external
checkpoint/memory mirror (spec TT3) is best-effort and non-blocking.
**Alternatives**: separate best-effort writes for closure+log (partial state:
closed item with no log entry — rejected), two-phase with compensation (overkill).
**Rationale**: reconciles spec TT3 (telemetry failures must not force a fail)
with the contract's "atomic write (append-only bitácora + mark item)" — the
*bitácora* is authoritative and transactional; the *checkpoint mirror* is not.

### D5: `begin_turn` enforces order, binding and budget in one guard chain

**Choice**: after the existing quest guard, run, in order: (a) order validation —
reject if a turn is already active for another intento without recovery; (b)
binding — resolve/validate `{session_id, project, mission_id, quest_id}` against
`_active_intento`; (c) budget — fail hard with `code="attempt_budget_exhausted"`
when `attempts_used >= attempts_authorized`; then increment `attempts_used` and
create the intento. Budget exhaustion mutates nothing.
**Alternatives**: budget check inside `create_intento` (too late), budget on the
plugin only (server must be the second lock — `endturn-bouncer` precedent).
**Rationale**: specs TCE1/TCE2/TCE4 and TSP1 require a server-side, no-mutation
hard fail.

### D6: Card editing is internalized; `card_update_description` leaves the catalog

**Choice**: turn steps and `deck_bridge` own the description write; remove the
`@app.tool()` decorator from `card_update_description` but **keep the function**
as an internal helper/alias (spec MQM2: not deleted from code). `plugin_preflight`
blocks `mcp__nextcloud__deck_*` card operations and its L166 message is dropped.
**Alternatives**: delete the function (contradicts the PM's confirmed assumption),
leave it registered and rely on instructions (the incident shows instructions fail).
**Rationale**: FastMCP exposes exactly the `@app.tool()` functions, so removing
the decorator is the precise "leave the agent catalog" mechanism; internal callers
import the function directly.

### D7: Server-owned title with fixed format `#{id} {title}`

**Choice**: `deck_bridge` renders the Deck title as `f"#{mission_id} {title}"`
on every create/update, after stripping any caller-supplied `#…` prefix.
**Alternatives**: store the rendered title in SQLite (duplication, drift), block
all title edits (the contract implies edits remain possible).
**Rationale**: req 5 — the numeric prefix must be unforgeable by the agent; render
at the write boundary so Deck is always canonical.

### D8: `turn_bitacora` is append-only

**Choice**: table `turn_bitacora(id, intento_id, session_id, project, mission_id,
checklist_item_id, final_status, gates_passed, summary, created_at)`; only INSERTs,
no UPDATE/DELETE exposed. Spec TT2.
**Alternatives**: reuse `intentos` rows as the log (loses the append-only invariant
and mixes live/mutable state with the immutable log).
**Rationale**: append-only integrity is a named requirement; a dedicated table
keeps it clean and cheap to read for the dashboard.

### D9: Additive schema migration v5→v6

**Choice**: bump `SCHEMA_VERSION` 5→6; `_migrate_v5_to_v6` issues only
`ALTER TABLE … ADD COLUMN …` (idempotent, `OperationalError` swallowed) plus
`CREATE TABLE IF NOT EXISTS attempt_grants / turn_bitacora`. Fresh-DB DDL mirrors it.
**Alternatives**: destructive rewrite (forbidden), no schema change (impossible —
the columns are required).
**Rationale**: additive and reversible; older code ignoring v6 fails safe
(`SCHEMA_AHEAD`, gate-persistence).

### D10: Dashboard = API endpoints in `dashboard_server.py` + Astro UI

**Choice**: add `POST /api/checklist/{item_id}/authorize_attempts` (body
`{amount, granted_by}` → insert grant + bump `attempts_authorized`); extend
`GET /api/missions/{id}` with attempts; extend `GET /api/checklist/{item_id}/intentos`
with `summary`/`evidence`/`closed_at`; new `GET /api/bitacora?mission_id=`. UI:
"Authorize attempts" button on `ChecklistCard.jsx`, summary on `IntentoCard.jsx`,
new bitácora view; legacy `dashboard/app.js` parity for staging.
**Alternatives**: server-render the button (the Astro build is `output: 'static'`,
so actions must be client-side fetches), Astro-only (leaves staging broken).
**Rationale**: matches the existing client-fetch pattern (`useApi.js`) and ADR-5's
canonical Astro root.

## Data Flow

```
begin_turn:  guard(quest) → order → binding → budget(check+increment) →
             checkpoint(best-effort) → gates → create_intento
end_turn:    resolve intento → binding validate → gate verdict →
             [TXN] mark item in Deck + upsert replica + append turn_bitacora +
                   complete intento(summary,evidence,closed_at) →
             checkpoint mirror (best-effort) → compact response
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `ultratimonel/persistence.py` | Modify | v5→v6 migration; `attempt_*` columns; `intentos.summary/evidence/closed_at`; `attempt_grants`, `turn_bitacora`; grant + budget + bitácora methods |
| `ultratimonel/server.py` | Modify | `begin_turn` order/binding/budget; `end_turn` summary + atomic closure + bitácora; card edit internalized; `card_update_description` loses `@app.tool()`; server-owned title |
| `ultratimonel/deck_bridge.py` | Modify | server-owned `#{id} {title}` rendering; expose internal description-edit used by turn steps |
| `ultratimonel/plugin_preflight.py` | Modify | block `mcp__nextcloud__deck_*` card ops; drop L166 guidance |
| `ultratimonel/dashboard_server.py` | Modify | authorize-attempts POST; summary/evidence on intentos; bitácora GET |
| `ultratimonel/dashboard-astro/src/components/ChecklistCard.jsx` | Modify | "Authorize attempts" button |
| `ultratimonel/dashboard-astro/src/components/IntentoCard.jsx` | Modify | show `summary`/`evidence`/`closed_at` |
| `ultratimonel/dashboard-astro/src/pages/…` + `hooks/useApi.js` | Modify | bitácora view + new API clients |
| `ultratimonel/dashboard/app.js`, `index.html` | Modify | staging parity |
| `tests/test_persistence.py`, `test_server.py`, `test_dashboard*.py`, `test_deck_bridge.py` | Modify/Create | migration, budget, atomicity, title, UI API |

## Interfaces / Contracts

```sql
-- v5 → v6 (additive)
ALTER TABLE checklist_items ADD COLUMN attempts_authorized INTEGER NOT NULL DEFAULT 0;
ALTER TABLE checklist_items ADD COLUMN attempts_used       INTEGER NOT NULL DEFAULT 0;
ALTER TABLE intentos        ADD COLUMN summary  TEXT;
ALTER TABLE intentos        ADD COLUMN evidence TEXT;
ALTER TABLE intentos        ADD COLUMN closed_at TEXT;
CREATE TABLE IF NOT EXISTS attempt_grants (
  id INTEGER PRIMARY KEY AUTOINCREMENT, mission_id INTEGER NOT NULL,
  checklist_item_id INTEGER NOT NULL, amount INTEGER NOT NULL,
  granted_by TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS turn_bitacora (
  id INTEGER PRIMARY KEY AUTOINCREMENT, intento_id INTEGER NOT NULL,
  session_id TEXT NOT NULL, project TEXT NOT NULL, mission_id INTEGER NOT NULL,
  checklist_item_id INTEGER NOT NULL, final_status TEXT NOT NULL,
  gates_passed INTEGER NOT NULL, summary TEXT, created_at TEXT NOT NULL DEFAULT (datetime('now')));
```

```python
begin_turn(session_id, project, mission_id=0, quest_id=0, message="", sender="user",
           checklist_item_id=0) -> str
    # order/binding fail → {"error","code":"turn_order"|"binding_mismatch"}
    # budget exhausted  → {"error","code":"attempt_budget_exhausted","quest_id"}
end_turn(intento_id: int, summary: str = "") -> str      # summary compat: D3
authorize_attempts(quest_id: int, amount: int, granted_by: str) -> str   # internal/API
```

## Testing Strategy

| Layer | What | Approach |
|-------|------|----------|
| Unit | migration v5→v6 idempotency; budget check; title rendering; summary fallback | `pytest`, temp DB, pure helpers |
| Integration | `begin_turn` budget/order/binding hard fail (no mutation); `end_turn` atomic closure + bitácora append; telemetry failure non-blocking | mocked `deck_bridge` + real temp SQLite |
| Regression | existing `begin_turn`/`end_turn` cycle still works with no `summary`; `card_update_description` absent from `tools/list`, present internally | `test_server.py` |
| API | authorize/budget/summary/bitácora endpoints | HTTP client against `dashboard_server` |
| E2E | Not available (`config.yaml`: e2e `available: false`) | manual smoke |

`strict_tdd: false`; add tests with each work unit.

## Migration Plan

1. **SQLite v5→v6**: additive columns + two new tables; idempotent; no data rewrite.
2. **Backfill**: existing quests start at `attempts_authorized=0`, `attempts_used=0`.
   To avoid instantly blocking live turns, `attempts_authorized=0` MUST be treated
   as "unbounded/legacy" until the first grant (documented) — a rollout guard.
3. **Surface**: `card_update_description` leaves the catalog (function kept);
   `plugin_preflight` blocks raw `deck_*`; Hermes catalog pruned (out of repo).
4. **Rollback**: `git revert` restores the surface; new columns/tables are inert
   to older code; Deck is never modified by rollback.

## Risks / Tradeoffs

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| `attempts_authorized=0` blocks live turns after cutover | High | Treat 0 as legacy-unbounded until a grant (rollout guard, step 2) |
| Atomic closure vs best-effort telemetry confusion | Med | D4 splits authoritative bitácora (transactional) from checkpoint mirror (best-effort) |
| Raw `deck_*` still used despite guidance | Med | Server-side plugin block, not just instructions |
| Title rendering double-prefix | Low | Strip caller `#…` before rendering; regression test |
| Astro static build vs interactive button | Med | Client-side POST to `dashboard_server` API (existing fetch pattern) |
| Scope creep into enforcement-v3 | Med | Explicitly out of scope; D5 covers only per-quest budget |

## Delivery Strategy

**chained-pr / feature-branch-chain** (PM decision, preflight #3). The design is
unchanged; only the delivery is re-segmented. The single-PR estimate
(~900–1300 lines) exceeds the 400-line review budget, so the work splits into a
tracker branch `feature_2389_cards-deterministas` plus 5 chained PRs
(S1 persistence → S2 turn-enforcement → S3 card-surface → S4 dashboard →
S5 docs), each ≤400 changed lines, reviewed against its immediate parent. No
`size:exception` is used. **The design decisions (D1–D10) remain valid and map
one-to-one onto these slices.**

## Open Questions

**None blocking.** The one explicit decision point (`end_turn` summary
compatibility) is resolved in **D3**: optional parameter + deterministic
auto-fallback summary, additive and non-breaking.
