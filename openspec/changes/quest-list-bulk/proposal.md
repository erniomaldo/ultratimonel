# Proposal: quest-list-bulk (Card Deck #194)

## Intent

Answering a single mission status question ("where are we?") currently costs
one `checklist_item_get` call **per quest**. The forum retro (discussion #3,
2026-10-18) reports 39 quests → 39 invocations; sending the 39 ids in one batch
was rejected by the local tool transport
(`tool_call takes exactly one entry for local tools; you sent 39`). The agent
has no way to fetch a mission's full checklist (id + text + done) in one call.

## Scope

### In Scope

- Add read-only tool `quest_list(mission_id: int, include_done: bool = True)`
  returning every quest of a mission in checklist order as `{id, text, done}`.
- `include_done=False` omits completed quests; `True` (default) includes them.
- Unknown mission → explicit error result, no state mutation.

### Out of Scope

- Deduplicating the triple wrapper (`result` + `structuredContent` +
  `_meta.fastmcp.wrap_result`) of ~30 read tools — separate follow-up.
- Turn state (`success|failed|aborted|partial`) and turn authorization — belongs
  to `cards-deterministas` on its own branch.
- Any schema change.

## Capabilities

### New Capabilities

- `quest-list`: single-call full-checklist read for a mission.

### Modified Capabilities

- None. No existing tool behavior changes.

## Approach

`quest_list` reads the local SQLite replica through the existing
`persistence.get_mission()` and `persistence.list_checklist_items()` (already
ordered by `item_index`) and serializes each row with the existing pure
`compact.compact_quest()` helper (already normalizes `done` to `bool`). No new
persistence method, no bridge, no schema change. Registered with the same
`@app.tool()` pattern, type hints, and `json.dumps(..., ensure_ascii=False,
default=str)` as sibling read tools.

## Decision: R4 symmetry (evaluate and document)

**Decision: NOT implemented in this change.** Documented as follow-up.

- `mission_get(include_quests=true)`: duplicates exactly what `quest_list`
  now returns; two payload shapes for the same data would be redundant surface.
- Batch `checklist_item_get(checklist_item_ids: [int])`: the reported failure
  mode is precisely that the agent does **not** know all ids up front — that is
  why it needed 39 calls. A batch still requires the caller to have every id, so
  it does not solve the original need; `quest_list` is the direct fix.

Follow-up: if a caller ever needs quests across **multiple** missions in one
call, add a `quest_list_many(mission_ids: [int])` rather than retrofitting
`checklist_item_get`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `ultratimonel/server.py` | Modified | Add `quest_list` read tool |
| `tests/test_server.py` | Modified | Add `TestQuestList` unit tests |
| `tests/test_integration.py` | Modified | Assert `quest_list` in the live tool catalog |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Large checklists inflate one response | Low | Same ~600 bytes/quest as today's per-id calls, but in **one** round trip; the wrapper dedup follow-up addresses sizing |
| Response shape drift vs `compact_quest` | Low | Reuse `compact.compact_quest`; no new serializer |

## Rollback Plan

Pure additive change. Revert the commit: delete the `quest_list` function and
its tests. No data, schema, or existing tool behavior is affected.

## Success Criteria

- [ ] `quest_list(mission_id)` returns every quest `{id, text, done}` in order in ONE call
- [ ] `include_done=False` omits completed quests; `True` includes them
- [ ] Unknown `mission_id` returns `{"error": "Mission <id> not found"}` with no mutation
- [ ] `quest_list` is registered in the agent tool catalog
