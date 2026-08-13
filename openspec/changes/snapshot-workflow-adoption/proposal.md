# Proposal: Snapshot Workflow Adoption (Card #150)

## Intent

Adopt the snapshot workflow used by the other Hermes instance: skills and plugins are synced into the snapshot (derived state) from their sources of truth, and the `ultratimonel-preflight` plugin hook signatures are corrected to match the runtime convention. The repo remains the source of truth for everything it owns.

Current gaps documented by this change:

1. **Skill sync desync** — `skills/ultratimonel-ciclo-basico` and `skills/protocolo-de-trazabilidad` differ between the repo and the snapshot; `opencode` and `pipeline-determinista-ui-code` are missing from the snapshot entirely.
2. **Plugin hook signature bug** — `_gates_bouncer` and `_post_turn_guard` in `ultratimonel/plugin_preflight.py` declare `ctx` as first parameter; the adopted Hermes runtime convention does not pass `ctx` to hooks.
3. **External dependency version decision** — `custom-dangerous-patterns` is unpinned between 0.3.4 and 1.6.0 in the Hermes runtime, but it is NOT a repo dependency (absent from `requirements.txt` and `pyproject.toml`). This change records the decision in docs only; there is no repo manifest to pin.
4. **Client parameterization already implemented (uncommitted post-state)** — the working tree's `ultratimonel_client.py` already resolves the MCP server via `ULTRATIMONEL_MCP_CMD`/`ULTRATIMONEL_MCP_ARGS` with fallback to `_hermes_mcp_config()` (`~/.hermes/config.yaml`) and finally `sys.executable`. This change documents that post-state instead of planning new code.
5. **Post-change verification** — no checklist exists to prove the snapshot is consistent after the change.

## Scope

### In Scope

- Sync repo-owned skills (`ultratimonel-ciclo-basico`, `protocolo-de-trazabilidad`) from repo → snapshot (`~/.hermes/skills/` per README)
- Add missing skills (`opencode`, `pipeline-determinista-ui-code`) to the snapshot
- Fix preflight hook signatures: remove `ctx` as first parameter from `_gates_bouncer` and `_post_turn_guard`
- Bump `plugin.yaml` to 2.0.1 and align the `register()` log message ("Plugin v2.0" → "v2.0.1")
- Record the `custom-dangerous-patterns` version decision in docs (0.3.4 default; docs-only — no repo manifest exists to pin)
- Document the already-implemented client parameterization (`ULTRATIMONEL_MCP_CMD`/`ULTRATIMONEL_MCP_ARGS` + `_hermes_mcp_config()` fallback) as post-state — no new code
- Post-change verification (py_compile, hook signature check + runtime smoke check, snapshot diff, test suite via `.venv/bin/pytest`)

### Out of Scope

- Changes to Ultratimonel server logic or MCP tools
- Changes to the other Hermes instance or its snapshot tooling (adopted, not re-implemented)
- Building a generic snapshot/sync tool inside this repo
- Any behavior change to gate logic, bouncer rules, or turn guard semantics

## Capabilities

### New Capabilities

- `snapshot-workflow`: Repo→snapshot skill sync + preflight plugin hook signature alignment + dependency version pinning + optional client path parameterization

### Modified Capabilities

- None (no existing capability spec changes)

## Approach

