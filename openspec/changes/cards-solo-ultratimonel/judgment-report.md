# Judgment Report — cards-solo-ultratimonel

**Branch**: `feature_189_cards-solo-ultratimonel` (working tree, NOT committed)
**Target**: full change — proposal, 6 delta specs, design (D1–D10), tasks (20/20), apply-progress, verify-report, and the implementation.

---

## Round 1 — 2026-09-27

| Judge | Lens | Delegation | Verdict |
|-------|------|-----------|---------|
| A | Architect | `unwilling-moccasin-finch` | **ISSUES FOUND** |
| B | Adversarial | `mid-tan-wolverine` | **ISSUES FOUND** |

Both blind, parallel, fresh context. No git, no code changes. **No contradictions.**

### Confirmed in Round 1
- **CRITICAL F1** — `begin_turn` persisted the raw alias `checklist_item_id=0` instead of the resolved `quest_id`, so `end_turn` never performed the quest `false→true` transition (runtime-proven by both judges). `verify` had missed it (hand-built intentos + no `create_intento` arg assertion).
- **W-d** — quest text interpolated verbatim could inject extra checkbox lines (incl. `- [x]`).
- **W-b/W3** — `sync_task` did not delete replica quests removed in Deck.
- **W-a** — `begin_turn` guard silently bypassed when ids omitted (defaults `0`).
- **W-f** — `end_turn` failed open with zero gate evidence.
- **W-g** — wrong `deck_stack_id` could be permanently backfilled.
- Verify W1–W6: all CONFIRMED.

**Round 1 outcome**: `JUDGMENT: ESCALATED ⚠️` — not approved; fix round applied.

---

## Fix round (Round 1 → Round 2) — 2026-09-28

Surgical fix agent (`passive-maroon-dinosaur`), 6 fixes + 12 new tests, one pass. Runtime only against temp DB / mocks; no git; `bridge.py` untouched.

- Fix 1 (CRITICAL): `create_intento(..., checklist_item_id=resolved_quest_id)` (`server.py:1891-1895`) + e2e test without hand-built intento.
- Fix 2 (W-d): `_single_line_quest_text` rejects `\n`/`\r` (`deck_bridge.py:165-176`, `:308-310`, `:345-347`).
- Fix 3 (W-b/W3): `delete_checklist_items_beyond` (`persistence.py:922`) + status from card stack (`server.py:1140-1170`).
- Fix 4 (W-a): require nonzero quest/mission id (`missing_quest`/`missing_mission`, `server.py:1753-1777`).
- Fix 5 (W-f): fail-closed without mandatory-gate evidence (`server.py:2104-2118`).
- Fix 6 (W-g): backfill stack only if the card was located (`server.py:1010-1054`, `:1116-1122`).

**Regression**: bounded deterministic subset → **205 passed, 12 deselected** (baseline 193 + 12 new). One existing test updated (`test_end_turn_gate_capture_failure_completes` now asserts `fail` — required by Fix 5, not masking).

---

## Round 2 — 2026-09-28 (re-judge after fixes)

| Judge | Lens | Delegation | Verdict |
|-------|------|-----------|---------|
| A | Architect | `loyal-gray-armadillo` (retry after timeout) | **ISSUES FOUND** |
| B | Adversarial | `inc-chocolate-prawn` | **ISSUES FOUND** |

Both blind, parallel. No git, no code changes. No new regressions introduced by the fixes.

### Round-1 finding closure

| # | Finding | Judge A | Judge B | Net |
|---|---------|---------|---------|-----|
| 1 | CRITICAL — cursor alias vs resolved quest id | CLOSED | CLOSED | ✅ **CLOSED** |
| 2 | W-d quest-text injection | CLOSED | CLOSED | ✅ **CLOSED** |
| 3 | W-b/W3 stale quests + stale status | PARTIAL | PARTIAL | ⚠️ **PARTIAL** — stale-quest deletion works; `status` derivation is defeated by the D9 cache (after the first sync, `deck_stack_id` is cached so the stack title can no longer be resolved) |
| 4 | W-a guard bypass on omitted ids | CLOSED | CLOSED | ✅ **CLOSED** |
| 5 | W-f fail-open with zero gate evidence | PARTIAL | PARTIAL | ⚠️ **PARTIAL** — the empty case fails closed, but the evidence source is **session-scoped, not turn-scoped**: a stale previous-turn `PASS` can still yield `success` |
| 6 | W-g wrong stack backfilled | PARTIAL | CLOSED | ⚠️ **PARTIAL** — `sync_task` now fails closed, but the **`end_turn` write path still guesses the stack** (asymmetric) |

