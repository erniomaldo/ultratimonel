# Tasks: cards-deterministas

## Review Workload Forecast

| Field | Value |
|-------|-------|
| Estimated changed lines | ~900–1300 total, split into 5 PRs ≤400 each |
| 400-line budget risk | Low (per PR) |
| Chained PRs recommended | Yes |
| Suggested split | S1 persistence → S2 turn-enforcement → S3 card-surface → S4 dashboard → S5 docs |
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

### PR Chain (Feature Branch Chain)

**Tracker**: `feature_2389_cards-deterministas` → `main` (draft / no-merge until the chain completes).

| PR | Branch | Base | Scope | Est. lines |
|----|--------|------|-------|------------|
| S1 | `feature_2389_s1_persistence` | tracker | Model v5→v6: DDL + methods + tests | ~200–280 |
| S2 | `feature_2389_s2_turn-enforcement` | S1 | begin/end + telemetry/bitácora + tests | ~250–380 |
| S3 | `feature_2389_s3_card-surface` | S2 | `card_update_description` out of catalog + internal edit + server-owned title + plugin blocks `deck_*` + tests | ~200–320 |
| S4 | `feature_2389_s4_dashboard` | S3 | API (authorize_attempts/budget/bitácora) + UI + tests | ~200–320 |
| S5 | `feature_2389_s5_docs` | S4 | READMEs + specs index | ~50–100 |

**Dependency diagram** (📍 = next PR to create):

```text
main
 └── feature_2389_cards-deterministas            tracker (draft/no-merge)
      └── 📍 S1 feature_2389_s1_persistence        base: tracker   ~200–280
           └── S2 feature_2389_s2_turn-enforcement base: S1        ~250–380
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
| 2 | Turn enforcement + telemetry/bitácora | S2 | Depends on S1 |
| 3 | Card surface internalized + server-owned title | S3 | Depends on S2 |
| 4 | Dashboard API + UI | S4 | Depends on S3 |
| 5 | Docs | S5 | Depends on S4 |

## Phase 1: Data model & migration

- [x] 1.1 `persistence.py`: bump `SCHEMA_VERSION` 5→6; `_migrate_v5_to_v6` adding `checklist_items.attempts_authorized/attempts_used`, `intentos.summary/evidence/closed_at` (idempotent). [TCE2]
- [x] 1.2 `persistence.py`: `CREATE TABLE IF NOT EXISTS attempt_grants` + `turn_bitacora` (append-only) in fresh DDL and migration. [TCE2, TT2]
- [x] 1.3 `persistence.py`: methods `grant_attempts`, `get_attempt_budget`, `increment_attempts_used`, `append_bitacora` (INSERT-only), `complete_intento_with_summary`. [TT2, TCE2]
- [x] 1.4 `tests/test_persistence.py`: v5→v6 migration idempotency, budget round-trip, bitácora append preserves prior rows. [TT2, TCE2]

## Phase 2: Turn enforcement & telemetry

- [ ] 2.1 `server.py` `begin_turn`: order validation, binding check, budget check with `code="attempt_budget_exhausted"` and zero mutation; then increment `attempts_used`. [TCE1, TCE2, TCE4, TSP1]
- [ ] 2.2 `server.py` `begin_turn`: internal checkpoint sub-step (best-effort, non-blocking); keep the existing done/missing quest guard. [TT1, TT3, TSP2]
- [ ] 2.3 `server.py` `end_turn`: `summary: str = ""` optional param + deterministic `auto:` fallback; set `closed_at`. [Req 3, D3]
- [ ] 2.4 `server.py` `end_turn`: single SQLite transaction = mark item (Deck-first) + append `turn_bitacora` + complete intento; checkpoint mirror best-effort after commit. [TT1, TT2, TCE3]
- [ ] 2.5 `tests/test_server.py`: budget hard-fail (no intento), order/binding fail, atomic closure (item+bitácora together), telemetry failure still completes, no-summary cycle still works. [TCE1–4, TT1–3, TSP1]

## Phase 3: Card surface & server-owned title

- [ ] 3.1 `server.py`: remove `@app.tool()` from `card_update_description` (keep function as internal helper). [MQM2]
- [ ] 3.2 `deck_bridge.py`/turn steps: own the description edit internally (Deck-first via `update_description`). [MQM1, MQM3, MQM4]
- [ ] 3.3 `deck_bridge.py`: render server-owned title `#{mission_id} {title}`, stripping caller `#…` prefixes on create/update. [Req 5, D7]
- [ ] 3.4 `plugin_preflight.py`: block `mcp__nextcloud__deck_*` card ops; drop the L166 `card_update_description` guidance. [MQM1]
- [ ] 3.5 `tests/test_deck_bridge.py` + `test_server.py`: title prefix unforgeable; `card_update_description` absent from `tools/list` but importable; bridge-unavailable → explicit fail, no local-only write. [MQM1–4]

## Phase 4: Dashboard (API + UI)

- [ ] 4.1 `dashboard_server.py`: `POST /api/checklist/{item_id}/authorize_attempts` → insert grant + bump authorized. [Req 6, TCE2]
- [ ] 4.2 `dashboard_server.py`: expose `attempts_authorized/used` on mission detail; `summary/evidence/closed_at` on intentos; add `GET /api/bitacora?mission_id=`. [Req 6, TT2]
- [ ] 4.3 `dashboard-astro`: "Authorize attempts" button (`ChecklistCard.jsx`), summary display (`IntentoCard.jsx`), bitácora view + `useApi.js` clients. [Req 6]
- [ ] 4.4 `dashboard/app.js` + `index.html`: staging parity. [Req 6]
- [ ] 4.5 `tests/test_dashboard*.py`: authorize increments budget; bitácora endpoint returns appended rows. [Req 6]

## Phase 5: Verification

- [ ] 5.1 `.venv/bin/pytest` full suite green; map each of the 15 requirements to at least one passing test. [all]
- [ ] 5.2 Manual smoke: authorize → begin/end cycle → bitácora shows the appended turn.

## Phase 6: Docs

- [ ] 6.1 `README.md` / `README.en.md`: tool table drops `card_update_description`; document `summary`, budget, bitácora. [MQM2]
- [ ] 6.2 `openspec/specs/.index.md`: register `turn-telemetry` and `turn-cycle-enforcement`. [TT, TCE]
