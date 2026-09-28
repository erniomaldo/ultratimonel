# Design: cards-solo-ultratimonel

## Technical Approach

Nextcloud Deck stays the ONE source of truth. This change adds a deterministic,
turn-aware **write surface** to ultratimonel and routes it through a new internal
**Deck write bridge** (`ultratimonel/deck_bridge.py`) built on the existing
`mcp_client.call_mcp_tool("nextcloud", …)` stdio path already proven by
`card_update_description`. Local SQLite is written only *after* a Deck write is
acknowledged, never before and never alone.

Verified facts that drive the design (read from the live surface, not guessed):

- The Nextcloud MCP (v1.27.0) exposes `deck_get_card`, `deck_create_card`,
- `deck_create_stack`, `deck_update_card`, `deck_get_stacks`, … but **no
  checklist/checklist-item tool**. Confirmed by `tools/list` against the live
  endpoint.
- The mission card `#189` (board `21`, stack `111`) stores its quest list as
  **markdown checkbox lines inside the card `description`** (`- [ ] …` /
  `- [x] …`). There is no separate `checklistItems` field.
- `sync_tasks` already parses exactly this markdown-checkbox format
  (`server.py:929-948`), so the replica model does not change.

Consequences: a **quest is a markdown checkbox line in the Deck card
description**; `checklist_items` is its SQLite replica. All new tools write Deck
first, then refresh the replica.

## Module Dependency Diagram

```
main.py
  └─> ultratimonel/server.py  (FastMCP "ultratimonel", all @app.tool registrations)
        ├─> persistence.py        (SQLite replica; schema v5)
        ├─> gate_engine.py        (gate config/classification)
        ├─> triple_match.py       (1a→1b→1c→1e execution)
        │     └─> mcp_client.py   (stdio MCP client)
        ├─> context_extractor.py  (project_maps lookups: board_id)
        ├─> compact.py            (NEW; pure output serializers)
        └─> deck_bridge.py        (NEW; internal Deck write bridge)
              ├─> mcp_client.py   (call_mcp_tool("nextcloud", …))
              └─> persistence.py  (mission_id → deck_task_id resolution)

mcp_client.py ──spawns──> http_to_stdio bridge ──HTTP──> Nextcloud MCP ──> Deck
```

`bridge.py` is **not** modified. It is a stub for mcp-capabilities-server
*dynamic discovery* (`bridge.py:14-31`), an unrelated concern; repurposing it
for Deck writes would be a category error (see D1).

## MCP Tool Registration Flow

```
server.py module load
  app = FastMCP("ultratimonel")            # server.py:56
  @app.tool()                              # decorator captures fn name + type hints
  def <tool_name>(...) -> str: ...         # FastMCP builds inputSchema from hints
        ↓
  connection handshake (initialize / notifications/initialized)
        ↓
  Hermes tools/list  → FastMCP enumerates every @app.tool() function
  Hermes tools/call  → FastMCP dispatches by name
```

Every new tool (`mission_create`, `mission_update_title`,
`mission_update_description`, `quest_add`, `quest_update`, `sync_task`,
`sync_all` marker) is added the same way: a module-level function decorated with
`@app.tool()`, returning a JSON string. No manual registration list exists, so
"registered" == "decorated in `server.py`". The deprecation marker is purely
docstring-level, matching `assert_gates` (`server.py:1419`).

## Architecture Decisions

### D1: Internal Deck write bridge = new `deck_bridge.py` over the existing `mcp_client` path

| Option | Tradeoff | Decision |
|--------|----------|----------|
| (a) Extend the existing `mcp_client` Deck path used by `card_update_description`, wrapped in a new `deck_bridge.py` | Reuses the proven stdio client + persistent subprocess cache; one clean home for high-level Deck semantics; `server.py` stays thin | **Chosen** |
| (b) Implement `bridge.py::register_capabilities()` as the Deck bridge | `bridge.py` is a capability-*discovery* stub for mcp-capabilities-server, not a Deck client; would conflate two concerns and still need `mcp_client` underneath | Rejected |
| (c) Local-DB-only writes, sync to Deck later | Violates the ONE-source-of-truth principle and the `deck-sync`/`mission-quest-management` specs | Rejected |

