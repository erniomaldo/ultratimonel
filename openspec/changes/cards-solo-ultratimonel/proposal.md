# Proposal: cards-solo-ultratimonel

## Intent (Why)

**Nextcloud (Deck) remains the ONE source of truth.** This change is **ADDITIVE**: it changes only Hermes's **access channel** to cards — from raw Nextcloud MCP tools to deterministic, turn-aware ultratimonel tools. It does NOT move the data origin, and does NOT replace or redesign the proven `Deck → sync` model. Data originates in Deck; local SQLite is a replica.

Why now: Hermes has confused new functions with destroying proven behavior, and gate flakiness breaks turns (evidence 2026-09-27: gates 1c/1e flapped WARN/PASS "bridge Nextcloud interno: unavailable"; `end_turn` returned ~91 KB). The PM removes Hermes's raw Nextcloud card tools and channels mission/quest management exclusively through ultratimonel (local + turn-aware).

> Guardrail: if any analysis pushes toward "ultratimonel as source of truth" or altering the proven Deck→sync model — **STOP and report**.

## Scope (What Changes)

### Requirement traceability (1:1)

| # | Requirement | Change in this proposal |
|---|-------------|-------------------------|
| 1 | Mission tools MUST exist | **CREATE** 5 write tools: create mission, update title, update description (must NOT touch checklist), add quest, update quest. **NO** mark-quest-completed tool; add/update quest set `done=false`. Today ultratimonel has **no** mission/quest write tools — only read `mission_list`, `mission_get`, `checklist_item_get`. |
| 2 | Turns = only state channel | `begin_turn` MUST FAIL if the quest is `done=true`; `end_turn` is the ONLY `false→true` transition and the ONLY way to update item/quest state. Remove the extra raw-Nextcloud item-mark call Hermes does today. |
| 3 | Sync | Deprecate `sync_all` (kept registered, marked `~~DEPRECATED~~`, same pattern as `assert_gates`/`record_intento` — NOT removed). Keep `sync_tasks`. **NEW** `sync_task(mission_id)` recovers ONE mission by local `mission_id` (resolves Deck `deck_task_id` internally), explicitly invoked by Hermes, refreshes fields + quests. |
| 4 | `end_turn` wrapper | `end_turn` = what it does today **PLUS** behind-the-scenes quest management. No new bottleneck tools. |
| 5 | Compact outputs by default | Essential fields only (ids, titles, state), no raw `result_data`, for `end_turn`, `mission_list`, and read/list tools in general. No global `verbose` flag for now. |
| 6 | Audit `agentcheckpoint` + `agentmemory` | They leave the MANDATORY gate set (1a/1b) and become **best-effort**; their failure MUST NOT block turn success (removes today's accumulated-WARN ⇒ `end_turn` → `fail`). This proposal formalizes: keep best-effort now; full removal is deferred, not done here. |

### In Scope
- Deterministic mission/quest write tools writing to Deck via the internal bridge.
- Turn-scoped state transitions, `end_turn` wrapper, compact outputs, sync reshape, agent-gate demotion.

### Out of Scope
- Moving the data origin off Deck; "ultratimonel as source of truth"; altering the proven Deck→sync model.
- Redesigning working gates 1c/1e.
- Batch #179-#186 beyond the supersessions below; `bridge.py` implementation (design phase); global `verbose` flag; new entities or destructive schema changes.

## Capabilities

### New Capabilities
- `mission-quest-management`: deterministic mission + quest write surface (Req 1) writing to **Deck via the internal bridge**; SQLite as replica; no mark-complete tool.
- `turn-state-protocol`: turn-scoped state channel (Req 2, 4) — `begin_turn` hard-fail on done quest; `end_turn` wrapper is the only `false→true`.
- `deck-sync`: `sync_task` (singular) + retained `sync_tasks` + `sync_all` deprecation (Req 3).
- `compact-tool-outputs`: compact-by-default serialization contract (Req 5).

### Modified Capabilities
- `mission-gate`: new deterministic tools registered on the MCP surface; `sync_all` marked deprecated.
- `triple-match`: gates 1a (agentmemory) and 1b (agentcheckpoint) leave the mandatory gate set → best-effort, non-blocking (Req 6).

## Approach

- New write tools write **against Deck (source of truth) via ultratimonel's internal bridge**; local SQLite is a **replica** — no local-only writes, no relying on a later sync.
- `begin_turn` validates quest `done` before creating the intento and fails hard if done; `end_turn` wraps existing logic and performs the `false→true` transition behind the scenes.
- Reuse the existing deprecation convention (`~~DEPRECATED~~` docstring, tool kept registered).
- Compact serialization: emit only ids/titles/state; drop `result_data` from default responses.
- Agents 1a/1b degrade to WARN without affecting `end_turn` final status.

## Affected Areas (Impact)

| Area | Impact | Description |
|------|--------|-------------|
| `ultratimonel/server.py` | Modified | Add 5 write tools; `sync_task`; `end_turn` wrapper; `begin_turn` quest guard; compact outputs |
| `ultratimonel/bridge.py` | Modified (design dep) | `register_capabilities()` is a **STUB** (`bridge.py:22`) — new tools need a real internal Deck write bridge. Flagged as design risk; NOT designed here. |
| `ultratimonel/persistence.py` | Modified | Replica reads/writes; `done` terminology; additive DDL only (NF-GP-05) |
| `ultratimonel/gate_engine.py` | Modified | 1a/1b best-effort classification |
| `ultratimonel/triple_match.py` | Modified | Non-blocking WARN for 1a/1b |
| `openspec/specs/*` | New/Modified | Specs/deltas per Capabilities above |

### Affected MCP tools/resources
- **Added**: `mission_create`, `mission_update_title`, `mission_update_description`, `quest_add`, `quest_update`, `sync_task` (working names; finalized in design).
- **Modified**: `begin_turn` (fail on done quest), `end_turn` (wrapper + compact), `mission_list` (compact default), read/list tools (compact).
- **Deprecated (kept registered)**: `sync_all`.
- **Best-effort (leave mandatory set)**: `agentmemory` (1a), `agentcheckpoint` (1b).
- **Resources**: none.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Internal Deck write bridge unimplemented (`bridge.py` stub) | High | Design phase must define it; block apply until resolved; no local-only fallback |
| Deck ↔ SQLite replica drift | Med | New tools write Deck first, then refresh replica; `sync_task` explicit recovery |
| Deprecating `sync_all` breaks callers | Low | Kept registered and marked; never removed |
| `begin_turn` hard-fail leaves stuck turns | Med | Clear error; orchestrator picks/creates next quest |
| Hidden behavior change beyond additive scope | Med | Out-of-scope guard; stop-and-report if source of truth moves |

## Confirmed Decisions (PM)

- Business question round already resolved in `.hermes-tmp/contrato-cards-solo-ultratimonel-decisiones.md` — no open decisions remain.
- **Write path**: new tools write against **Deck (source of truth)** via ultratimonel's internal bridge; local SQLite is a **replica**. No local-only writes; no relying on a later sync.
- **Quest model**: quest = row in `checklist_items`; "checked" = column **`done`** — unify terminology to `done`. No new entity.
- **Sync**: `sync_task` singular by local `mission_id` (resolves Deck `deck_task_id` internally), explicitly invoked by Hermes. `sync_all` deprecated with mark, not removed.
- **Agents**: `agentcheckpoint` + `agentmemory` best-effort; failure MUST NOT block turn success (removes WARN ⇒ `fail`). Full removal deferred, not in this change.
- **Batch #179-#186**: this change **supersedes #181, #182 and #185** (1:1 overlap: compact outputs, sync N+1, deterministic management — do NOT duplicate). The rest of the batch stays **independent**.
- **Confirmations**: Req 2 `begin_turn` fails hard on done quest; Req 5 compact outputs by default, no global `verbose` flag.

## Rollback Plan

- Git-revert the change commit: tool additions/edits in `server.py`, `gate_engine.py`, `triple_match.py` are additive, so reverting restores the prior MCP surface.
- `sync_all` is never removed, so no caller contract to undo.
- No destructive SQLite DDL expected; any migration MUST be additive (NF-GP-05) and revertible via an older server (`SCHEMA_AHEAD` fails safe).
- Deck is never modified by rollback; data stays canonical.

## Dependencies

- `ultratimonel/bridge.py` internal Deck write bridge — `register_capabilities()` is a **stub**; design dependency/risk, not designed here.
- Existing Deck write precedent: `mcp_client.py` + `card_update_description` (`deck_update_card`).
- `openspec/specs/` main specs for delta merges.

## Success Criteria

- [ ] 6 requirements covered 1:1 and traceable; no scope invented.
- [ ] Nextcloud (Deck) explicitly declared the ONE source of truth; change declared additive.
- [ ] Mission/quest write tools exist; no mark-complete tool; add/update quest set `done=false`.
- [ ] `begin_turn` fails on done quest; `end_turn` is the only `false→true` and the wrapper.
- [ ] `sync_all` deprecated-but-registered; `sync_task` recovers one mission; `sync_tasks` retained.
- [ ] `end_turn`/`mission_list`/read-list outputs compact by default.
- [ ] Agents 1a/1b best-effort; their failure does not force `end_turn` fail.
- [ ] Rollback restores the prior tool surface without data loss.
