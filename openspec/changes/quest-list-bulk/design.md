# Design: quest-list-bulk (Card Deck #194) — retroactive

> **Change:** `quest-list-bulk` · **Branch:** `feature_194_quest-list`
> **Status:** implemented (documented retroactively on 2026-10-21)
> **Inputs:** [proposal.md](./proposal.md) · [spec.md](./specs/quest-list/spec.md)
> **Code of record:** `ultratimonel/server.py::quest_list` (L1323–L1353)

## Context

A single mission status question ("where are we?") used to cost one
`checklist_item_get` call per quest. The forum retro (discussion #3,
2026-10-18) reported 39 quests → 39 invocations; sending the 39 ids as one
batch was rejected by the local tool transport
(`tool_call takes exactly one entry for local tools; you sent 39`).

The problem is not "fetch many ids at once" — it is that the agent does not
know the ids and has no way to enumerate a mission's checklist from the tool
surface. `quest_list` closes that gap with one read-only call.

## Decision R4 — symmetric bulk APIs: NOT implemented

**Decision:** this change does **not** add `mission_get(include_quests)` nor a
batch mode to `checklist_item_get`.

Rationale (from `proposal.md` §Decision):

- `mission_get(include_quests=true)` would duplicate exactly what `quest_list`
  already returns: two payload shapes for the same data, i.e. two contracts to
  keep in sync and two surfaces for clients to learn.
- A batch `checklist_item_get(checklist_item_ids: [int])` does not solve the
  reported failure: the agent does **not** know the ids up front — that is
  precisely why it needed 39 calls. A batch still requires the caller to hold
  every id, so it keeps the original friction.
- Follow-up if cross-mission reads ever become necessary: add
  `quest_list_many(mission_ids: [int])` rather than retrofitting
  `checklist_item_get`.

Documented as follow-up, not as debt in this change.

## Contract of `quest_list`

### Signature

```python
@app.tool()
def quest_list(mission_id: int, include_done: bool = True) -> str
```

### Output — mission found

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

- `quests` follows `item_index` ascending (checklist order).
- `done` is always a JSON boolean, never SQLite `0`/`1`.
- `total` is the number of quests returned **after** filtering.

### Output — mission not found

```json
{ "error": "Mission <id> not found" }
```

No mutation, no partial write, no Deck call on this path.

### Read-only invariant

`quest_list` never writes: it does not touch the schema, does not call the Deck
bridge (`deck_bridge`/`mcp_client`), and does not mark any quest as done. The
only path to `done=true` remains `end_turn`.

## Data source

Plain read of the local SQLite replica:

1. `persistence.get_mission(mission_id)` resolves the mission; falsy → error
   object (L1340–L1342).
2. `persistence.list_checklist_items(mission_id)` returns the rows already
   `ORDER BY item_index` (L1343–L1346).
3. `compact.compact_quest()` serializes each row to `{id, text, done}` and
   normalizes `done` through `bool(...)` (L1347–L1348).
4. `include_done=False` filters the already-serialized list on the normalized
   boolean (L1347–L1348).
5. The envelope is emitted with `json.dumps(..., ensure_ascii=False,
   default=str)`, matching sibling read tools (L1349–L1353).

No new persistence method, no new serializer, no new schema, no bridge.

## Alternatives considered

| Alternative | Pros | Cons | Chosen |
|---|---|---|---|
| Per-quest `checklist_item_get` loop (status quo) | No new surface | N round trips; the reported 39-call problem | No |
| Batch `checklist_item_get(ids)` | Fewer round trips when ids are known | Caller must already know every id; does not solve the reported case | No |
| `mission_get(include_quests=true)` | One call | Duplicates `quest_list`; two payload shapes for the same data | No |
| New `quest_list(mission_id, include_done)` | One call, no ids needed, reuses existing helpers | One more read tool in the catalog | **Yes** |

## Consequences

- **Positive:** one round trip per mission status; no new persistence or schema
  surface; ordering and `done` normalization are inherited from existing,
  already-tested helpers.
- **Negative:** a very large checklist returns in one response (~600 bytes per
  quest is the proposal estimate). Acceptable for the reported 27–39 quest
  range; wrapper dedup / pagination is an explicit follow-up, not a regression.
- **Risk:** response shape drift if `compact_quest` ever changes. Mitigated by
  reusing that helper instead of a local serializer and by the unit tests
  asserting the `{id, text, done}` shape and boolean type.

## Rollback

The change is purely additive. Revert the `quest_list` commit: the tool and its
tests disappear; no data, schema, or existing tool behavior is affected.
`git revert <commit>` is sufficient; no migration and no data backfill.

## Traceability

| Artifact | Location |
|---|---|
| Proposal / R4 decision | `openspec/changes/quest-list-bulk/proposal.md` |
| Delta spec | `openspec/changes/quest-list-bulk/specs/quest-list/spec.md` |
| Implementation | `ultratimonel/server.py` L1323–L1353 |
| Unit tests | `tests/test_server.py` — `TestQuestList` |
| Integration catalog assertion | `tests/test_integration.py` — `test_tools_listed` |
| Verification evidence | `openspec/changes/quest-list-bulk/verify-report.md` |
| Adversarial review | `openspec/changes/quest-list-bulk/judgment-day.md` |
