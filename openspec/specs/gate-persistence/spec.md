# Gate Persistence — SQLite Schema for Gate State Tracking

> **Capability ID:** `gate-persistence`
> **Status:** Draft · **Updated:** 28 Jun 2026
> **MVP:** Yes — persistence capability

## 1. Purpose

Define the SQLite schema and access patterns for persisting gate state across Hermes sessions and restarts. Gate state must survive process termination so that long-running missions can resume without re-running all gates.

## 2. Requirements

### 2.1 Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| F-GP-01 | A SQLite database SHALL be created at `~/.hermes/ultratimonel.db` | MUST |
| F-GP-02 | A `gate_state` table SHALL track per-gate status for each session/project combination | MUST |
| F-GP-03 | A `missions` table SHALL track top-level mission records | MUST |
| F-GP-04 | The server SHALL read from SQLite on `assert_gates()` and `check_gate()` | MUST |
| F-GP-05 | The server SHALL write to SQLite on `complete_gate()` and after `assert_gates()` runs | MUST |
| F-GP-06 | The database SHALL be created with WAL journal mode for read concurrency | SHOULD |
| F-GP-07 | The server SHALL use a single-writer pattern (no concurrent writes) | MUST |
| F-GP-08 | Schema migrations SHALL use incremental versioning stored in a `schema_version` table | MUST |
| F-GP-09 | The database SHALL be created automatically on first server start if it does not exist | MUST |

### 2.2 Non-Functional Requirements

| ID | Requirement | Priority |
|----|-------------|----------|
| NF-GP-01 | All reads SHALL complete in under 50ms | MUST |
| NF-GP-02 | All writes SHALL complete in under 100ms | MUST |
| NF-GP-03 | The database SHALL use `PRAGMA journal_mode=WAL` for read concurrency during writes | MUST |
| NF-GP-04 | The database SHALL use `PRAGMA synchronous=NORMAL` for balance of safety and speed | MUST |
| NF-GP-05 | Schema changes SHALL be additive only — no destructive DDL in MVP | MUST |
| NF-GP-06 | The database file SHALL be excluded from version control (`.gitignore`) | SHOULD |

## 3. SQLite Schema

### 3.1 Schema Version

```sql
-- Schema version tracking for incremental migrations
CREATE TABLE IF NOT EXISTS schema_version (
    version     INTEGER PRIMARY KEY,
    description TEXT NOT NULL,
    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Initial version: `1` — "MVP gate persistence schema"

### 3.2 Gate State Table

```sql
-- Tracks per-gate status for each active session/project
CREATE TABLE IF NOT EXISTS gate_state (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,          -- Hermes session identifier
    project         TEXT NOT NULL,           -- Active project name
    gate_name       TEXT NOT NULL,           -- e.g., '1a', '1b', '1e'
    state           TEXT NOT NULL            -- PASS | SKIP | WARN | BLOCK | PENDING
                    CHECK(state IN ('PASS', 'SKIP', 'WARN', 'BLOCK', 'PENDING')),
    mandatory       INTEGER NOT NULL DEFAULT 1,  -- 1 = mandatory, 0 = optional
    duration_ms     INTEGER,                 -- Execution time in milliseconds
    message         TEXT,                    -- Human-readable result or error detail
    result_data     TEXT,                    -- JSON blob: gate-specific output (memory snippets, checkpoint, deck cards)
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    
    -- Enforce one status row per gate per session per project
    UNIQUE(session_id, project, gate_name)
);

-- Index for fast lookups by session + project
CREATE INDEX IF NOT EXISTS idx_gate_state_lookup
    ON gate_state(session_id, project);

-- Index for finding stale/old sessions
CREATE INDEX IF NOT EXISTS idx_gate_state_updated
    ON gate_state(updated_at);
```

### 3.3 Missions Table

```sql
-- Tracks top-level mission records
CREATE TABLE IF NOT EXISTS missions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,           -- Hermes session identifier
    project         TEXT NOT NULL,           -- Mission project name
    status          TEXT NOT NULL DEFAULT 'active'
                    CHECK(status IN ('active', 'completed', 'failed', 'aborted')),
    gates_passed    INTEGER NOT NULL DEFAULT 0,   -- Count of gates in PASS state
    gates_total     INTEGER NOT NULL DEFAULT 3,   -- Total configured gates
    started_at      TEXT NOT NULL DEFAULT (datetime('now')),
    completed_at    TEXT,
    last_gate_run   TEXT,                    -- Timestamp of last gate execution
    
    UNIQUE(session_id, project)
);

