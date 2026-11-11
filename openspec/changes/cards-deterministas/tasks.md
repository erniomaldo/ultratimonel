# Tasks: cards-deterministas

> Citation legend (I2): `[Req N]` = requirement N of **Card Deck #2389** (tracked in PR #31; see proposal `## Requirement sources`). Spec tags are `[TT#]`, `[TCE#]`, `[TSP#]`, `[MQM#]`, `[DASH#]`.
> Sequencing note (M4): if `cards-solo-ultratimonel` archives first, its base spec becomes the baseline for the MODIFIED capabilities; re-check ADDED-vs-MODIFIED before apply.

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~900–1300 total, split into 5 PRs ≤400 each |
| 400-line budget risk | Low (per PR); S2 is the chain's risk point (I6) |
| Chained PRs recommended | Yes |
| Suggested split | S1 persistence → S2 turn-enforcement (S2a/S2b if >~350) → S3 card-surface → S4 dashboard → S5 docs |
| Delivery strategy | chained-pr |
| Chain strategy | feature-branch-chain |

Decision needed before apply: No
Chained PRs recommended: Yes
Chain strategy: feature-branch-chain
400-line budget risk: Low

> **PM decision (preflight #3): chained PRs, Feature Branch Chain with tracker.**
> `size:exception` is **NOT approved** and no longer required. The single-PR
> estimate (~900–1300 lines) exceeds the 400-line budget, so the delivery is split
> into 5 chained PRs, each **≤400 changed lines**.
> **Rule**: every PR ≤400 lines; verification happens per PR; `judgment-day` runs
> at the end of the chain; child PRs **never** target `main` directly.

### S2 split trigger (I6)

S2 (~250–380) carries order + binding + budget (+ atomic check-then-increment) +
the `end_turn` closure TXN + checkpoint mirror + a 5-test matrix — one hardening
round pushes it past 400. **Trigger**: if the S2a+S2b combined draft exceeds
~350 changed lines, split S2 before opening the PR:

- **S2a — guards**: `begin_turn` order validation + binding + budget (atomic) + the
  legacy/unbounded carve-out + guard tests. Tasks 2.1, 2.2 (checkpoint sub-step), 2.5 (guard cases).
- **S2b — closure TXN + telemetry**: `end_turn` summary/`closed_at`, the single
  closure transaction (bitácora + completion + success-only item done), checkpoint
  mirror, bitácora/atomicity tests. Tasks 2.3, 2.4, 2.5 (closure/telemetry cases).

### PR Chain (Feature Branch Chain)

**Tracker**: `feature_2389_cards-deterministas` → `main` (draft / no-merge until the chain completes).

| PR | Branch | Base | Scope | Est. lines |
|----|--------|------|-------|------------|
| S1 | `feature_2389_s1_persistence` | tracker | Model v5→v6: DDL + methods + tests | ~200–280 |
| S2 | `feature_2389_s2_turn-enforcement` | S1 | begin/end + telemetry/bitácora + tests | ~250–380 |
| S2a (only if S2 >~350 lines) | `feature_2389_s2a_guards` | S1 | `begin_turn` guard chain (order/binding/budget atomic) + legacy carve-out + tests | ~120–180 |
| S2b (only if S2 >~350 lines) | `feature_2389_s2b_closure` | S2a | `end_turn` closure TXN + summary/bitácora + tests | ~180–260 |
| S3 | `feature_2389_s3_card-surface` | S2 | `card_update_description` out of catalog + internal edit + server-owned title + plugin blocks `deck_*` + tests | ~200–320 |
| S4 | `feature_2389_s4_dashboard` | S3 | API (authorize_attempts/budget/bitácora) + UI + tests | ~200–320 |
| S5 | `feature_2389_s5_docs` | S4 | READMEs + specs index | ~50–100 |

**Dependency diagram** (📍 = next PR to create):

```text
main
 └── feature_2389_cards-deterministas            tracker (draft/no-merge)
      └── 📍 S1 feature_2389_s1_persistence        base: tracker   ~200–280
           └── S2 feature_2389_s2_turn-enforcement base: S1        ~250–380
                (if >~350 lines → S2a guards → S2b closure, then continue)
                 └── S3 feature_2389_s3_card-surface base: S2      ~200–320
                      └── S4 feature_2389_s4_dashboard  base: S3   ~200–320
                           └── S5 feature_2389_s5_docs  base: S4   ~50–100
```

Each PR carries the **Chain Context** block (tracker, position, base, depends-on,
follow-up, review budget, starts-at/ends-with). Children are reviewed against
their immediate parent; a polluted diff is a branching bug → retarget/rebase.

### Work-Unit → PR Map

| Unit | Goal | PR | Notes |
|------|------|----|-------|
| 1 | Data model v5→v6 (DDL + methods) | S1 | Layer 1; tests with code |
| 2 | Turn enforcement + telemetry/bitácora | S2 (or S2a/S2b) | Depends on S1 |
| 3 | Card surface internalized + server-owned title | S3 | Depends on S2 |
| 4 | Dashboard API + UI | S4 | Depends on S3 |
| 5 | Docs | S5 | Depends on S4 |

## Phase 1: Data model & migration

- [ ] 1.1 `persistence.py`: bump `SCHEMA_VERSION` 5→6; `_migrate_v5_to_v6` adding `checklist_items.attempts_authorized/attempts_used`, `intentos.summary/evidence/closed_at` (idempotent). Backfill stays `attempts_authorized=0` = legacy/unbounded until a grant arms it (TCE2). [TCE2]
- [ ] 1.2 `persistence.py`: `CREATE TABLE IF NOT EXISTS attempt_grants` + `turn_bitacora` (append-only) in fresh DDL and migration. [TCE2, TT2]
- [ ] 1.3 `persistence.py`: methods `grant_attempts`, `get_attempt_budget`, `increment_attempts_used` (single atomic `UPDATE … WHERE used < authorized`), `append_bitacora` (INSERT-only), `complete_intento_with_summary`. [TT2, TCE2, M1]
- [ ] 1.4 `tests/test_persistence.py`: v5→v6 migration idempotency, **downgrade test** (open the v6 DB with v5 code, pre-existing data intact — I4), budget round-trip, bitácora append preserves prior rows. [TT2, TCE2]

## Phase 2: Turn enforcement & telemetry

- [ ] 2.1 `server.py` `begin_turn`: order validation, binding check, budget check for armed quests with `code="attempt_budget_exhausted"` and zero mutation; legacy quest (`authorized=0`, no grant) allowed; increment `attempts_used` **atomically** (single `UPDATE … WHERE used < authorized`, fail on 0 rows — M1). [TCE1, TCE2, TCE4, TSP1]
- [ ] 2.2 `server.py` `begin_turn`: internal checkpoint sub-step (best-effort, non-blocking); keep the existing done/missing quest guard (also the external-close reconciliation point, TCE3). [TT1, TT3, TSP2]
- [ ] 2.3 `server.py` `end_turn`: `summary: str = ""` optional param + deterministic `auto:<final_status> gates=<p>/<t>` fallback + `evidence.summary_source` (`caller`/`auto`, schema DASH4); set `closed_at`. [Req 3, D3, TT1, DASH4]
- [ ] 2.4 `server.py` `end_turn`: single SQLite transaction = append `turn_bitacora` + complete intento + mark item done (Deck-first, **only on a success verdict** — a `fail` leaves the quest open, TCE3); the bitácora append is **not** best-effort — on failure roll the TXN back and return a retryable error with the turn open; checkpoint mirror best-effort after commit. [TT1, TT2, TCE3, TSP3]
- [ ] 2.5 `tests/test_server.py`: budget hard-fail (no intento) + legacy/unbounded allowed then armed; order/binding fail; atomic closure (item+bitácora together, rollback on bitácora failure); checkpoint/mirror failure still completes; no-summary cycle still works; no telemetry read required for the cycle. [TCE1–4, TT1–4, TSP1, TSP3]

## Phase 3: Card surface & server-owned title

- [ ] 3.1 `server.py`: remove `@app.tool()` from `card_update_description` (keep function as internal helper). [MQM2]
- [ ] 3.2 `deck_bridge.py`/turn steps: own the description edit internally (Deck-first via `update_description`). [MQM1, MQM3, MQM4]
- [ ] 3.3 `deck_bridge.py`: render server-owned title `#{mission_id} {title}`, stripping caller `#…` prefixes on create/update; description-only edit strips then re-renders the prefix, title text unchanged. [Req 5, MQM4, D7]
- [ ] 3.4 `plugin_preflight.py`: block `mcp__nextcloud__deck_*` card ops; drop the L166 `card_update_description` guidance. [MQM1]
- [ ] 3.5 `tests/test_deck_bridge.py` + `test_server.py`: title prefix unforgeable; `card_update_description` absent from `tools/list` but importable; bridge-unavailable → explicit fail, no local-only write. [MQM1–4]

## Phase 4: Dashboard (API + UI)

Spec: `specs/dashboard-authorize/spec.md` (`DASH1–DASH5`).

- [ ] 4.1 `dashboard_server.py`: `POST /api/checklist/{item_id}/authorize_attempts` → insert grant + bump authorized (arms the budget), with input validation (`amount>0`, known `item_id`, non-empty `granted_by`) and grant+bump atomicity; human-gated, off the agent surface. [Req 6, DASH1, DASH2, DASH5]
- [ ] 4.2 `dashboard_server.py`: expose `attempts_authorized/used` on mission detail; `summary/evidence/closed_at` on intentos (evidence schema DASH4); add `GET /api/bitacora?mission_id=` (the explicit human-requested telemetry read). [Req 6, DASH3, DASH4, TT2, TT4]
- [ ] 4.3 `dashboard-astro`: "Authorize attempts" button (`ChecklistCard.jsx`), summary display (`IntentoCard.jsx`), bitácora view + `useApi.js` clients. [Req 6, DASH3]
- [ ] 4.4 `dashboard/app.js` + `index.html`: staging parity. [Req 6, DASH3]
- [ ] 4.5 `tests/test_dashboard*.py`: authorize increments/arms budget; validation (amount≤0, unknown item, empty granted_by) rejects with no mutation; grant+bump atomicity; agent tool catalog has no grant op; bitácora endpoint returns appended rows. [Req 6, DASH1, DASH2, DASH3, DASH5]

## Phase 5: Verification

- [ ] 5.1 `.venv/bin/pytest` full suite green; map each of the **20** requirements (TT1–4, TCE1–4, TSP1–3, MQM1–4, DASH1–5) to at least one passing test — including TT4 (no required telemetry read + human-requested read), TSP3 (internal sub-steps are not agent calls), and DASH2 (no grant op on the agent surface). [all]
- [ ] 5.2 Manual smoke: authorize → begin/end cycle → bitácora shows the appended turn; `fail` verdict leaves the quest open; invalid authorize (`amount=0`, unknown item) is rejected with no mutation.

## Phase 6: Docs

- [ ] 6.1 `README.md` / `README.en.md`: tool table drops `card_update_description`; document `summary`, budget (armed/legacy), bitácora. [MQM2]
- [ ] 6.2 `openspec/specs/.index.md`: register `turn-telemetry` and `turn-cycle-enforcement`. [TT, TCE]