**Choice**: new `deck_bridge.py` exposing high-level operations that call
`mcp_client.call_mcp_tool("nextcloud", <deck_* tool>, …)`.

**Rationale**: the Deck write precedent already exists and works
(`card_update_description`, `server.py:1558-1640`). Putting the new semantics in
one module keeps `server.py` focused on MCP surface, makes the bridge
unit-testable, and avoids touching `bridge.py`'s unrelated discovery contract.
The bridge is the only module allowed to compose/decompose the card description.

### D2: Quest representation in Deck = markdown checkbox lines in the card description

**Choice**: `checklist_items` rows mirror `- [ ] <text>` / `- [x] <text>` lines
inside the Deck card `description`. `done` = `[x]`. No new Deck entity.

**Alternatives considered**: a dedicated Deck checklist MCP tool (does not exist
in v1.27.0), one Deck card per quest (breaks mission↔card mapping and the
`deck_task_id UNIQUE` model), storing quests in a separate SQLite-only table
(violates source-of-truth).

**Rationale**: it is the only representation Deck actually accepts through the
available write tool (`deck_update_card.description`), and the existing
`sync_tasks` parser already reads it.

### D3: `mission_update_description` never touches quests

**Choice**: `deck_bridge.update_description` reads the current card, extracts
every checkbox line in its original order (`extract_quests`), strips checkbox
lines from the incoming prose (rejecting input that tries to introduce one), and
writes the updated prose with the preserved quest block re-appended in its
original relative order. Quest lines stay byte-identical before and after.
**Policy (PM, resolved)**: preserve original order; do NOT normalize quests under
a `## Quests` region — normalizing would mutate proven behavior and is explicitly
future work, out of scope for this change.

**Alternatives considered**: full-description replace (would silently delete
quests), storing prose separately in SQLite (prose would no longer live in Deck,
breaking source-of-truth), normalizing all checkboxes under a `## Quests` region
(rejected by the PM as mutation of proven behavior; deferred as future work).

**Rationale**: satisfies the spec scenario "no quest is added, removed, or
modified" while keeping prose canonical in Deck. Quest operations
(`quest_add`/`quest_update`) do *surgical* line edits and never touch prose.

### D4: Compact output by default via a pure `compact.py`

**Choice**: new `ultratimonel/compact.py` with pure serializers
(`compact_gate`, `compact_gates`, `compact_mission`, `compact_quest`).
`end_turn` returns compact gates (no `result_data` — the ~91 KB culprit, since
`list_gate_states` carries each gate's `result_data`, including full Deck card
descriptions via gate 1e). `mission_list` defaults to `include_description=False`.
No global `verbose` flag.

**Alternatives considered**: a global `verbose` parameter (explicitly out of
scope by the spec), stripping fields ad-hoc in each tool (duplication, drift).

**Rationale**: one testable seam, consistent shapes, default-safe payloads. The
existing per-tool `include_description` optional in `mission_list` is kept as an
opt-in (it is not a global toggle), so the spec's "no global verbose" holds.

### D5: `begin_turn` guards the quest before any mutation

