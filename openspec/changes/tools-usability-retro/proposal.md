# Proposal: Tools Usability Retro (Card #147)

## Intent

Hermes (the MCP client) struggles to use Ultratimonel's tool surface efficiently. Three retro items from Hermes brother #108 (2026-08-05) block smooth turn workflows: `mission_list` returns bloated payloads, there's no way to look up a checklist item by ID without fetching everything, and a bug in `begin_turn` causes `end_turn` gates to run against the wrong project ("unknown") when context extraction fails to match.

## Scope

### In Scope
- Add lightweight mission lookup: `mission_get(mission_id)` returning minimal fields (id, title, checklist_item_ids only)
- Add `checklist_item_get(checklist_item_id)` for direct ID-based lookup
- Add `include_description=false` opt-in to `mission_list` to skip heavy payload when not needed
- Fix `begin_turn` to prefer the explicit `project` parameter over context-extracted project, falling back to extracted only when parameter is empty/default
- Add integration test covering the begin_turn → end_turn project-persistence bug (intents #219–#225 pattern)

### Out of Scope
- Refactoring `mission_list` return shape for dashboard consumers (separate change)
- Adding search-by-text capabilities (future enhancement)
- Changing the `sync_tasks` / `sync_all` payload structure
- Any changes to gate logic itself (gates work correctly when project is right)

## Capabilities

### New Capabilities
- `mission-lookup`: Lightweight mission and checklist_item lookup tools (`mission_get`, `checklist_item_get`) plus optional lightweight mode for `mission_list`
- `begin-turn-project-fix`: Correct project resolution in `begin_turn` to use explicit parameter over context extraction

### Modified Capabilities
- `mission-gate`: `begin_turn` requirement F-MG-12 (project extraction) — SHALL prefer explicit `project` param over `context["project"]`; gate validation in `end_turn` SHALL use the persisted project from the intento record (already correct, but bug prevented it from being right)

## Approach

1. **Lightweight lookup tools**: Add `mission_get(mission_id: int)` and `checklist_item_get(checklist_item_id: int)` to `server.py`. Both query the DB directly and return minimal JSON (no descriptions, no nested items unless requested).
2. **`mission_list` light mode**: Add optional `include_description: bool = False` parameter. When false, omit `description` field and skip fetching nested `checklist_items` (return only `[{"id": ..., "item_index": ..., "text": ...}]` or just IDs).
3. **Project fix in `begin_turn`**: At line 1255 of `server.py`, change `resolved_project = context["project"]` to prefer the explicit `project` parameter: if `project` arg is non-empty and not the default empty string, use it; otherwise fall back to `context["project"]`. This ensures Hermes' explicit project wins over heuristic topic matching.
4. **Tests**: Add test in `tests/test_server.py` that calls `begin_turn(project="voy-rojo", ...)` then `end_turn(intento_id=...)` and asserts gates are validated against "voy-rojo" not "unknown".

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `ultratimonel/server.py` | Modified | Add 2 new tools, modify `mission_list` sig, fix project resolution in `begin_turn` |
| `ultratimonel/persistence.py` | Modified | Add `get_mission_by_id()` and `get_checklist_item_by_id()` query methods |
| `tests/test_server.py` | Modified | Add project-persistence bug regression test |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Breaking dashboard consumers of `mission_list` when adding `include_description` param | Low | Param is optional with default `False` — existing callers get full payload; dashboard can opt into light mode later in a follow-up |
| New tools expose internals to Hermes that weren't intended | Low | Tools are internal MCP — only Hermes calls them; minimal fields reduce attack surface vs full payloads |
| Project fix changes behavior for current non-Hermes callers who rely on context extraction | Medium | Any caller passing explicit `project=""` gets fallback to context extraction; only callers passing a real project string change behavior, and that's the *correct* behavior |

## Rollback Plan

All changes are additive (new tools) or narrow parameter fixes. To rollback:
1. Revert commit on `feature_147_tools-usability-retro` branch.
2. New tools are harmless no-ops if not called; removing them requires only deleting the function defs and persistence methods.
3. The `begin_turn` project fix is a one-line change — revert to `resolved_project = context["project"]`.

## Dependencies

- None external. Self-contained within Ultratimonel codebase.

## Success Criteria

- [ ] `mission_get(123)` returns mission with id/title only (no description, no nested items) in <5ms
- [ ] `checklist_item_get(456)` returns the item by ID or clear "not found" error
- [ ] `mission_list(project, include_description=false)` omits description and checklist_items from response
- [ ] `begin_turn(project="voy-rojo", ...)` persists intento with project="voy-rojo" even when context extraction would return "unknown"
- [ ] `end_turn(intento_id)` validates gates against the persisted project (not "unknown")
- [ ] Regression test passes: begin_turn with explicit project → end_turn gates run against correct project
