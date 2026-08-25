# Proposal: Plugin Preflight Context & Environment Fixes

## Intent

Document retroactive fixes applied in commit 484e42f to establish audit trail. Three critical changes were made: (1) plugin hook signatures corrected with `ctx=None` default causing TypeError and breaking all gate enforcement, (2) MCP client spawning without PATH/HOME environment preventing gates 1a/1b from executing external tools successfully, and (3) `mcp__ultratimonel__begin_turn` initially added to TOOLS_REQUIRING_VERIFIED_GATES in commit 484e42f but was SUPERSEDED by PR #19 (commit 2e6c5e5, enforcement-v3 branch): begin_turn is now EXEMPT from the bouncer to prevent deadlock.

## Scope

### In Scope
- Document the three fixes applied in commit 484e42f: (1) hook signatures with `ctx=None`, (2) MCP client environment merge, (3) `mcp__ultratimonel__begin_turn` initially added to TOOLS_REQUIRING_VERIFIED_GATES but superseded by PR #19 making it EXEMPT from the bouncer
- Record technical details of plugin_preflight.py hook signature corrections
- Record ultratimonel_client.py MCP spawn environment merge fix
- Document begin_turn exemption logic in _gates_bouncer to prevent deadlock (R3.1)

### Out of Scope
- Modifying WIP dashboard*/combat_ws_server directories
- Any additional code changes or commits
- Creating new specs (bug fixes with no spec-level behavior change)

## Capabilities

> This section is the CONTRACT between proposal and specs phases. The sdd-spec agent reads this to know exactly which spec files to create or update. Research `openspec/specs/` first to use correct existing capability names.

### New Capabilities
None — bug fix only, no new capabilities introduced.

### Modified Capabilities
None — fixes correct implementation bugs; no requirement changes at spec level. The mission-gate specification remains unchanged as it already defines the expected behavior that these fixes enable.

## Approach

Document retroactively as audit trail of production fixes. No forward implementation required — code is already deployed and verified in main branch. Focus on capturing:
- Root cause analysis (hook signatures, missing env vars)
- Fix implementation details (default args, environment merge)
- Production verification results

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `ultratimonel/plugin_preflight.py` | Fixed | Hook functions `_gates_bouncer()` and `_post_turn_guard()` corrected with `ctx=None` default parameter AND `mcp__ultratimonel__begin_turn` EXEMPT from bouncer (removed from TOOLS_REQUIRING_VERIFIED_GATES, see lines 92-94 in current code) |
| `ultratimonel/ultratimonel_client.py:132` | Fixed | MCP server spawn now merges `os.environ` + `ULTRATIMONEL_ENV` instead of replacing system environment |

**Nota:** El cambio de begin_turn a TOOLS_REQUIRING_VERIFIED_GATES en commit 484e42f fue SUPERSEIDO por PR #19 (commit 2e6c5e5, rama enforcement-v3). La versión actual del código tiene begin_turn como EXEMPTO del bouncer para prevenir deadlock. Ver lógica R3.1 en plugin_preflight.py:92-94.

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Regression if hooks called with positional args only | Low (backward-compatible) | Default parameters allow both calling conventions |
| Missing PATH/HOME in subprocess env breaks MCP tools | Low (already fixed) | Environment merge ensures all required vars available |

## Rollback Plan

N/A — documentation only. Code changes already deployed to production and verified working. Revert would require reverting commit 484e42f, but post-restart verification shows gates 4/4 PASS stable with TypeError resolved from logs.

## Dependencies

- None (bug fix retroactive)

## Success Criteria

- [x] Audit trail complete for commit 484e42f fixes
- [x] Documentation available at `openspec/changes/plugin-preflight-ctx-env-fix/proposal.md`