**Choice**: `begin_turn` resolves the quest first (step 0, before orphan cleanup
and before gate execution) and, when `done == 1`, returns
`{"error": …, "code": "quest_done", "quest_id": …}` with **no** intento and **no**
gate-state write. `quest_id` becomes the canonical 4th parameter (positionally
compatible with today's `checklist_item_id`), with `checklist_item_id` kept as a
trailing alias.
**Signature (PM, resolved)**: `session_id` and `project` remain required existing
inputs (the proven interface); `mission_id`/`quest_id`/`work_description` are the
new/changed fields. The 4 internal gates keep running inside `begin_turn`.

**Alternatives considered**: validate after gate execution (would mutate
`gate_state` — violates "MUST NOT mutate any state"), validate inside
`create_intento` (too late, intento exists).

**Rationale**: the spec requires a hard fail with zero state mutation, so the
guard must precede every side effect. Renaming the 4th positional parameter keeps
`SOUL.md`'s positional call and existing tests working.

### D6: `end_turn` is the wrapper and the only `false→true` path

**Choice**: `end_turn` keeps its current flow (resolve intento, validate gates,
complete intento) and adds, behind the scenes: flip the intento's quest in Deck
(`- [ ]` → `- [x]`), then refresh the replica (`done=1`), then return compact
output. No new bottleneck tool is added.
**Policy (PM, resolved)**: the transition is **unconditional** — the quest always
becomes `done=true` when the turn closes. The success/fail result lives on the
intento; retry is done with a NEW quest (PM model: "take the next quest or add a
new one").

**Alternatives considered**: a separate `complete_quest` tool (explicitly
forbidden — "no new bottleneck tools", "no mark-complete tool"), transitioning
only on `final_status == "success"` (rejected by the PM: gate warnings are now
best-effort and turn-success is decoupled from quest state).

**Rationale**: the spec makes `end_turn` the single state channel; pairing the
transition with the turn close keeps callers at the 2-call workflow, and the
unconditional rule keeps "one turn = one quest consumed" deterministic.

### D7: `sync_task` (singular) + `sync_tasks` retained + `sync_all` deprecated-but-registered

**Choice**: add `sync_task(mission_id)` resolving `deck_task_id` internally,
refreshing only that mission's fields + quests. Keep `sync_tasks(project)`
as-is. Add the `~~DEPRECATED~~` marker to `sync_all`'s docstring and keep it
registered. Requires an additive `missions.deck_stack_id` column (D9) to write
the card without an extra stack lookup.

**Alternatives considered**: remove `sync_all` (spec forbids), `sync_task` by
`deck_task_id` (spec mandates local `mission_id`), resolve `stack_id` at write
time via `deck_get_stacks` (extra round-trip; kept as fallback).

**Rationale**: explicit single-mission recovery is what the PM asked for; the
deprecation follows the existing mark pattern so no caller contract breaks.

### D8: Gates 1a/1b become best-effort; 1c/1e untouched

**Choice**: add `best_effort: bool` to `GateConfig`/`GateResult`; set it on 1a
(`agentmemory`) and 1b (`agentcheckpoint`) and set their `mandatory=False`.
`aggregate` ignores `WARN`/`BLOCK` from `best_effort` gates; `end_turn`
computes `final_status` from **mandatory** gates only (replacing the hardcoded
`gates_passed >= 4`). `_call_agentmemory`/`_call_checkpoint` keep returning
`WARN` on failure — they are simply excluded from the aggregate. 1c and 1e
configuration and behavior are unchanged.

**Alternatives considered**: change 1a/1b failure states to `SKIP` (also works,
but the spec scenario says "GIVEN gate 1a returns WARN … overall PASS", so WARN
must be tolerated), make `aggregate` ignore all non-mandatory WARN (would change
1c, which is `mandatory=False` today and whose WARN currently yields overall
WARN — a regression).

**Rationale**: an explicit `best_effort` flag isolates the change to exactly the
two gates the spec demotes, preserving the "1c/1e behavior unchanged" scenario.

### D9: Additive, reversible SQLite change (NF-GP-05)

**Choice**: bump `SCHEMA_VERSION` 4 → 5; add `_migrate_v4_to_v5` issuing only
`ALTER TABLE missions ADD COLUMN deck_stack_id INTEGER` (nullable). Fresh-DB DDL
includes the column. No destructive DDL, no data rewrite.

**Alternatives considered**: no schema change (forces a stack lookup per write),
a new table (overkill).

**Rationale**: additive column; older server code ignores an unknown version and
still works (fails safe, no downgrade), satisfying the `SCHEMA_AHEAD` contract in
`gate-persistence`.

### D10: Unify terminology to `done` / `quest`

**Choice**: keep the SQLite column name `done` (already correct); introduce
`quest` as the public term for a `checklist_items` row and `quest_id` as the
public id. No entity is added.

**Alternatives considered**: rename the column (destructive DDL — forbidden),
keep "checked" in the public API (inconsistent with the PM decision).

**Rationale**: the storage already uses `done`; only the public surface needs
the vocabulary alignment.

## Data Flow

Write tool (e.g. `mission_update_title`):

```
Hermes ──> server.mission_update_title(mission_id, title)
             │
             ├─> persistence.get_mission(mission_id) ──> deck_task_id, project, deck_stack_id
             │       (not found → {"error": "not found"}; NO Deck call)
             │
             ├─> deck_bridge.update_title(board_id, stack_id, card_id, title)
             │       │  read card (desk_get_card) → preserve description + quests
             │       └─> mcp_client.call_mcp_tool("nextcloud","deck_update_card", …)
             │               └─> http_to_stdio ──> Nextcloud MCP ──> Deck  [SOURCE OF TRUTH]
             │       (bridge error → {"error": "bridge unavailable"}; NO local write)
             │
             ├─> persistence.upsert_mission(... title=new ...)   # replica refresh
             └─> compact JSON {mission_id, title, status}
```

`end_turn` (only `false→true` path):

```
Hermes ──> server.end_turn(intento_id)
             ├─ resolve intento ──> session, project, mission_id, quest_id
             ├─ capture gate states (with result_data, internal only)
             ├─ final_status = fail  IFF any MANDATORY gate ∉ {PASS,SKIP}   # best-effort 1a/1b ignored
             ├─ deck_bridge.complete_quest(board_id, stack_id, card_id, quest)   # '- [ ]' → '- [x]'
             ├─ persistence.upsert_checklist_item(done=1)   # replica refresh
             ├─ persistence.complete_intento_with_gates(...)
             └─ compact JSON {status, intento_id, final_status, gates:[{name,state,mandatory}], quest_id, quest_done}
                (NO result_data → bounded payload)
```

`sync_task` (singular recovery):

```
Hermes ──> server.sync_task(mission_id)
             ├─ persistence.get_mission(mission_id) ──> deck_task_id, project, deck_stack_id
             ├─ mcp_client nextcloud.deck_get_card(board_id, stack_id, deck_task_id)
             ├─ parse description → title, prose, quests   (reuse sync_tasks parser logic)
             ├─ persistence.upsert_mission(...) + upsert_checklist_item(each quest)
             └─ {mission_id, deck_task_id, status, quests_synced}
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `ultratimonel/deck_bridge.py` | Create | Internal Deck write bridge: `create_card`, `update_title`, `update_description`, `append_quest`, `update_quest`, `complete_quest`, `extract_quests`; all via `mcp_client`. |
| `ultratimonel/compact.py` | Create | Pure compact serializers: gates (no `result_data`), missions, quests. |
| `ultratimonel/server.py` | Modify | Add `mission_create`, `mission_update_title`, `mission_update_description`, `quest_add`, `quest_update`, `sync_task`; `begin_turn` quest guard; `end_turn` quest transition + compact; `mission_list` compact default; `sync_all` `~~DEPRECATED~~` marker. |
| `ultratimonel/persistence.py` | Modify | `SCHEMA_VERSION` 4→5; `_migrate_v4_to_v5`; `missions.deck_stack_id` column; `set_quest_done`/`get_mission_by_deck_task` helpers. |
| `ultratimonel/gate_engine.py` | Modify | `best_effort` on `GateConfig`/`GateResult`; 1a/1b `mandatory=False, best_effort=True`; `aggregate` ignores best-effort WARN/BLOCK. |
| `ultratimonel/mcp_client.py` | Modify | Add `deck_create_card`, `deck_create_stack` to `TOOL_NAMES["nextcloud"]`. |
| `ultratimonel/bridge.py` | Not modified | Deliberately untouched — see D1 (capability-discovery stub, unrelated). |
| `tests/test_deck_bridge.py` | Create | Bridge parsing/composition + Deck-first ordering. |
| `tests/test_compact.py` | Create | Serializer shapes drop `result_data`. |
| `tests/test_server.py` | Modify | New tools, `begin_turn` guard, `end_turn` compact/transition, `sync_all` marker. |
| `tests/test_gate_engine.py` | Modify | Best-effort aggregate behavior. |
| `tests/test_triple_match.py` | Modify | 1a/1b WARN non-blocking; 1c/1e unchanged. |
| `tests/test_persistence.py` | Modify | v4→v5 migration + `deck_stack_id`. |

## Interfaces / Contracts

```python
# ── New MCP tools (server.py, all -> JSON str) ──────────────────────────────
mission_create(project: str, title: str, description: str = "") -> str
    # -> {"mission_id", "deck_task_id", "title", "status"}; no quests
mission_update_title(mission_id: int, title: str) -> str
    # -> {"mission_id", "title", "status"}; not found -> {"error"}
mission_update_description(mission_id: int, description: str) -> str
    # -> {"mission_id", "status"}; quests byte-identical (D3)
quest_add(mission_id: int, title: str) -> str
    # -> {"quest_id", "mission_id", "title", "done": false}
quest_update(quest_id: int, title: str | None = None, position: int | None = None) -> str
    # -> {"quest_id", "title", "done": false}
sync_task(mission_id: int) -> str
    # -> {"mission_id", "deck_task_id", "status", "quests_synced"}

# begin_turn (4th positional = quest_id, backward compatible)
begin_turn(session_id, project, mission_id=0, quest_id=0, message="", sender="user",
           checklist_item_id=0) -> str
    # done=true -> {"error", "code": "quest_done", "quest_id"}   (no mutation)
    # missing    -> {"error", "code": "missing_quest"}

# ── deck_bridge.py (internal; all return (value, error|None)) ────────────────
create_card(board_id, stack_id, title, description) -> (card_id, err)
update_title(board_id, stack_id, card_id, title) -> (ok, err)
update_description(board_id, stack_id, card_id, prose) -> (ok, err)   # preserves quests
append_quest(board_id, stack_id, card_id, text) -> (position, err)
update_quest(board_id, stack_id, card_id, position, text) -> (ok, err)
complete_quest(board_id, stack_id, card_id, position) -> (ok, err)    # '[ ]' -> '[x]'
extract_quests(description) -> list[{"line_no", "done", "text"}]      # regex over '- [ ]'/'[x]'

# ── compact.py shapes (default outputs) ─────────────────────────────────────
compact_gate(g)   -> {"name", "state", "mandatory"}          # drops message/result_data/duration
compact_gates(gs) -> [compact_gate(g), ...]
compact_mission(m)-> {"id", "title", "status"}               # drops description/checklist_items
compact_quest(q)  -> {"id", "text", "done"}

# ── gate_engine classification ───────────────────────────────────────────────
@dataclass GateConfig:  name, mandatory=True, best_effort=False, timeout_s=2.0, source=""
@dataclass GateResult:  name, state=BLOCK, mandatory=True, best_effort=False, ...
# DEFAULT_GATES: 1a,1b -> mandatory=False, best_effort=True ; 1c,1e unchanged
```

Status vocabulary: mission `status` stays `pendiente|en_progreso|completada|bloqueada`;
quest state is `done: bool`; gate states stay `PASS|SKIP|WARN|BLOCK`.

## Testing Strategy

| Layer | What to Test | Approach |
|-------|-------------|----------|
| Unit | `extract_quests`, description preservation, `compact_*` drop `result_data`, best-effort `aggregate` | `pytest`; pure functions, no I/O |
| Unit | `deck_bridge` Deck-first ordering and bridge-unavailable failure | monkeypatch `mcp_client.call_mcp_tool`; assert no `persistence` write on error |
| Integration | New tools end-to-end with mocked `mcp_client` + real temp SQLite | `.venv/bin/pytest tests/test_server.py`; assert Deck called before replica upsert |
| Integration | `begin_turn` guard (done → no intento, no gate write); `end_turn` transitions quest + compact payload; `sync_task` refreshes one mission only | temp DB fixtures |
| Integration | v4→v5 migration adds `deck_stack_id` without data loss | reopen DB, `PRAGMA table_info(missions)` |
| Regression | 1a/1b WARN no longer forces `end_turn` fail; 1c/1e behavior unchanged | `tests/test_triple_match.py`, `tests/test_gate_engine.py` |
| E2E | Not available (`openspec/config.yaml`: e2e `available: false`) | Manual smoke against Deck when bridge env is configured |

`strict_tdd: false`; still add tests before/with implementation per work-unit.

## Migration / Rollout

Additive and reversible:

1. **SQLite**: v4→v5 adds nullable `missions.deck_stack_id`. Existing rows stay
   `NULL` until the next sync; writes fall back to a `deck_get_stacks` stack
   lookup when `deck_stack_id` is `NULL`. No destructive DDL (NF-GP-05).
2. **MCP surface**: purely additive tools; `sync_tasks` untouched; `sync_all`
   kept and only docstring-marked. No caller contract removed.
3. **Replica backfill**: no bulk migration; `sync_tasks`/`sync_task` populate
   `deck_stack_id` lazily. Quest representation is unchanged (same markdown
   checkboxes `sync_tasks` already parses), so no card reformatting.
4. **Cutover**: Hermes is pointed at the ultratimonel tools; raw Nextcloud card
   tools are pruned in Hermes config (out of repo scope).
5. **Rollback**: `git revert` removes the new tools and restores the prior MCP
   surface; `sync_all` is never removed, so no caller to undo; Deck data is
   never modified by rollback; the extra SQLite column is inert to older code.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Deck write bridge (`deck_bridge.py`) is new surface, apply-blocking | High | Design pins the exact path (D1) over the proven `mcp_client`; block apply until `deck_bridge.py` + tests land; no local-only fallback |
| Quest write has no first-class Deck primitive | High | Canonical model is markdown checkboxes in the description (verified on card #189); bridge owns parse/compose; never reformats via `mission_update_description` (D3) |
| `mission_update_description` placement policy for pre-existing interspersed checkboxes | Med | Resolved (D3): preserve original order and re-append the preserved block byte-identical; normalizing is deferred future work, out of scope |
| Deck ↔ replica drift | Med | Deck-first then replica refresh in every write; explicit `sync_task` recovery; no deferred sync |
| `begin_turn` hard-fail leaves a stuck turn | Med | Guard runs before side effects; clear `code`; orchestrator picks the next open quest |
| `deck_stack_id` stale after a card moves stack | Low | Refreshed on every sync; fallback lookup resolves it when `NULL`/stale |
| Best-effort change accidentally alters 1c/1e | Low | Explicit `best_effort` flag on 1a/1b only; regression tests assert 1c/1e unchanged |
| Hidden behavior change beyond additive scope | Med | No source-of-truth move; `bridge.py` untouched; stop-and-report if scope pushes beyond it |

## Open Questions

**None.** All three questions raised during design were resolved by the PM on
2026-09-27 and folded into the decisions below.

- **RESOLVED — D3 (quest placement in `mission_update_description`)**: preserve
  original order; checkbox lines stay byte-identical. Normalizing under a
  `## Quests` region is rejected (it would mutate proven behavior) and deferred
  as future work, explicitly out of scope for this change.
- **RESOLVED — D6 (`end_turn` on a failed turn)**: unconditional — the quest
  always becomes `done=true` when the turn closes; success/fail stays on the
  intento and retry uses a new quest.
- **RESOLVED — D5 (`begin_turn` signature)**: `session_id`/`project` remain
  required existing inputs; `mission_id`/`quest_id`/`work_description` are the
  new/changed fields; the gates keep running internally.
