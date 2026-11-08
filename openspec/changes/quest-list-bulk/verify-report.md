# Verify Report: quest-list-bulk (Card Deck #194)

> **Change:** `quest-list-bulk` · **Branch:** `feature_194_quest-list`
> **Date of this run:** 2026-10-21
> **Scope verified:** `origin/main...HEAD` (9 files, +576 / −23)
> **Inputs:** [proposal.md](./proposal.md) · [spec.md](./specs/quest-list/spec.md) · [design.md](./design.md) · [tasks.md](./tasks.md)

## Verdict

**GENERAL: PASS** — the implementation matches every scenario in the delta spec,
the suite is green, and no CRITICAL finding remains. Two WARNINGs and three
SUGGESTIONs are recorded below; none blocks the change.

## Evidence executed in this run

All commands were run from the repository root with the project virtualenv.
Results are copied verbatim from the terminal.

### Full suite (default selection)

```text
$ .venv/bin/python -m pytest -q
........................................................................ [ 27%]
........................................................................ [ 55%]
........................................................................ [ 83%]
...........................................                              [100%]
259 passed, 15 deselected in 12.88s
```

Exit code `0`. The 15 deselected tests are the ones marked `integration`
(`pytest.ini` → `addopts = -m "not integration"`).

### Server unit suite

```text
$ .venv/bin/python -m pytest tests/test_server.py -q
........................................................................ [ 67%]
...................................                                      [100%]
107 passed in 3.33s
```

### Quest-list focused selection

```text
$ .venv/bin/python -m pytest -k quest_list -q
.....                                                                    [100%]
5 passed, 269 deselected in 0.81s
```

### Not executed here

`pytest -m integration` was **not** run: the 15 integration tests spawn live MCP
servers (agentmemory, checkpoint, nextcloud) and need
`ULTRATIMONEL_NEXTCLOUD_COMMAND` / `ULTRATIMONEL_NEXTCLOUD_ARGS` pointing at a
working environment. This run had no live MCP environment, so the result is
reported as not executed rather than inferred.

## Spec coverage

| Spec scenario | Evidence | Result |
|---|---|---|
| Full checklist in one call, checklist order, boolean `done` | `TestQuestList::test_quest_list_returns_full_checklist` — asserts ids `[101,102,103]`, order, and `isinstance(q["done"], bool)` for all rows | PASS |
| `include_done=true` (default and explicit) includes completed quests | `test_quest_list_include_done_true_includes_done` — `total == 3` in both calls, at least one `done is True` | PASS |
| `include_done=false` omits completed quests | `test_quest_list_include_done_false_omits_done` — ids `[101,103]`, `total == 2`, all `done is False` | PASS |
| Unknown mission fails without mutation | `test_quest_list_mission_not_found` — exact error string, `list_checklist_items` not called, `set_quest_done` / `upsert_checklist_item` not called | PASS |
| Registered in the tool catalog | `test_quest_list_registered_in_catalog` — `app.list_tools()` contains `quest_list`; plus `tests/test_integration.py::test_tools_listed` asserts it in the live stdio catalog | PASS (hermetic) |
| Read-only — never completes a quest | `ultratimonel/server.py` L1340–L1353 has no write call and no bridge import; unit test asserts no mutation on both paths | PASS |

### Contract conformance

- Signature `quest_list(mission_id: int, include_done: bool = True)` — matches
  `spec.md` and `design.md` (`ultratimonel/server.py:1324`).
- Output envelope `{mission_id, quests, total}` — `server.py:1349–1353`.
- Error envelope `{"error": "Mission <id> not found"}` — `server.py:1342`.
- Ordering and `done` normalization delegated to
  `persistence.list_checklist_items` (`ORDER BY item_index`) and
  `compact.compact_quest` (`bool(...)`), not reimplemented.
- Zero schema changes: `git diff origin/main...HEAD` touches no migration or
  schema file.
- Zero Deck-bridge calls: the new function imports and calls no
  `deck_bridge` / `mcp_client` symbol.