### New confirmed issues (Round 2) — no CRITICAL

| Severity | Finding | File:line |
|----------|---------|-----------|
| WARNING (real) | `end_turn` quest closure targets a **guessed** stack (`_resolve_stack_id` pending/first heuristic) — Fix 6's guarantee was not applied to the single `false→true` path; the Deck write can silently fail with `quest_done=false` | `server.py:1969` (`_complete_quest_for_intento`), `:1367-1371` |
| WARNING (real) | `end_turn` gate evidence is **session/project-scoped**, not turn-scoped; a stale previous-turn `PASS` yields a false `success` (the fresh snapshot already stored on the intento is unused) | `server.py:2083-2087` |
| WARNING (real) | `mission_create` writes `description` verbatim → checkbox lines (incl. `- [x]`) become quests, contradicting the "no quest is created" contract | `server.py:1419` |
| WARNING (theoretical) | `delete_checklist_items_beyond` can orphan `intentos` (no FK enforcement) | `persistence.py:922-936`, `server.py:1956-1962` |
| WARNING (theoretical) | Duplicate quest parsers (`sync_tasks` vs `deck_bridge.extract_quests`) make positional `complete_quest` index-unsafe on non-canonical markers | `server.py:936-948`, `deck_bridge.py:50,179-198` |
| SUGGESTION | Replica text drift on quest writes (bridge trims, server persists raw text) | `server.py:1613`, `:1700` |
| SUGGESTION | `begin_turn` still advertises `mission_id=0, quest_id=0` as optional while the guard requires them | `server.py:1714-1715` |
| SUGGESTION | `tests/test_integration.py:285` still calls `begin_turn(..., 0, 0, ...)`, now rejected by Fix 4 (pre-existing hang, out of scope) | `tests/test_integration.py:285` |

## Scope / source-of-truth checks

`bridge.py` remains the unmodified capability-discovery stub. No source-of-truth move. Everything remains Deck-first via `deck_bridge`. No new CRITICAL; no scope violation.

---

## Final Verdict

**JUDGMENT: ESCALATED ⚠️** (Round 2)

The original **CRITICAL is CLOSED** and 3 of 6 Round-1 findings are fully closed. No new regressions were introduced by the fixes. However, **3 confirmed real WARNINGs remain** on runtime paths:

1. `end_turn` closes against a guessed stack (asymmetric with Fix 6).
2. `end_turn` gate evidence is not turn-scoped (stale PASS → false success).
3. `mission_create` description can inject quests.

Per the Judgment Day rule (approved = zero confirmed CRITICAL **and** zero confirmed real WARNINGs), the change is **NOT approved**. A second bounded fix iteration (these 3 real warnings) + re-judge is required before the chained PRs.

## Pre-PR recommendation

**Do NOT open the chained PRs yet.** Run a second surgical fix iteration over the 3 confirmed real warnings, re-judge (Round 3), and only then proceed to PR. The CRITICAL fix is solid and regression is green (205 passed), so the remaining work is bounded.

---

## Iteration 2 (Round 2 → Round 3) — 2026-09-28

Surgical fix agent (`marine-rose-porcupine`), 3 fixes + 4 new tests, one pass. Runtime only against temp DB / mocks; no git; `bridge.py` untouched.

- Fix 1: `_complete_quest_for_intento` (`server.py:2003`) now uses `_resolve_stack_for_card` (fail-closed) instead of the guessing `_resolve_stack_id`.
- Fix 2: `_gates_from_intento_snapshot` (`server.py:133-160`); `end_turn` (`:2115-2120`) derives `final_gates` from the intento's `gates_detail`; empty/missing → `fail`.
- Fix 3: `clean_prose` (`deck_bridge.py:202`), reused by `update_description` (`:293`) and `mission_create` (`server.py:1446`).

