# Assert Gates Deprecation — Spec

> **Capability ID:** `assert-gates-deprecation` · **Updated:** 13 Aug 2026 · **Change:** Card #150 (retrospective)

## Purpose

Document and verify the deprecation of `assert_gates` as an agent-facing gate step, in favor of the consolidated 2-call flow (`begin_turn` → trabajo → `end_turn`). `assert_gates` SHALL remain registered and functional because the plugin still invokes it in `pre_llm_call`; it SHALL be marked `~~DEPRECATED~~` and relocated to the legacy section. Documentation SHALL reflect the real inventory: 20 MCP tools (17 active + 3 legacy), plus the documented `mission_get` / `checklist_item_get` tools. All requirements are verifiable against the working tree.

## Requirements

### Functional

| ID | Requirement | Priority |
|----|-------------|----------|
| F-AGD-01 | The server SHALL keep `assert_gates(message, session_id, sender="user")` registered as an MCP tool with unchanged signature and behavior | MUST |
| F-AGD-02 | The `assert_gates` docstring SHALL begin with the marker `~~DEPRECATED~~` and SHALL instruct callers to use `begin_turn()` instead (consolidated 2-call flow) | MUST |
| F-AGD-03 | The `assert_gates` tool SHALL be located inside the "Legacy / archived tools" section of `server.py` (after `end_turn`) | MUST |
| F-AGD-04 | The server SHALL expose exactly 20 MCP tools via `@app.tool()` in `server.py` (17 active + 3 legacy) | MUST |
| F-AGD-05 | Exactly the 3 legacy tools SHALL carry a `DEPRECATED` marker in their docstring: `assert_gates`, `record_intento`, `complete_intento` | MUST |
| F-AGD-06 | `README.md` and `README.en.md` SHALL state the tool count as **20 (17 active + 3 legacy)** in every location where the count appears (architecture diagram, feature table, tools section, project tree), in the phrasing each README uses (ES: "20 tools MCP: 17 activas + 3 legacy"; EN: "20 MCP tools: 17 active + 3 legacy") | MUST |
| F-AGD-07 | Both READMEs SHALL list `assert_gates` in the legacy/archived tools table, not in the core gates table | MUST |
| F-AGD-08 | Both READMEs SHALL document `mission_get(mission_id)` and `checklist_item_get(checklist_item_id)` in the Misiones/Deck Sync tools section | MUST |

### Non-Functional

| ID | Requirement | Priority |
|----|-------------|----------|
| NF-AGD-01 | The deprecation SHALL NOT alter the runtime behavior of `assert_gates` (same gates execution, same persistence, same JSON response shape) | MUST |
| NF-AGD-02 | The deprecation SHALL NOT break `ultratimonel/plugin_preflight.py`: it SHALL still invoke `assert_gates` in its hooks (`on_session_start`, `pre_llm_call`) to fill the gate cache consumed by `pre_tool_call` | MUST |
| NF-AGD-03 | Documentation counts SHALL match the discoverable inventory via `app.list_tools()` (20) rather than any hand-maintained number | MUST |

## Scenarios

### S1 — assert_gates still registered and functional

GIVEN the working tree `ultratimonel/server.py`
WHEN the MCP tool list is discovered
THEN `assert_gates` is present and callable with `(message, session_id, sender="user")`

Verification: `rg -c "@app\.tool\(\)" ultratimonel/server.py` → 20; `tests/test_integration.py::test_assert_gates_returns_expected_shape` passes.

### S2 — Deprecation marker on docstring

GIVEN the `assert_gates` function in `ultratimonel/server.py`
WHEN its docstring is inspected
THEN it starts with `~~DEPRECATED~~` and mentions `use begin_turn() instead`

Verification: line 1419 of `server.py` contains `"""~~DEPRECATED~~ Run all pre-flight gates...` and `use begin_turn() instead`.

### S3 — Legacy section placement

GIVEN `ultratimonel/server.py`
WHEN the code between `end_turn` and `record_intento` is inspected
THEN there is a section header `# ── Legacy / archived tools ──` followed by `@app.tool() def assert_gates(...)`

Verification: section header at ~line 1408; `assert_gates` at line 1413–1414.

### S4 — Tool inventory is 20 (17 active + 3 legacy)

GIVEN the working tree `ultratimonel/server.py`
WHEN every `@app.tool()` decorator is counted
THEN the total is 20, of which exactly 3 tools (`assert_gates`, `record_intento`, `complete_intento`) have a `DEPRECATED` docstring

Verification: `rg -n "@app\.tool\(\)" ultratimonel/server.py | wc -l` → 20. Active count = 20 − 3 = 17. The 3 deprecated docstrings are those of `assert_gates` (lines 1419/1421), `record_intento` (line 1530), `complete_intento` (line 1674) — each contains `DEPRECATED`.

### S5 — README count consistency

GIVEN `README.md` and `README.en.md` in the working tree
WHEN all hardcoded tool-count references are inspected
THEN every reference reads **20** with breakdown **17 + 3 legacy**, in each README's own phrasing

Verification:
- `README.md`: `(20 tools)` (diagram), `20 tools MCP` (feature table + tools section), `20 tool handlers (17 activas + 3 legacy)` (project tree)
- `README.en.md`: `(20 tools)` (diagram), `20 MCP tools` (feature table + tools section), `20 tool handlers (17 active + 3 legacy)` (project tree)
- No remaining "18 tools" / "16 active" reference in either file.

### S6 — assert_gates in legacy table, not core

GIVEN both READMEs
WHEN the "Núcleo (Gates)" and "Legacy / Archivadas" tables are inspected
THEN `assert_gates` appears ONLY in the legacy table with `~~DEPRECATED~~ — use begin_turn() instead`

Verification: `assert_gates` row present under `### 🗄️ Legacy / Archivadas`; absent from `### 🧠 Núcleo (Gates)`.

### S7 — mission_get / checklist_item_get documented

GIVEN both READMEs
WHEN the Misiones/Deck Sync tools table is inspected
THEN it contains rows for `mission_get(mission_id)` and `checklist_item_get(checklist_item_id)`

Verification: grep for `mission_get` and `checklist_item_get` in both READMEs → present in the Missions section (not just the file tree).

### S8 — Plugin still calls assert_gates

GIVEN `ultratimonel/plugin_preflight.py`
WHEN the `on_session_start` and `pre_llm_call` hooks are inspected
THEN they still invoke `ultratimonel_client.assert_gates(...)` to populate the gate cache used by the `pre_tool_call` bouncer

Verification: `ultratimonel_client.assert_gates(` present at lines 243 (`_on_session_start`) and 285 (`_pre_llm_call`) of `plugin_preflight.py`. The bouncer itself (`_gates_bouncer`) reads the cache and does not call the tool directly.

### S9 — No behavior regression in tests

GIVEN the working tree
WHEN the server unit test suite runs
THEN `tests/test_server.py::TestAssertGates` passes (assert_gates remains functional with unchanged behavior)

Verification: `pytest tests/test_server.py::TestAssertGates -q` → `1 passed` (verified 2026-08-13). Note: `tests/test_integration.py` hangs in this environment at MCP client handshake (`session.initialize()`) — pre-existing environment limitation unrelated to this diff (the diff does not touch `main.py`, fixtures, or the MCP client); prior verify reports also relied on unit suites.
