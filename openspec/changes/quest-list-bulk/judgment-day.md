# Judgment Day: quest-list-bulk (Card Deck #194)

> **Target:** `origin/main...HEAD` on `feature_194_quest-list`
> **Base:** `9ed02bb3c49c4c4b8c44ffa6172394f0f018848e`
> **Head:** `a326bda82018517b0c4bb1c77075ee365208a704`
> **Diff:** 9 files, +576 / −23
> **Date:** 2026-10-21
> **Round:** 1
> **Mode:** read-only adversarial review. Nothing was edited, staged, committed,
> or reverted during this review.

## Scope and method

Frozen scope: the full commit range `origin/main...HEAD` — production code
(`ultratimonel/server.py`), tests (`tests/test_server.py`,
`tests/test_integration.py`, `tests/test_triple_match.py`, `tests/conftest.py`),
runner config (`pytest.ini`), and the three SDD artifacts
(`proposal.md`, `specs/quest-list/spec.md`, `tasks.md`).

Criteria: correctness, edge cases, error handling, read-only guarantees,
regression surface, test validity, performance/conventions.

**Method limitation (disclosed, not hidden).** The judgment-day skill calls for
two blind judges launched in parallel with identical scope. This runtime exposed
no sub-agent/delegation tool in the session, so a true two-judge blind run was
not possible and no result here is represented as "confirmed by two judges".
The closest available audit was performed: one independent first pass over the
frozen diff, with two explicit adversarial lenses applied in sequence — Judge A
(correctness, edge cases, error handling, read-only invariant) and Judge B
(regression surface, test validity, performance, project conventions). Findings
are classified as `deterministic` when the evidence is a direct code/diff fact,
and `suspect` when a second independent pass would be needed to confirm. No
correction round was run and no fix was applied, per the card contract.

## Findings ledger

| ID | Severity | Class | Location | Claim | Status |
|---|---|---|---|---|---|
| JD-1 | WARNING | documentation drift (deterministic) | `openspec/changes/quest-list-bulk/tasks.md:47` | T1 states "`design.md` omitted: the only real decision (R4) is recorded in the proposal". That is no longer true: card #194 requires a retroactive `design.md`, which now exists. The task line contradicts the delivered artifact set. | Open — not fixed (scope excludes editing tasks.md) |
| JD-2 | WARNING | evidence integrity (deterministic) | `openspec/changes/quest-list-bulk/tasks.md:170` | The file records "**Veredicto judgment-day:** APPROVE" before any `judgment-day.md` existed. A verdict was asserted ahead of the review that is supposed to produce it. This document is the first actual review artifact, and its verdict is independent of that pre-written line. | Open — not fixed (scope) |
| JD-3 | INFO | stale measurement (deterministic) | `openspec/changes/quest-list-bulk/tasks.md:174` | Records 523 changed lines on this branch; measured `git diff --shortstat origin/main...HEAD` is +576/−23 (599 changed). The metric definition used by the author may differ, but the recorded number no longer reproduces. The conclusion (over the 400-line budget) is unchanged either way. | Info |
| JD-4 | WARNING | unverified live path (deterministic) | `tests/test_integration.py:97`, `pytest.ini:6` | The live stdio catalog assertion (`quest_list` in `list_tools()`) is marked `integration` and deselected by default; this run did not execute it. Registration is proven only in-process by `test_quest_list_registered_in_catalog`. Live exposure remains unverified until `pytest -m integration` runs with a live MCP environment. | Info — run before `main` |
| JD-5 | SUGGESTION | test safety net is partial (deterministic) | `tests/conftest.py:24-39` | The autouse stub patches `mcp_client.call_mcp_tool` and `triple_match.call_mcp_tool`. Any future module-level `from .mcp_client import call_mcp_tool` (the pattern `server.py` uses inside function bodies is safe) would capture the real symbol and bypass the stub. The fixture is a strong net, not a proof of hermeticity. | Info |
| JD-6 | SUGGESTION | swallowed teardown error (deterministic) | `tests/test_integration.py:75-86` | The fixture's `finally` swallows any `BaseException` raised while exiting the transport after `stop.set()`. A genuine shutdown regression would be invisible. Startup failures are still surfaced through `ready`. | Info |
| JD-7 | SUGGESTION | hardcoded seed id (deterministic) | `tests/test_integration.py:318` | `quest_id = p.list_checklist_items(1)[0]["id"]` and `mission_id=1` assume the first inserted mission has id 1, while `_make_db()` already returns `mid`. Brittle if seeding order ever changes. | Info |

### Lens A — correctness, edge cases, error handling, read-only

- **Full checklist and ordering** — `list_checklist_items` is
  `ORDER BY item_index` (`ultratimonel/persistence.py:886-895`); `quest_list`
  does not re-sort or reorder. `compact_quest` maps `{id, text, done}` and
  normalizes `done` with `bool(...)` (`ultratimonel/compact.py:69-79`).
  **Clean.**