**Regression**: bounded deterministic subset → **209 passed, 12 deselected** (205 + 4 new).

---

## Round 3 — 2026-09-28 (re-judge after iteration 2)

| Judge | Lens | Delegation | Verdict |
|-------|------|-----------|---------|
| A | Architect | `criminal-olive-toad` | **ISSUES FOUND** |
| B | Adversarial | `continental-magenta-kite` | **ISSUES FOUND** |

Both blind, parallel. No git, no code changes.

### Round-2 residual finding closure

| # | Finding | Judge A | Judge B | Net |
|---|---------|---------|---------|-----|
| 1 | `end_turn` guessed stack | CLOSED | CLOSED | ✅ **CLOSED** |
| 2 | Session-scoped gate evidence | CLOSED | CLOSED | ✅ **CLOSED** |
| 3 | `mission_create` description injection | CLOSED | PARTIAL | ⚠️ **CONTRADICTION — escalate** |

### Residual issues (Round 3) — no CRITICAL

| Severity | Finding | Evidence |
|----------|---------|----------|
| WARNING (real) — **both judges** | **Masking / stale test debt**: 5 of the 7 deselected `TestEndTurn`/`TestBeginTurnProjectFix` tests (`test_end_turn_success_4_4`, `…blocked_by_block_gate`, `…warn_gates_completes_as_fail`, `…partial_pass`, `test_end_turn_validates_against_persisted_project`) have assertions invalidated by the new fail-closed snapshot logic and were NOT updated. Production `end_turn` is NOT broken (`begin_turn` captures the snapshot when `gate_results` is non-empty), but the deselected set is now stale and hides the dependency. | `tests/test_server.py:569,608,633,800,1501` |
| WARNING (real) — Judge B (empirically confirmed) | **Incomplete sanitization**: `clean_prose` strips a strict subset of what `sync_tasks` treats as a quest. `- [TODO] x`, `- [] x`, `- [  ] x` survive cleaning, but `sync_tasks` (`server.py:962`, `line.startswith("- [")`) counts them → a `mission_create` description can still inject a quest on the next bulk sync. | `deck_bridge.py:51,202-212` vs `server.py:962` |
| INFO | `_resolve_stack_for_card` cached branch (`server.py:1052-1054`) returns a cached `deck_stack_id` without re-locating the card (D9-by-design). | — |
| INFO | `TestEndTurnQuestTransition` still patches the now-unused `_resolve_stack_id` (dead patch). | — |
| INFO | No negative test for non-standard bracket content in `mission_create`. | — |

**Contradiction**: Judge A marks finding 3 CLOSED; Judge B marks it PARTIAL with an empirical counter-example (parser divergence). Per the Judgment Day rule, a contradiction escalates for human decision.

---

## Final Verdict (Round 3)

**JUDGMENT: ESCALATED ⚠️** — 2 fix iterations exhausted.

The Round-1 CRITICAL is **CLOSED** and held closed across Round 3. Round-2 findings 1 and 2 are **CLOSED**. No new CRITICAL. **No production regression** was found (the updated fixtures are faithful; `begin_turn` always captures the snapshot on the normal path).

Remaining blockers to approval:
1. **Finding 3 contradiction** — the `clean_prose` vs `sync_tasks` parser divergence leaves an injection vector (Judge B, empirical).
2. **Masking / stale test debt** — 5 deselected tests assert the old contract and were not updated (both judges).

## Pre-PR recommendation

**Not approved yet.** Two bounded options:
- **(a)** A 3rd iteration: unify the quest parsing/cleaning on ONE parser (`sync_tasks` should use `deck_bridge.extract_quests`; `clean_prose` should strip exactly what that parser accepts) + update the 5 stale deselected tests. Then Round 4.
- **(b)** Accept the residual as **documented debt with explicit PM sign-off** and proceed to the chained PRs, carrying the two warnings into the PR description.

Requires a human/PM decision (2 iterations exhausted).

---

## Iteration 3 (Round 3 → Round 4) — 2026-09-28

Fix agent (`precious-silver-dinosaur`), 2 fixes + 9 tests, one pass. Runtime only against temp DB / mocks; no git; `bridge.py` untouched.

