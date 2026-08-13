# Tasks: Snapshot Workflow Adoption (Card #150)

> **Change:** `snapshot-workflow-adoption` · **Date:** 2026-08-12
> **Inputs:** [proposal.md](./proposal.md) · [spec.md](./specs/snapshot-workflow/spec.md) · [design.md](./design.md)
> **Branch:** `feature_147_tools-usability-retro` (working branch — no checkout needed)

---

## Review Workload Forecast

| Task | Files changed | Est. lines | Risk |
|------|--------------|------------|------|
| T1 — Sync repo skills → snapshot | snapshot only (copy to `~/.hermes/skills/`) | ~0 (copy) | Low |
| T2 — Add missing skills to snapshot | snapshot only (copy); **blocked-by-decision** (confirm source) | ~0 (copy) | Medium |
| T3 — Fix hook signatures (remove ctx) + log v2.0.1 | 2 | ~10 | Low |
| T4 — Document client parameterization (post-state, no code) | 1 (.env.example / docs) | ~10 | Low |
| T5 — Record custom-dangerous-patterns decision (docs-only) | design.md ADR-3 + README | ~5 | Medium |
| T6 — Post-change verification (incl. runtime smoke check) | none (checks) | ~0 | Low |
| T7 — README snapshot workflow docs | 1 | ~40 | Low |
| **Total (this change's planned diff)** | **~3 repo files** | **~65 lines** | — |

**Pre-existing working tree (NOT planned by this change — declared explicitly):**
`ultratimonel/ultratimonel_client.py` (+96/−8, parameterization already implemented, uncommitted) and `.env.example` (untracked) predate this change. They are NOT part of this change's planned diff. Decision required at apply time: include them in this PR as post-state capture (ADR-4), or commit them separately. If included, add ~126 lines to the forecast (still under the 400-line budget).

**Forecast: ~65 changed lines from this change's own tasks (docs + 2 signature edits), plus ~126 pre-existing working-tree lines if included in the PR.** Under 400-line review budget. No chained PRs needed (single PR, strategy C2).

---

## Dependency Graph

```
T3 (hook signatures) ──► T6 (verification includes signature check + smoke check)
T1, T2 (skill sync) ────► T6 (verification includes snapshot diff)
T5 (version decision) ──► T6 (verification validates docs record)
T4 (post-state docs) ───► T6
T6 (verification) ──────► T7 (README documents verified state)
```

**Recommended sequential order:** T3 → T1 → T2 → T5 → T4 → T6 → T7

---

## Tasks

### T1 — Sync repo-owned skills to snapshot (F-SW-01, NF-SW-02)

**Files:** snapshot skills dir (`~/.hermes/skills/` — external), `skills/ultratimonel-ciclo-basico/SKILL.md`, `skills/protocolo-de-trazabilidad/SKILL.md`

**What:** Copy `ultratimonel-ciclo-basico` and `protocolo-de-trazabilidad` from the repo into the snapshot at `~/.hermes/skills/`. The repo is the source of truth; the snapshot is derived state (ADR-1). Diff first to detect desync, then copy.

**How:**
1. `diff -r skills/ultratimonel-ciclo-basico ~/.hermes/skills/ultratimonel-ciclo-basico` — record any drift
2. `diff -r skills/protocolo-de-trazabilidad ~/.hermes/skills/protocolo-de-trazabilidad` — record any drift
3. `cp -r skills/ultratimonel-ciclo-basico ~/.hermes/skills/` and same for `protocolo-de-trazabilidad`
4. Confirm `diff -r` is now empty

**Done when:**
- [ ] Snapshot skills are byte-identical to repo skills (diff empty)
- [ ] Drift (if any) reported in apply-progress

---

### T2 — Add missing skills to snapshot (F-SW-02) — BLOCKED-BY-DECISION (source confirmation)

**Files:** snapshot skills dir (`~/.hermes/skills/` — external)

**What:** Copy `opencode` and `pipeline-determinista-ui-code` from their canonical sources into `~/.hermes/skills/`.

**Source default (design.md §7, resolved):** primary = skills dir of the OTHER Hermes snapshot — the other machine/other user's `~/.hermes/skills/` (e.g., `hermes@otra-maquina:~/.hermes/skills/opencode`), NEVER the local `~/.hermes/skills/` (the local path is the snapshot DESTINATION of this change). Fallback = the canonical upstream repos. The executor MUST confirm the actual source path at apply time and confirm `source != destination` before any `cp`, recording both in apply-progress (this task is blocked until that decision is recorded).

**How:**
1. Confirm canonical source path for each skill (see source default above); assert `source != destination` (source is the other Hermes, never the local `~/.hermes/skills/` destination); record both in apply-progress BEFORE copying
2. `cp -r <source>/opencode ~/.hermes/skills/` and `cp -r <source>/pipeline-determinista-ui-code ~/.hermes/skills/`
3. `ls ~/.hermes/skills/` — assert 4 skills present

**Done when:**
- [ ] Canonical source path confirmed and recorded in apply-progress
- [ ] `source != destination` confirmed and recorded in apply-progress (source is the other Hermes snapshot, not the local `~/.hermes`)
- [ ] Snapshot contains `opencode` and `pipeline-determinista-ui-code`
- [ ] Snapshot contains all 4 skills (F-SW-02)

---

### T3 — Fix preflight hook signatures (F-SW-03, F-SW-04, F-SW-05, F-SW-08, NF-SW-01)

**Files:** `ultratimonel/plugin_preflight.py`, `ultratimonel/plugin.yaml`

**What:** Remove `ctx` as first parameter from `_gates_bouncer` and `_post_turn_guard`. Verify `_on_session_start` and `_pre_llm_call` are already clean. Bump `plugin.yaml` to 2.0.1 and align the `register()` log message ("Plugin v2.0" → "v2.0.1").

**How:**
1. In `plugin_preflight.py`:
   ```python
   def _gates_bouncer(tool_name: str, args: dict, **kwargs) -> dict | None:
   def _post_turn_guard(tool_name: str, args: dict, result: dict, **kwargs) -> dict | None:
   ```
2. Verify no hook body references `ctx` (grep)
3. In `plugin_preflight.py` `register()`: change log message `"Plugin v2.0 registered"` → `"Plugin v2.0.1 registered"` (cosmetic — reflects the bump, Juez A note 3)
4. In `plugin.yaml`: `version: 2.0.1`
5. `.venv/bin/python -m py_compile ultratimonel/plugin_preflight.py`

**Done when:**
- [ ] Signatures have no `ctx` (inspect)
- [ ] No hook body references `ctx`
- [ ] `plugin.yaml` at 2.0.1
- [ ] `register()` log message says `v2.0.1`
- [ ] `py_compile` passes (`.venv/bin/python`)

---

### T4 — Document client parameterization (post-state, no code) (F-SW-07, ADR-4)

**Files:** `ultratimonel/ultratimonel_client.py` (read-only — already implemented), `.env.example` (already untracked), docs

**What:** The working tree already implements `ULTRATIMONEL_MCP_CMD`/`ULTRATIMONEL_MCP_ARGS` resolution with fallback to `_hermes_mcp_config()` (`~/.hermes/config.yaml`) and finally `sys.executable`. This task DOCUMENTS the post-state and verifies `.env.example` covers the vars — NO code change. The obsolete `ULTRATIMONEL_HERMES_HOME` from the old plan is NOT implemented and must NOT be added.

**How:**
1. Verify `ultratimonel_client.py` resolution order matches the docs (env var → `_hermes_mcp_config()` → portable)
2. Verify `.env.example` documents `ULTRATIMONEL_MCP_CMD`/`ULTRATIMONEL_MCP_ARGS` (+ Nextcloud/checkpoint vars) — decision at apply time: include `.env.example` in the PR or keep it out (Review Workload Forecast)
3. `.venv/bin/python -m py_compile ultratimonel/ultratimonel_client.py` (existing state, no changes)

**Done when:**
- [ ] Docs describe the implemented resolution order (env var → Hermes config → portable)
- [ ] `.env.example` covers `ULTRATIMONEL_MCP_CMD`/`ULTRATIMONEL_MCP_ARGS`
- [ ] Decision recorded in apply-progress: `.env.example` in or out of the PR
- [ ] `py_compile` passes (existing state)

---

### T5 — Record custom-dangerous-patterns decision (docs-only) (F-SW-06, ADR-3)

**Files:** `design.md` (ADR-3), `README.md` — NO repo manifest pin

**What:** The dependency is NOT present in the repo manifests (`requirements.txt`/`pyproject.toml` — verified), so there is no repo manifest to pin. Record the decision (default 0.3.4; flip to 1.6.0 only after validation) in ADR-3 + README. At apply time, confirm the actual version used by the other Hermes snapshot and update the documented decision with that evidence.

**How:**
1. Confirm which version the other Hermes snapshot uses (evidence for the docs)
2. Record the decision in design.md ADR-3 (update from "default" to "confirmed" if evidence exists) — no code, no manifest changes
3. Reference the decision in README (snapshot workflow section)
4. `grep -rn "custom-dangerous-patterns" requirements.txt pyproject.toml` — assert no repo manifest exists to pin (expected: no matches)

**Done when:**
- [ ] Decision recorded in ADR-3 + README (docs-only)
- [ ] No repo manifest pin attempted (dependency absent from repo manifests)
- [ ] Confirmed version (if found) noted in ADR-3

---

### T6 — Post-change verification (F-SW-09)

**Files:** none (checks)

**What:** Run the verification checklist from design.md section 5, using the venv interpreter (pytest 9.1.1 lives in `.venv`; plain `python -m pytest` may not resolve it).

**How:**
1. `.venv/bin/python -m py_compile ultratimonel/plugin_preflight.py ultratimonel/ultratimonel_client.py`
2. Runtime smoke check (operationalizes ADR-2; fails loudly while the `ctx` fix is not applied):
   ```bash
   .venv/bin/python - <<'PY'
   import inspect, types
   from ultratimonel import plugin_preflight as p
    assert 'ctx' not in inspect.signature(p._gates_bouncer).parameters
    assert 'ctx' not in inspect.signature(p._post_turn_guard).parameters
    # F-SW-05/S5: unmodified hooks must also not receive ctx (verify only)
    assert 'ctx' not in inspect.signature(p._on_session_start).parameters
    assert 'ctx' not in inspect.signature(p._pre_llm_call).parameters
    ctx = types.SimpleNamespace(register_hook=lambda *a, **k: None)
   p.register(ctx)
   assert p._gates_bouncer('write_file', {}).get('action') == 'block'
   assert p._post_turn_guard('mcp__ultratimonel__end_turn', {}, {}) is None
   assert p._post_turn_guard('write_file', {}, {}) is not None
   print('SMOKE OK')
   PY
   ```
3. `diff -r skills/ultratimonel-ciclo-basico ~/.hermes/skills/ultratimonel-ciclo-basico` and same for `protocolo-de-trazabilidad` → empty
4. `ls ~/.hermes/skills/` → 4 skills
5. Run existing suite: `.venv/bin/pytest tests/ -q --tb=short`
6. Confirm `openspec/config.yaml` testing block aligned (framework `pytest`, command `.venv/bin/pytest`)

**Done when:**
- [ ] All checks pass
- [ ] Any failure documented with evidence in verify-report

---

### T7 — README snapshot workflow docs

**Files:** `README.md`

**What:** Document the snapshot workflow: repo → snapshot sync, anti-desync rule, the 4 skills, and the preflight hook convention.

**How:**
1. Extend the "Instalar las skills del proyecto" section with the snapshot workflow
2. Add the anti-desync rule (repo source of truth, one-directional copy)
3. Reference the plugin signature convention

**Done when:**
- [ ] README documents the snapshot workflow and the 4 skills
- [ ] Anti-desync rule present

---

## Execution Order

| Step | Task | Depends on | Estimated effort |
|------|------|------------|-----------------|
| 1 | T3 — Hook signature fix | None | ~15 min |
| 2 | T1 — Sync repo skills | None | ~10 min |
| 3 | T2 — Add missing skills (blocked-by-decision: confirm source) | None | ~10 min |
| 4 | T5 — Record version decision (docs-only) | None | ~10 min |
| 5 | T4 — Document client parameterization (post-state) | None | ~10 min |
| 6 | T6 — Verification (incl. smoke check) | T1+T2+T3+T5+T4 | ~15 min |
| 7 | T7 — README docs | T6 | ~15 min |

**Total estimated: ~85 min. All tasks under 400-line review budget.**

**Note:** the pre-existing working-tree changes (`ultratimonel_client.py` +96/−8, `.env.example` untracked) are NOT tasks of this change — they predate it. Their inclusion in the PR is a decision to record in apply-progress (see Review Workload Forecast).