- **Filtering** — `include_done=False` filters on the already-normalized
  boolean (`server.py:1347-1348`); no `0`/`1` leakage. **Clean.**
- **Unknown mission** — falsy `get_mission` returns the exact spec string and
  short-circuits before `list_checklist_items`; no write path is reachable
  (`server.py:1340-1342`). **Clean.**
- **Read-only invariant** — no `deck_bridge`, no `mcp_client`, no persistence
  write call in the new function. **Clean.**
- **Input coercion** — `mission_id: int`, `include_done: bool` are declared and
  validated by the FastMCP tool registration, same as sibling tools.
  **Clean.**
- **Serializer consistency** — success branch uses
  `ensure_ascii=False, default=str`; the error branch uses plain `json.dumps`
  (`server.py:1342` vs `1349-1353`). Harmless today (ASCII-only message), noted
  as a consistency nit in `verify-report.md` SUGGESTION 2.

### Lens B — regression surface, tests, performance, conventions

- **Existing tool behavior** — additive function; no existing function body was
  modified in `server.py`. `git diff` on `server.py` is insertion-only (+33).
  **Clean.**
- **Schema / migrations** — no schema file touched. **Clean.**
- **Test validity** — the five `TestQuestList` tests assert the spec's observable
  effects (payload, order, boolean type, filter, exact error, no mutation,
  catalog presence). They mock `persistence` at the module boundary, which is
  the same pattern used by the rest of `test_server.py`. **Clean.**
- **Harness changes** — `conftest.py` and `pytest.ini` are justified by the
  documented 60 s-per-call hang; the root cause (empty
  `ULTRATIMONEL_NEXTCLOUD_ARGS` → bare interpreter that never answers
  `initialize`) is consistent with `call_mcp_tool`'s timeout/retry shape. The
  performance-formula corrrection (`/ iterations * 1000`) is mathematically
  correct per-iteration milliseconds; the previous expression was an identity
  and could never fail. **Clean.**
- **Bouncer test** — expected message `Gates obligatorios no pasaron` matches
  `ultratimonel/plugin_preflight.py:128`; `_turn_count = 5` clears
  `GRACE_TURNS = 3` (`plugin_preflight.py:18,120`). **Clean.**
- **Performance** — O(n) serialization in one call versus n round trips; the
  only unbounded axis is payload size, already recorded as an accepted risk in
  `proposal.md` §Risks and `verify-report.md` SUGGESTION 1. **Clean.**
- **Security** — no new input reaches a shell, no file path, no credential, no
  network call. **Clean.**

## Verdict

**APPROVE WITH FIXES**

Justification: the change under review — the production tool and its tests — has
no CRITICAL or behavioral defect. It is additive, reuses the existing replica
read path and serializer, preserves the read-only invariant, and its five unit
tests map one-to-one to the spec scenarios. The suite is green
(`259 passed, 15 deselected in 12.88s`).

The fixes required are documentation/process-only and do not touch code:

1. **JD-1** — update `tasks.md:47` to reference the retroactive `design.md`
   instead of asserting it was omitted.
2. **JD-2** — annotate `tasks.md:170` so the judgment-day verdict points at this
   report as its source, rather than preceding it.
3. **JD-3** — reconcile the changed-line figure in `tasks.md:174` with
   `git diff --shortstat` (or state the metric used).

Neither JD-1/2/3 nor the SUGGESTIONs block merge. JD-4 must be cleared by running
`pytest -m integration` in an environment with live MCP servers before promoting
to `main`.

None of these were applied in this run, per the card contract.

```yaml
target_identity: a326bda82018517b0c4bb1c77075ee365208a704 (base 9ed02bb3c49c4c4b8c44ffa6172394f0f018848e)
round: 1
confirmed: []
suspect: []
contradictions: []
info:
  - JD-1  # tasks.md:47 stale "design.md omitted"
  - JD-2  # tasks.md:170 verdict recorded before review
  - JD-3  # tasks.md:174 changed-line figure does not reproduce
  - JD-4  # live integration catalog assertion not executed
  - JD-5  # conftest stub covers two import sites only
  - JD-6  # teardown exceptions swallowed after stop
  - JD-7  # hardcoded mission id 1 in integration test
fix_work_units: []
scoped_rejudgment: not_run
terminal_state: approved
skill_resolution: fallback-registry — judgment-day SKILL.md loaded from /home/ernesto-personal/.config/opencode/skills/judgment-day/SKILL.md; registry (.atl/skill-registry.md:49) points to /home/ernesto-personal/.agents/skills/judgment-day/SKILL.md. No sub-agent delegation tool was available in this runtime, so the two-judge blind protocol was reduced to a single-pass dual-lens audit (disclosed above).
```

## Follow-ups (not part of this change)

- Run the live integration suite before `main`.
- Decide whether `quest_list` needs `limit`/`offset` once real checklists grow.
- Fold the harness changes into a dedicated PR slice if the 400-line budget must
  be respected at review time (the branch is already over it: 599 changed
  lines).
