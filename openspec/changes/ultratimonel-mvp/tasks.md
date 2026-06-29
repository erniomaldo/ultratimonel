# Task Breakdown: Ultratimonel MVP

## Phase 1 — Infrastructure

### 1.1 Project scaffolding
- [x] Create `ultratimonel/` package, `requirements.txt` (`fastmcp`), `server.py` skeleton with FastMCP init
- [x] **Verify:** `python -c "from ultratimonel.server import app"` succeeds

### 1.2 SQLite persistence (`persistence.py`)
- [x] `Persistence` class, schema v1: `gate_state`, `missions`, `schema_version` tables
- [x] WAL mode, NORMAL sync, busy_timeout=5000; auto-create at `~/.hermes/ultratimonel.db`
- [x] CRUD: get/upsert gate state, upsert/complete mission
- [x] **Verify:** pytest with in-memory SQLite covers all operations + migration

### 1.3 Context extractor (`context_extractor.py`)
- [x] `extract_context(message, session_id) → dict{sender, topic, project}`
- [x] Topic from leading noun phrase; project via regex dict, fallback to topic
- [x] **Verify:** correct output for empty msg, known project, unknown input

## Phase 2 — Core Gates

### 2.1 Gate engine (`gate_engine.py`)
- [x] `GateEngine` state machine (BLOCK/PASS/WARN/SKIP) + per-gate config
- [x] `run_gate(config, context) → GateResult` calls external MCP tool with 2s timeout
- [x] `aggregate(results) → (overall_status, context_envelope)`
- [x] **Verify:** all transitions, timeout→WARN, unavailable→SKIP

### 2.2 Triple match coordinator (`triple_match.py`)
- [x] `TripleMatchCoordinator` runs 1a→1b→1e sequentially with error isolation
- [x] **1a:** `memory_smart_search(sender+topic, 10)`; **1b:** `checkpoint_get_state(project)`, default if missing; **1e:** `deck_get_boards()`→filter→`get_stacks()`, empty if no match
- [x] Compiles `context_envelope` from all three outputs
- [x] **Verify:** correct envelope; one gate failure doesn't block others

### 2.3 MCP tools (`server.py`)
- [x] **`assert_gates(msg, sid)`:** extract→triple-match→aggregate→persist→`{status, gates[], context_envelope, timestamp}`
- [x] **`check_gate(name, sid)`:** read state from persistence
- [x] **`complete_gate(name, sid, reason)`:** BLOCK→PASS or WARN→PASS; log transition
- [x] Schemas per design.md JSON specs
- [x] **Verify:** FastMCP lists 3 tools with correct I/O

## Phase 3 — Integration

### 3.1 SOUL.md deployment
- [x] `scripts/deploy-soul-rules.sh`: injects `## Protocolo Pre-flight (OBLIGATORIO)` section with backup + diff
- [x] Idempotent: updates in-place if section exists
- [x] **Verify:** produces correct Spanish imperative rules

### 3.2 mcp-capabilities bridge (`bridge.py`)
- [x] Stub class; all no-ops with post-MVP docs
- [x] **Verify:** imports, no-op returns None

### 3.3 Error handling sweep
- [x] try/except on all external calls → SKIP fallback; invalid names → structured error; SQLite failure → WARN, never crash
- [x] **Verify:** mock failures per scenario, server stays up

## Phase 4 — Testing

### 4.1 Unit tests
- [x] `test_gate_engine`: transitions, aggregation, timeout→WARN
- [x] `test_context_extractor`: edge cases (empty, unknown project)
- [x] `test_persistence`: CRUD, migration, upsert idempotency
- [x] `test_triple_match`: error isolation, empty results, default checkpoint

### 4.2 Integration smoke test
- [x] Start server, call all 3 tools, verify output shape; BLOCK propagates; state persists
- [x] **Verify:** end-to-end pass

## Phase 5 — Documentation

### 5.1 README + docstrings
- [x] README.md: setup, tool signatures, usage, deps; module docstrings on all files
- [x] **Verify:** docs match actual I/O

---

## Review Workload Forecast

- **~450 lines** across 8 source files + 1 script + tests (greenfield)
- **Single PR** — no existing code; mock-based unit tests + integration smoke test
- **Risk areas:** External tool availability, 2s timeout, agent SOUL.md compliance
- **Review priority:** Phase 2 (core logic) + Phase 3.3 (resilience)