CREATE INDEX IF NOT EXISTS idx_missions_active
    ON missions(status, started_at);
```

## 4. Access Patterns

### 4.1 Read Gate State (used by `check_gate()` and `assert_gates()`)

```sql
SELECT gate_name, state, mandatory, duration_ms, message, result_data, updated_at
FROM gate_state
WHERE session_id = ? AND project = ? AND gate_name = ?;
```

### 4.2 Write Gate State (used by `complete_gate()` and `assert_gates()` post-run)

```sql
INSERT INTO gate_state (session_id, project, gate_name, state, mandatory, duration_ms, message, result_data)
VALUES (?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(session_id, project, gate_name) DO UPDATE SET
    state = excluded.state,
    duration_ms = excluded.duration_ms,
    message = excluded.message,
    result_data = excluded.result_data,
    updated_at = datetime('now');
```

### 4.3 Upsert Mission (used after full `assert_gates()` run)

```sql
INSERT INTO missions (session_id, project, status, gates_passed, gates_total, last_gate_run)
VALUES (?, ?, 'active', ?, 3, datetime('now'))
ON CONFLICT(session_id, project) DO UPDATE SET
    gates_passed = excluded.gates_passed,
    last_gate_run = datetime('now');
```

### 4.4 Complete Mission (used at end of session or project)

```sql
UPDATE missions
SET status = 'completed', completed_at = datetime('now')
WHERE session_id = ? AND project = ?;
```

## 5. Scenarios

### 5.1 First Assert — No Prior State

```
Given: No rows exist in gate_state for session "sess-001" and project "ultratimonel"
When:  assert_gates() is called
Then:  Gates are executed fresh
And:   Results are INSERTed into gate_state
And:   A new mission row is INSERTed into missions with status "active"
```

### 5.2 Subsequent Assert — State Exists

```
Given: Gate 1a is already PASS in gate_state for this session and project
When:  assert_gates() is called
Then:  Gate 1a result from previous run is loaded from SQLite
And:   Gate 1a is NOT re-executed (unless forced)
And:   The mission's last_gate_run is updated
```

### 5.3 Complete Gate Updates Persistence

```
Given: Gate 1b is currently PENDING
When:  complete_gate("1b") is called
Then:  gate_state row for 1b is UPDATED to state="PASS"
And:   missions.gates_passed is incremented
```

### 5.4 Restart Survives Process Termination

```
Given: The Ultratimonel MCP server is stopped and restarted
When:  assert_gates() is called with the same session_id and project
Then:  Gate state is still present in SQLite
And:   Previously PASSed gates are not re-executed
And:   The mission continues from where it left off
```

### 5.5 Schema Migration

```
Given: The schema version table reports version 1
When:  A new migration (version 2) is introduced
Then:  The migration SQL is applied
And:   schema_version gains a row (version=2, description="...")
And:   Existing data is preserved (additive DDL only)
```

### 5.6 Cleanup Stale Sessions

```
Given: A mission row has not been updated in 7 days
When:  The server starts
Then:  Stale missions MAY be marked as "aborted" automatically
And:   Associated gate_state rows MAY be pruned
```

## 6. Error Handling

| Error | Condition | Response |
|-------|-----------|----------|
| `DB_CREATE_FAIL` | Cannot create or open SQLite file | Return WARN for all persistence-backed reads, continue degraded |
| `DB_WRITE_FAIL` | INSERT/UPDATE fails | Log error, return WARN for the affected gate, continue degraded |
| `SCHEMA_STALE` | Schema version is behind expected | Run migrations on startup before accepting requests |
| `SCHEMA_AHEAD` | Schema version is ahead of server code | Fail gracefully — do not downgrade: `{"error": "Database schema is newer than this server version"}` |
| `DB_LOCKED` | SQLite returns SQLITE_BUSY | Retry up to 3 times with 100ms backoff |

## 7. Initialization Sequence

On server startup:

1. Check if `~/.hermes/ultratimonel.db` exists
2. If not, create the file + run initial DDL
3. If yes, read `schema_version` and compare with expected version
4. Run any pending migrations sequentially
5. Set `PRAGMA journal_mode=WAL`
6. Set `PRAGMA synchronous=NORMAL`
7. Set `PRAGMA busy_timeout=5000`
8. Begin accepting tool requests

## 8. Schema Version History

| Version | Description | Date |
|---------|-------------|------|
| 1 | MVP: gate_state + missions + schema_version | 2026-06-28 |