1. **Skill sync (repo → snapshot):** Copy `skills/ultratimonel-ciclo-basico` and `skills/protocolo-de-trazabilidad` into the snapshot. Repo is source of truth, per README rule ("NUNCA editar la copia instalada") and ADR-007 of change `plugin-preflight-sync`. Diff first to detect drift. Copy the missing `opencode` and `pipeline-determinista-ui-code` skills into the snapshot from their canonical sources (source paths confirmed during tasks).
2. **Hook signature fix:** In `ultratimonel/plugin_preflight.py`, remove `ctx` from `_gates_bouncer` and `_post_turn_guard` (see design ADR-2 for before/after signatures). `_on_session_start` and `_pre_llm_call` already follow the convention — verify only.
3. **Version decision (docs-only):** Record the `custom-dangerous-patterns` decision (0.3.4 default, flip to 1.6.0 only after validation) in design ADR-3 + README. The dependency is absent from the repo manifests, so no repo pin is performed.
4. **Client parameterization (post-state, no new code):** The working tree already implements `ULTRATIMONEL_MCP_CMD`/`ULTRATIMONEL_MCP_ARGS` with fallback to `_hermes_mcp_config()` and `sys.executable` (see design ADR-4). This change documents the behavior and verifies `.env.example` covers the vars.
5. **Post-change verification:** `py_compile` on modified files, hook signature inspection + runtime smoke check (`.venv/bin/python`), diff repo vs snapshot skills, run the existing test suite via `.venv/bin/pytest`.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `skills/ultratimonel-ciclo-basico/SKILL.md` | Sync | Re-copy from repo to snapshot (drift reviewed before copy) |
| `skills/protocolo-de-trazabilidad/SKILL.md` | Sync | Re-copy from repo to snapshot (same as above) |
| Snapshot `opencode` + `pipeline-determinista-ui-code` | Add | Copy missing skills into snapshot |
| `ultratimonel/plugin_preflight.py` | Modified | Remove `ctx` first param from `_gates_bouncer` + `_post_turn_guard` |
| `ultratimonel/plugin.yaml` | Modified | Version bump to 2.0.1 reflecting hook signature fix; `register()` log message aligned to v2.0.1 |
| `ultratimonel/ultratimonel_client.py` | Post-state (already implemented, uncommitted in working tree) | Document existing `ULTRATIMONEL_MCP_CMD`/`ULTRATIMONEL_MCP_ARGS` + `_hermes_mcp_config()` resolution — NO new code in this change |
| `.env.example` | Already untracked in working tree | Documents the MCP/Nextcloud/checkpoint env vars; decision needed: include in this PR or keep out |
| `README.md` | Modified | Document snapshot workflow (skills + plugin + anti-desync rule) |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Snapshot overwrites newer runtime-only fixes (desync recurrence) | Medium | Keep repo as source of truth; diff before copy; copy only repo → snapshot, never reverse |
| Hook signature change breaks runtime if a Hermes version still passes `ctx` | Low | Signature fix aligns with the adopted runtime convention (other Hermes snapshot already corrected); runtime smoke check operationalized in design §5.2 / S8 / T6 |
| `custom-dangerous-patterns` decision is wrong for the runtime | Medium | Record decision in ADR-3 + README; validate before flipping from 0.3.4 to 1.6.0 (no repo manifest pin exists — decision is docs-only) |
| Missing skills source unavailable at copy time | Low | Task fails loudly with clear error; snapshot diff verification catches absence; T2 has a concrete fallback source |

## Rollback Plan

1. Revert the fix commit on the working branch.
2. Restore previous snapshot contents (backup before sync or from git history).
3. Hook signature fix is a 2-line change per function — revert removes the `ctx` params.
4. Version pin revert restores the previous unpinned state.

## Dependencies

- None external. Skill sources for `opencode` and `pipeline-determinista-ui-code` must be available at copy time.

## Success Criteria

- [ ] `skills/ultratimonel-ciclo-basico` and `skills/protocolo-de-trazabilidad` in the snapshot are byte-identical to the repo (diff empty)
- [ ] Snapshot contains all 4 skills: `ultratimonel-ciclo-basico`, `protocolo-de-trazabilidad`, `opencode`, `pipeline-determinista-ui-code`
- [ ] `_gates_bouncer` and `_post_turn_guard` have no `ctx` parameter; `_on_session_start` and `_pre_llm_call` verified clean
- [ ] `plugin.yaml` version reflects the fix (2.0.1) and the `register()` log message says v2.0.1
- [ ] `custom-dangerous-patterns` decision recorded in design.md ADR-3 + README (docs-only — no repo manifest exists to pin)
- [ ] Client parameterization documented matches the implementation (`ULTRATIMONEL_MCP_CMD`/`ULTRATIMONEL_MCP_ARGS` + `_hermes_mcp_config()` fallback)
- [ ] `py_compile` passes on `plugin_preflight.py` and `ultratimonel_client.py` (`.venv/bin/python`)
- [ ] Runtime smoke check passes: import plugin, register hooks, exercise `_gates_bouncer`/`_post_turn_guard` with the new signatures
- [ ] Existing test suite passes via `.venv/bin/pytest` (no behavior change)
- [ ] README documents the snapshot workflow and the anti-desync rule