## Root cause of the previous suite hang

The suite was not hanging on an anyio cancel scope. `call_mcp_tool` was
spawning the `nextcloud` MCP server **without arguments**
(`ULTRATIMONEL_NEXTCLOUD_ARGS` empty in the test environment), which produced a
bare Python interpreter that never answers `initialize`. With a 30 s initialize
timeout plus one retry, every accidental call cost ≈60 s; several gate-touching
tests made the run look permanently stuck.

## Harness fix applied on this branch

1. `tests/conftest.py` — autouse fixture pins `call_mcp_tool` to
   `(None, "unavailable")` for every test not marked `integration`. It patches
   both `mcp_client.call_mcp_tool` and the direct alias
   `triple_match.call_mcp_tool`, because `triple_match` imported the symbol by
   value. Unit tests can no longer spawn a live server by accident.
2. `pytest.ini` — declares the `integration` marker and sets
   `addopts = -m "not integration"`, so the default run is hermetic.
3. `tests/test_triple_match.py` — `TestTripleMatch` marked `integration`
   (it calls `run_triple_match` without mocking the transport).
4. `tests/test_integration.py` — two stale tests repaired: the explicit-project
   test now uses a real mission/quest (the `missing_quest` guard rejects
   `mission_id=0`) and the post-grace bouncer test pins `_turn_count` and
   expects the current message (`Gates obligatorios no pasaron`, see
   `ultratimonel/plugin_preflight.py:128`).
5. Performance tests with an inverted formula
   (`/ iterations * iterations / 1000` always passed) corrected to
   `/ iterations * 1000`.

## Findings

### CRITICAL

None.

### WARNING

1. **The default run does not exercise the live catalog.** The live stdio
   assertion lives in `tests/test_integration.py::test_tools_listed`, which is
   deselected by `addopts`; the default suite proves registration only through
   the in-process `app.list_tools()`. Run `pytest -m integration` with a live
   MCP environment before promoting to `main`. Evidence:
   `pytest.ini:1-6`, `tests/test_integration.py:97`.
2. **Five `TestTripleMatch` tests left the default selection.**
   `tests/test_triple_match.py:34` marks the whole class `integration`, so those
   tests no longer run by default. The decision is defensible (they call
   `run_triple_match` against the real transport), but the coverage reduction
   must stay visible in the PR description. Evidence:
   `tests/test_triple_match.py:34`, `259 passed, 15 deselected`.

### SUGGESTION

1. **No pagination or `limit` on `quest_list`.** A hypothetical very large
   checklist returns in one payload. The proposal already lists this as an
   accepted risk and points to the wrapper-dedup follow-up; a `limit`/`offset`
   pair would bound it if real data ever grows far beyond ~40 quests. Evidence:
   `ultratimonel/server.py:1343-1353`, `proposal.md` §Risks.
2. **Error branch serializer is inconsistent with the success branch.**
   `server.py:1342` uses plain `json.dumps(...)` while the success path uses
   `ensure_ascii=False, default=str`. Harmless today (the message is ASCII), but
   consistency avoids a surprise if the message ever carries a mission title.
3. **`test_begin_turn_persists_explicit_project` hardcodes `mission_id=1` and
   `quest_id` from `list_checklist_items(1)`.** `_make_db()` already returns the
   mission id (`mid`); using it would keep the test correct if seed order ever
   changes. Evidence: `tests/test_integration.py:256-265, 318`.

## Artifacts checked

- `openspec/changes/quest-list-bulk/proposal.md`
- `openspec/changes/quest-list-bulk/specs/quest-list/spec.md`
- `openspec/changes/quest-list-bulk/tasks.md`
- `openspec/changes/quest-list-bulk/design.md` (this run)
- `ultratimonel/server.py` (`quest_list`, L1323–L1353)
- `tests/test_server.py` (`TestQuestList`)
- `tests/test_integration.py`, `tests/test_triple_match.py`, `tests/conftest.py`, `pytest.ini`
