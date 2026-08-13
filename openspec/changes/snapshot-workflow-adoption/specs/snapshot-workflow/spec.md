# Snapshot Workflow — Skill Sync & Preflight Hook Fix

> **Capability ID:** `snapshot-workflow` · **Updated:** 12 Aug 2026 · **Change:** Card #150

## Purpose

Adopt the snapshot workflow used by the other Hermes instance: sync the repo-owned skills and preflight plugin into the snapshot, add the missing skills, fix the preflight hook signatures (remove `ctx` as first parameter), record the `custom-dangerous-patterns` version decision (docs-only — the dependency is not present in repo manifests), document the already-implemented client parameterization, and verify the result. The repo remains the source of truth; the snapshot is derived state.

## Requirements

### Functional

| ID | Requirement | Priority |
|----|-------------|----------|
| F-SW-01 | The repo-owned skills SHALL be synced from the repo into the snapshot: `ultratimonel-ciclo-basico` and `protocolo-de-trazabilidad`. The repo SHALL remain the source of truth; the snapshot SHALL be derived state. | MUST |
| F-SW-02 | The snapshot SHALL contain the four skills: `ultratimonel-ciclo-basico`, `protocolo-de-trazabilidad`, `opencode`, `pipeline-determinista-ui-code`. | MUST |
| F-SW-03 | `_gates_bouncer` SHALL have signature `(tool_name: str, args: dict, **kwargs)` — no `ctx` parameter. | MUST |
| F-SW-04 | `_post_turn_guard` SHALL have signature `(tool_name: str, args: dict, result: dict, **kwargs)` — no `ctx` parameter. | MUST |
| F-SW-05 | `_on_session_start` and `_pre_llm_call` SHALL NOT receive `ctx` (verify only — no change). | MUST |
| F-SW-06 | The `custom-dangerous-patterns` version decision SHALL be recorded in the change documentation (design.md ADR-3 + README). The dependency is NOT present in the repo's manifests (`requirements.txt`/`pyproject.toml`), so no repo manifest pin SHALL be performed; the pin lives in the external Hermes runtime snapshot. Default decision: 0.3.4; flip to 1.6.0 only after validation. | MUST |
| F-SW-07 | `ultratimonel_client.py` SHALL resolve the MCP server command/args via env vars `ULTRATIMONEL_MCP_CMD`/`ULTRATIMONEL_MCP_ARGS` when set, falling back to the Hermes MCP config (`_hermes_mcp_config()` reading `~/.hermes/config.yaml`), and finally to `sys.executable`/portable fallback. This is already implemented in the working tree (post-state); this change SHALL document the behavior and verify `.env.example` covers the vars — NO new code. The previously planned env var `ULTRATIMONEL_HERMES_HOME` is obsolete and superseded by the implemented mechanism. | MUST |
| F-SW-08 | `plugin.yaml` SHALL reflect the hook signature fix with a version bump to 2.0.1, and the `register()` log message SHALL say `v2.0.1` (currently logs "Plugin v2.0"). | MUST |
| F-SW-09 | Post-change verification SHALL pass: `py_compile`, hook signature inspection, runtime smoke check, snapshot skill diff, and the existing test suite (via `.venv/bin/pytest`). | MUST |

### Non-Functional

| ID | Requirement | Priority |
|----|-------------|----------|
| NF-SW-01 | The hook signature fix SHALL NOT change hook behavior (parameter removal only). | MUST |
| NF-SW-02 | Snapshot sync SHALL be one-directional: repo → snapshot, never reverse. | MUST |

## Tool Specifications

N/A — this change modifies plugin internals and snapshot contents, not MCP tool schemas.

## Scenarios

### S1 — Repo skills synced to snapshot
GIVEN `skills/ultratimonel-ciclo-basico` and `skills/protocolo-de-trazabilidad` exist in the repo
WHEN the snapshot sync runs
THEN both skills are copied from the repo into the snapshot
AND `diff -r` between repo skills and snapshot skills is empty

### S2 — Missing skills added to snapshot
GIVEN the snapshot does not contain `opencode` nor `pipeline-determinista-ui-code`
WHEN the snapshot sync runs
THEN both skills are copied from their canonical sources into the snapshot
AND the snapshot contains all 4 skills

### S3 — pre_tool_call hook without ctx
GIVEN `_gates_bouncer` currently declares `ctx` as first parameter
WHEN the signature fix is applied
THEN the signature is `(tool_name: str, args: dict, **kwargs)`
AND no hook body references `ctx`

### S4 — post_tool_call hook without ctx
GIVEN `_post_turn_guard` currently declares `ctx` as first parameter
WHEN the signature fix is applied
THEN the signature is `(tool_name: str, args: dict, result: dict, **kwargs)`
AND no hook body references `ctx`

### S5 — on_session_start / pre_llm_call verified clean
GIVEN `_on_session_start` and `_pre_llm_call` do not declare `ctx`
WHEN the verification runs
THEN both hooks remain unchanged
AND inspection confirms they receive no `ctx`

### S6 — Dependency version decision recorded (docs-only)
GIVEN `custom-dangerous-patterns` is unpinned between 0.3.4 and 1.6.0 in the Hermes runtime
AND the dependency is absent from the repo manifests (`requirements.txt`/`pyproject.toml`)
WHEN the version decision is recorded in design.md ADR-3 and README
THEN the decision (default 0.3.4) is documented
AND no repo manifest pin is attempted

### S7 — Client parameterization documented as post-state
GIVEN `ULTRATIMONEL_MCP_CMD` or `ULTRATIMONEL_MCP_ARGS` is set
WHEN `ultratimonel_client.py` resolves the MCP server command/args
THEN the env var value is used (implementation already present in the working tree)
GIVEN no env vars are set
WHEN `ultratimonel_client.py` resolves the MCP server command/args
THEN it falls back to `_hermes_mcp_config()` (`~/.hermes/config.yaml`) and finally `sys.executable`
AND the documentation and `.env.example` reflect this resolution order

### S8 — Post-change verification
GIVEN the skill sync and hook signature fix are applied
WHEN the verification checklist runs
THEN `py_compile` passes on modified files (`.venv/bin/python`)
AND hook signature inspection shows no `ctx` on the modified hooks (`_gates_bouncer`, `_post_turn_guard`) nor on the unmodified `_on_session_start`/`_pre_llm_call` (F-SW-05/S5)
AND a runtime smoke check imports the plugin, registers hooks, and exercises `_gates_bouncer`/`_post_turn_guard` with the new signatures
AND the repo→snapshot skill diff is empty
AND the existing test suite passes via `.venv/bin/pytest`
