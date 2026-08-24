# Proposal: Plugin Preflight Context & Environment Fixes

## Intent

Document retroactive fixes applied in commit 484e42f to establish audit trail. Three critical changes were made: (1) plugin hook signatures corrected with `ctx=None` default causing TypeError and breaking all gate enforcement, (2) MCP client spawning without PATH/HOME environment preventing gates 1a/1b from executing external tools successfully, and (3) `mcp__ultratimonel__begin_turn` added to TOOLS_REQUIRING_VERIFIED_GATES to enforce mandatory tool contracts for the turn cycle.

## Scope

### In Scope
- Document the three fixes applied in commit 484e42f: (1) hook signatures with `ctx=None`, (2) MCP client environment merge, (3) `mcp__ultratimonel__begin_turn` addition to TOOLS_REQUIRING_VERIFIED_GATES
- Record technical details of plugin_preflight.py hook signature corrections
- Record ultratimonel_client.py MCP spawn environment merge fix
- Document the critical tool contract change for begin_turn enforcement

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
| `ultratimonel/plugin_preflight.py` | Fixed | Hook functions `_gates_bouncer()` and `_post_turn_guard()` corrected with `ctx=None` default parameter AND `mcp__ultratimonel__begin_turn` added to TOOLS_REQUIRING_VERIFIED_GATES (lines 40-42) |
| `ultratimonel/ultratimonel_client.py:132` | Fixed | MCP server spawn now merges `os.environ` + `ULTRATIMONEL_ENV` instead of replacing system environment |

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