- Fix 1 — **ONE quest parser**: `sync_tasks` (`server.py:960`) and `sync_task` (`:1156`) now call `deck_bridge.extract_quests`; authoritative `_CHECKBOX_RE` (`deck_bridge.py:53`); tolerant superset `_QUEST_LIKE_RE = ^\s*[-*+]\s*\[[^\]]*\]` (`:60`) used by `_is_checkbox_line` (`:171-177`); `clean_prose` (`:225`) drops every match.
- Fix 2 — the 5 stale tests now supply the `gates_detail` snapshot (`tests/test_server.py:657, :695, :731, :906, :1612`).

**Regression**: bounded deterministic subset → **218 passed, 12 deselected** (209 + 9 new).

---

## Round 4 — 2026-09-28 (FINAL)

| Judge | Lens | Delegation | Verdict |
|-------|------|-----------|---------|
| A | Architect | `anonymous-emerald-barnacle` | **CLEAN** |
| B | Adversarial | `revolutionary-olive-asp` | **ISSUES FOUND** |

### Closure of Round-3 residuals

| # | Finding | Judge A | Judge B | Net |
|---|---------|---------|---------|-----|
| 1 | Incomplete sanitization / double parser | CLOSED | CLOSED | ✅ **CLOSED** |
| 2 | Masking / stale test debt | CLOSED | CLOSED | ✅ **CLOSED** |

- **One parser confirmed**: `sync_tasks` + `sync_task` both call `extract_quests`; no other `startswith("- [")`/`[x]` parsing remains in `*.py`.
- **Sanitization proven bypass-free** across 18–19 adversarial variants (`- [TODO]`, `- []`, `- [  ]`, `+ [x]`, `1. [ ]`, tabs, NBSP, nested indent, CRLF, …): 0 parsed quests survive `clean_prose`.
- **The 5 tests are consistent** with the snapshot contract (`name`/`state`/`mandatory`), assertions hold.

### Residual (non-critical — per CAP)

| Severity | Finding | Evidence |
|----------|---------|----------|
| WARNING (real) — Judge B, empirically verified; Judge A judged it safe/out-of-contract (contradiction) | **Over-sanitization**: `_QUEST_LIKE_RE` targets the whole bracket, so `clean_prose` deletes legitimate NON-quest bullets — `- [Docs](https://x.dev)`, `- [WIP]: refactor`, `- [1] first item` → data loss on `mission_create` / `update_description`. New in iteration 3. | `deck_bridge.py:60,225` |
| INFO (pre-existing debt) | `card_update_description` (`server.py:2344-2425`) writes raw `description` with no `clean_prose` and no quest preservation — a D3 bypass still open (out of iteration-3 scope). | `server.py:2344` |
| INFO | The 5 tests remain deselected (unpatched `run_triple_match`, `HTTP_TIMEOUT=300s` × 4 gates); patching it would re-enable real coverage. | `tests/test_server.py` |

**Contradiction**: Judge A (`CLEAN`) and Judge B (`ISSUES FOUND`) diverge on the over-sanitization residual's severity → escalate for human decision.

---

## Final Verdict (Round 4)

**JUDGMENT: ESCALATED ⚠️ — closable to APPROVED WITH DOCUMENTED DEBT upon PM sign-off (per the agreed CAP).**

- **No CRITICAL.** Round-3 residual findings **1 and 2 are CLOSED by both judges.** One parser confirmed; sanitization proven bypass-free; the 5 tests are consistent.
- **One non-critical residual** (over-sanitization data loss) + one **pre-existing debt** (`card_update_description` D3 bypass). The PM's CAP: non-critical residuals → accept as documented debt with sign-off and close (no iteration 4).

## Pre-PR recommendation

Per the CAP: **accept the non-critical residuals as documented debt with PM sign-off** and proceed to the chained PRs, carrying both items into the PR description. Optional micro-follow-up (beyond the agreed CAP): narrow `_QUEST_LIKE_RE` from `[^\]]*` to bracket content that looks like a checkbox (`[ ]`, `[x]`, `[X]`, whitespace/uppercase-word-only), which would stop the markdown-link data loss without reopening the injection vector.
