# Proposal: Ultratimonel MVP — Pre-flight Gate Enforcement

## Intent
Create Ultratimonel, an MCP server that enforces a deterministic pre-flight gate protocol in Hermes. The agent consistently fails to consult AgentMemory, Checkpoint, or Deck context before inferring. Ultratimonel exposes gate-check tools embedded as hard rules in SOUL.md, blocking generation until mandatory gates pass.

## Scope

### In
1. MCP server with 3 tools: `assert_gates()` (run + validate all), `check_gate(name)` (single status), `complete_gate(name)` (mark passed)
2. Triple match gates: 1a (AgentMemory recall), 1b (Checkpoint get_state), 1e (Deck scan)
3. SOUL.md enforcement rules
4. SQLite persistence for mission state
5. Pre-gate context extraction (sender, topic, project)

### Out
- No GUI/dashboard (MCP-only)
- No inter-agent communication
- mcp-capabilities integration (1b.1 — post-MVP)
- Skills search (1d) and session search (1c) — conditional, deferred

## Capabilities

### New
- `mission-gate` — Pre-flight verification: 3 tools + pass/block/warn/skip states
- `triple-match` — Coordinated AgentMemory + Checkpoint + Deck scan into unified context
- `soul-enforce` — SOUL.md identity hardening with hard gate rules
- `gate-persistence` — SQLite schema tracking gate status per session

## Approach
Python MCP server with FastMCP, SQLite3 via stdlib. Three phases:

1. **Infrastructure** — Skeleton with FastMCP, SQLite schema, tool registration
2. **Core gates** — `assert_gates()`, `check_gate()`, `complete_gate()` with triple-match (1a→1b→1e)
3. **Integration** — SOUL.md deployment with hard rules; mcp-capabilities bridge stub

Frequency: every message. Gate states: PASS (continue), SKIP (continue, N/A), WARN (warn+continue), BLOCK (halt generation).

## Affected Areas
- **New**: `ultratimonel/` — Python MCP server, SQLite DB
- **SOUL.md**: Hard enforcement rules for pre-generation gate calls
- **mcp-capabilities-server**: Bridge point defined (no MVP changes)
- **Nextcloud**: Read-only Deck access via existing tools

## Risks
| Risk | Mitigation |
|------|-----------|
| LLM ignores SOUL.md | n8n backup pipeline in Nextcloud docs |
| SQLite contention | Single-writer pattern |
| Deck scan latency | SKIP state if unavailable; per-gate timeout |

## Rollback Plan
1. Edit SOUL.md to remove gate-rule section (not delete the file)
2. Stop Ultratimonel MCP server (kill + remove from Hermes config)
3. Delete `ultratimonel.db` — no other system affected

## Dependencies
- Python ≥3.13 with stdlib sqlite3
- `fastmcp` package
- AgentMemory, Checkpoint, and Deck MCP tools (all already available)

## Success Criteria
1. `assert_gates()` returns structured PASS/BLOCK for each of 1a, 1b, 1e
2. Hermes calls gates before every message (audit-log verified)
3. Generation blocked when a mandatory gate fails
4. SOUL.md rules present and enforced by agent identity
5. SQLite persists gate state across restarts
