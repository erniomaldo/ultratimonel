# Proposal: Assert Gates Deprecation (Card #150)

## Intent

`assert_gates` was originally the gate-step tool for the pre-flight flow: Hermes called it before each turn to run the 4 gates. The consolidated 2-call flow (`begin_turn` → trabajo → `end_turn`, Cards #147/#148) made that step redundant: `begin_turn` now executes the 4 gates **internally** (fresh assert) and persists the snapshot in the intento.

Keeping `assert_gates` exposed as a normal agent-facing tool is actively harmful: the plugin already executes it automatically on every turn (`on_session_start`, `pre_llm_call`), so an agent-side call duplicates the gate run; and the plugin bouncer's own messages still instruct the agent to call `assert_gates()` when gates are missing (`_gates_bouncer`, lines 103–155), which conflicts with the consolidated flow. The correct contract is: **do not use `assert_gates` as an agent step** — the plugin invokes it internally and that is its only legitimate remaining caller.

This change deprecates `assert_gates` retroactively over the diff already present in the working tree: the tool remains registered and functional (compatibility with the plugin), its docstring becomes `~~DEPRECATED~~` with a pointer to `begin_turn()`, and it moves to the "Legacy / archived tools" section of `server.py` alongside `record_intento` and `complete_intento`. Documentation (ES/EN READMEs) reflects the new counts and documents `mission_get` / `checklist_item_get`, correcting a previous judgment finding: the real tool count is **20** (17 active + 3 legacy), verifiable with `app.list_tools()`.

## Scope

### In Scope
- Deprecate `assert_gates` in `ultratimonel/server.py`:
  - Move the tool to the "Legacy / archived tools" section (after `end_turn`)
  - Add `~~DEPRECATED~~` marker and replacement guidance to its docstring
  - Keep signature and behavior identical (still registered with `@app.tool()`, still invoked by the plugin in `pre_llm_call`)
- Update `README.md` and `README.en.md`:
  - Tool count 18 → 20 (17 active + 3 legacy), everywhere it appears (diagram, feature table, tools section, file tree)
  - Move `assert_gates` from "Núcleo (Gates)" to "Legacy / Archivadas"
  - Document `mission_get` and `checklist_item_get` in the Misiones/Deck Sync section

### Out of Scope
- Removing `assert_gates` (plugin compatibility — `pre_llm_call` still calls it)
- Changing `assert_gates` behavior, signature, or persistence logic
- Any change to `begin_turn` / `end_turn` / plugin bouncer logic
- `openspec/changes/dashboard-astro-migration/` — dashboard migration (card #154), separate PR

## Capabilities

### New Capabilities
- `assert-gates-deprecation`: Retrospective documentation of the `assert_gates` deprecation and the corrected tool inventory

### Modified Capabilities
- `mission-gate`: The gate-step tool set. `assert_gates` is re-classified from active core tool to legacy (kept for compatibility, not for agent use). `begin_turn` remains the replacement (executes the 4 gates internally).

## Approach

1. **Server deprecation** (already applied in working tree): move the `assert_gates` handler below `end_turn` under the `Legacy / archived tools` section header; prepend `~~DEPRECATED~~` to the docstring with an explicit pointer to `begin_turn()` and a warning that the plugin bouncer treats it as the gate step. No behavioral changes — body, signature, return shape untouched.
2. **Documentation** (already applied in working tree): correct every hardcoded tool count to 20 (17 active + 3 legacy), move `assert_gates` to the legacy table, add `mission_get` / `checklist_item_get` rows to the Misiones/Deck Sync section in both ES and EN READMEs.
3. **Verification**: requirements are verifiable against the working tree (grep for `@app.tool()` count = 20, `DEPRECATED` docstring markers, README counts, plugin invocations of `assert_gates`).

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `ultratimonel/server.py` | Modified | `assert_gates` moved to legacy section, docstring deprecated, signature/behavior unchanged |
| `README.md` | Modified | Tool count 18→20 (17+3), `assert_gates` to legacy table, add `mission_get`/`checklist_item_get` rows |
| `README.en.md` | Modified | Same corrections in English |
| `ultratimonel/plugin_preflight.py` | Unchanged | Still invokes `assert_gates` in `on_session_start` / `pre_llm_call` — the compatibility reason for not removing the tool |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Hermes keeps calling `assert_gates` as an agent step despite deprecation | Medium | Docstring warning + README legacy classification; plugin bouncer behavior already guards turn state |
| Removing the tool later without checking plugin callers | Low (future) | Kept registered for now; removal is explicitly out of scope and requires a plugin migration first |
| README counts drift again | Low | Spec requirement ties count to `app.list_tools()` (20) — verifiable at review time |

## Rollback Plan

Not applicable to production code (no runtime behavior changed): the diff is a move + docstring edit in `server.py` and README content. To rollback: restore `assert_gates` to its original location/status and revert README counts — no data or gate-state impact.

## Dependencies

- None external. Self-contained within Ultratimonel.

## Success Criteria

- [ ] `assert_gates` still registered and functional (tests calling it pass; plugin `pre_llm_call` still works)
- [ ] `assert_gates` docstring contains `~~DEPRECATED~~` and points to `begin_turn()`
- [ ] `assert_gates` lives in the "Legacy / archived tools" section of `server.py`
- [ ] `@app.tool()` count in `server.py` is 20; exactly 3 docstrings carry `DEPRECATED`
- [ ] `README.md` and `README.en.md` state **20 MCP tools: 17 active + 3 legacy** consistently
- [ ] `mission_get` and `checklist_item_get` documented in the Misiones/Deck Sync section of both READMEs
- [ ] `plugin_preflight.py` still calls `assert_gates` without breaking
- [ ] Dashboard-astro-migration change untouched
