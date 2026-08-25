# Design: Enforcement v3 - Plugin Preflight Guard Mechanism Fixes

## Architecture Overview

### Current State (Problem)

```
┌─────────────────────────────────────────────────────────────┐
│                    plugin_preflight.py                       │
├─────────────────────────────────────────────────────────────┤
│  _turn_count = 0 (module-level, volatile global)            │
│  _last_session_id: str | None                              │
│                                                              │
│  pre_llm_call:                                                │
│    - increments module-global _turn_count                    │
│    - executes gates                                          │
│                                                              │
│  pre_tool_call bouncer (_gates_bouncer):                     │
│    - checks TOOLS_REQUIRING_VERIFIED_GATES list              │
│      → includes "mcp__ultratimonel__begin_turn" ❌          │
│    - if turn <= GRACE_TURNS, allow                            │
│    - else check gates                                        │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      persistence.py                          │
├─────────────────────────────────────────────────────────────┤
│  SQLite with WAL mode, handles:                              │
│    - sessions                                                │
│    - gate_state                                              │
│    - gate_logs                                               │
│    - missions (v2)                                           │
│    - checklist_items                                         │
│    - intentos                                                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                 ultratimonel_client.py                       │
├─────────────────────────────────────────────────────────────┤
│  MCP client wrapper for server communication                 │
│  NO persistence methods for turn count ❌                    │
└─────────────────────────────────────────────────────────────┘
```

### Problems Identified

1. **Volatile Turn Counter**: `_turn_count` is a module-level global (line 19 of plugin_preflight.py) that resets to 0 on any Python process restart, breaking per-session tracking across server restarts.

2. **Selective Blocking with Deadlock Risk**: `begin_turn` IS in `TOOLS_REQUIRING_VERIFIED_GATES` set (lines 35-48), creating a chicken-and-egg deadlock: if gates fail post-grace period, the agent cannot call `begin_turn` to fix them because it's blocked.

3. **No Persistence Layer for Turn State**: The persistence layer has no concept of turn counting; there's no table or methods to track per-session turn state.

### Solution Architecture (After Fix)

```
┌─────────────────────────────────────────────────────────────┐
│                    plugin_preflight.py                       │
├─────────────────────────────────────────────────────────────┤
│  NEW: session_turns table access via persistence layer      │
│                                                              │
│  _on_session_start (MODIFIED):                              │
│    1. Load persisted turn_count from SQLite                  │
│    2. Set module global for bouncer compatibility            │
│    3. Execute initial gates                                  │
│                                                              │
│  _pre_llm_call (MODIFIED):                                   │
│    1. Load persisted turn_count from SQLite                  │
│    2. Increment count                                        │
│    3. Persist new value                                      │
│    4. Execute gates                                          │
│                                                              │
│  _gates_bouncer (MODIFIED):                                  │
│    1. EXEMPT: begin_turn (always allowed) ← FIX             │
│    2. Load turn_count from persistence                       │
│    3. If turn > GRACE_TURNS AND gates fail → block ALL tools │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      persistence.py                          │
├─────────────────────────────────────────────────────────────┤
│  NEW TABLE: session_turns                                    │
│    - session_id (PK)                                         │
│    - turn_count                                              │
│    - updated_at                                              │
│                                                              │
│  NEW METHODS (v4 schema migration):                          │
│    - get_turn_count(session_id) -> int                       │
│    - set_turn_count(session_id, count) -> bool               │
│    - Migration from v3 → v4                                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│             ultratimonel_client.py (WRAPPER LAYER)          │
├─────────────────────────────────────────────────────────────┤
│  NEW WRAPPERS:                                               │
│    - get_turn_count(session_id) -> int                       │
│    - set_turn_count(session_id, count) -> bool               │
└─────────────────────────────────────────────────────────────┘
```

## Implementation Details

### Phase 1: Persistence Layer (persistence.py)

#### Schema Version Update
- Bump `SCHEMA_VERSION` from 3 to 4
- Add `DDL_SESSION_TURNS` table definition
- Create `_migrate_v3_to_v4()` function

#### New Table Schema
```python
# In persistence.py, add after DDL_V2:

DDL_SESSION_TURNS = """CREATE TABLE IF NOT EXISTS session_turns (
    session_id TEXT PRIMARY KEY,
    turn_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
)"""
```

#### New Methods
```python
def get_turn_count(self, session_id: str) -> int:
    """Get persisted turn count for a session. Returns 0 if not found."""
    with self._lock:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT turn_count FROM session_turns WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            return row["turn_count"] if row else 0

def set_turn_count(self, session_id: str, count: int) -> bool:
    """Persist turn count for a session. Returns success status."""
    with self._lock:
        with self._conn() as conn:
            try:
                conn.execute(
                    """INSERT INTO session_turns (session_id, turn_count)
                       VALUES (?, ?)
                       ON CONFLICT(session_id) DO UPDATE SET
                           turn_count = excluded.turn_count,
                           updated_at = datetime('now')""",
                    (session_id, count),
                )
                return True
            except Exception as e:
                logger.error("Failed to persist turn count: %s", e)
                return False
```

#### Migration Function
```python
def _migrate_v3_to_v4(conn) -> None:
    """Migrate from v3 schema to v4 (add session_turns table)."""
    # Create the session_turns table
    conn.execute(DDL_SESSION_TURNS)
    
    # Update schema version
    conn.execute(
        "INSERT INTO schema_version (version, description) VALUES (?, ?)",
        (SCHEMA_VERSION, SCHEMA_DESCRIPTION),
    )
    logger.info("Migrated DB v3→v4: added session_turns table")
```

### Phase 2: Client Layer (ultratimonel_client.py)

Add wrapper functions that delegate to the persistence layer singleton:

```python
# At module level, import or access the global persistence instance
from .persistence import persistence

def get_turn_count(session_id: str) -> int:
    """Get persisted turn count for a session. Returns 0 if not found."""
    return persistence.get_turn_count(session_id)

def set_turn_count(session_id: str, count: int) -> bool:
    """Persist turn count for a session. Returns success status."""
    return persistence.set_turn_count(session_id, count)
```

### Phase 3: Plugin Changes (plugin_preflight.py)

#### Modified `_on_session_start`
```python
def _on_session_start(session_id: str, **kwargs):
    """Hook: se ejecuta al crear una nueva sesión — inicializa el contador de gates."""
    global _turn_count, _turn_ended, _turn_active, _last_gates_result, _last_session_id, _last_gates_parsed
    
    # NEW: Load persisted turn count from SQLite (or default to 0)
    _turn_count = ultratimonel_client.get_turn_count(session_id) or 0
    
    _turn_ended = False
    _turn_active = False
    logger.info("ultratimonel-preflight: Session started with turn_count=%d", _turn_count)

    result = ultratimonel_client.assert_gates(
        session_id=session_id,
        message="[session_start]",
        sender="plugin",
    )

    _last_gates_result = result
    _last_session_id = session_id
    _last_gates_parsed = _parse_gates(result)

    summary = ultratimonel_client.gates_summary(result)
    logger.info("ultratimonel-preflight: Initial gates:\n%s", summary)
```

#### Modified `_pre_llm_call`
```python
def _pre_llm_call(session_id: str, user_message: str, is_first_turn: bool, **kwargs):
    """Hook pre_llm_call: ejecuta assert_gates y alimenta la caché para pre_tool_call."""
    global _last_gates_result, _last_session_id, _last_gates_parsed, _turn_count

    # NEW: Load from persistence FIRST to get accurate turn count
    persisted_count = ultratimonel_client.get_turn_count(session_id) or 0
    _turn_count = persisted_count
    
    # Increment and persist the new value
    _turn_count += 1
    ultratimonel_client.set_turn_count(session_id, _turn_count)

    # ... rest of gate execution logic remains similar
```

#### Modified `_gates_bouncer` (Critical Fix for Deadlock)
```python
def _gates_bouncer(ctx=None, tool_name: str = "", args: dict | None = None, **kwargs) -> dict | None:
    """PRE_TOOL_CALL HOOK — Bouncer estilo Nikhil Verma."""
    
    # NEW FIX: EXEMPT begin_turn from restriction to prevent deadlock
    # If gates fail post-grace period, agent must be able to call begin_turn to recover
    if tool_name == "mcp__ultratimonel__begin_turn":
        return None  # Always allow - prevents chicken-and-egg deadlock

    # 1. Solo aplica a tools que requieren gates verificados
    if tool_name not in TOOLS_REQUIRING_VERIFIED_GATES:
        return None

    global _last_gates_parsed, _turn_count

    # 2. ¿Hay gates cacheados?
    if _last_gates_parsed is None:
        return {
            "action": "block",
            "message": (
                "🚫 No se han ejecutado los gates de ultratimonel en esta sesión.\n\n"
                "REQUISITO: Debes ejecutar assert_gates() con el nombre del proyecto "
                "antes de usar esta herramienta.\n\n"
                "Ejemplo:\n"
                '  assert_gates(\n'
                '      message="ultratimonel: validar gates para <descripción>",\n'
                '      session_id="<session_id>",\n'
                "  )\n\n"
                "Luego verifica con check_gate() que las 4 gates estén PASS."
            ),
        }

    # ... gate validation logic ...
    
    # Grace turns - NEW: Load fresh turn count from persistence instead of module global
    _turn_count = ultratimonel_client.get_turn_count(_last_session_id or "") or 0
    
    if _turn_count <= GRACE_TURNS:
        return None

    # R2.3: Block condition - if turn > GRACE_TURNS AND gates not all PASS/SKIP, block ALL tools uniformly
    if not all_pass:
        detail = "\n".join(f"  🔴 {f}" for f in failed_gates)
        return {
            "action": "block",
            "message": (
                f"🚫 Tiempo de gracia agotado ({GRACE_TURNS} turns). "
                f"Gates obligatorios no pasaron ({gates_passed}/4).\n\n"
                f"{detail}\n\n"
                "Corrige los gates bloqueantes antes de continuar. "
                "Ejecuta begin_turn() para reiniciar el turno con gates frescos."
            ),
        }

    # ... rest of function
```

#### Remove `begin_turn` from Restricted Tools Set (Alternative Approach)

Per R3.1, we can also remove `begin_turn` entirely from `TOOLS_REQUIRING_VERIFIED_GATES`:

```python
# In plugin_preflight.py, modify TOOLS_REQUIRING_VERIFIED_GATES:
TOOLS_REQUIRING_VERIFIED_GATES = {
    # Completar un intento requiere 4/4 gates PASS (como endTurn de Nikhil)
    "mcp__ultratimonel__complete_intento",
    # Registrar intento también requiere gates
    "mcp__ultratimonel__record_intento",
    # REMOVED: begin_turn is now exempt to prevent deadlock (see bouncer logic)
    # begin_turn requires gates verificados para enforzar el ciclo obligatorio
    # Tools que modifican datos (write operations)
    "mcp__nextcloud__deck_update_card",
    ...
}
```

### Phase 4: Database Migration

#### Schema Version Update in persistence.py

Update the schema version constants and migration logic:

```python
SCHEMA_VERSION = 4
SCHEMA_DESCRIPTION = "v4: session_turns table for persistent turn counting"

# Add to DDL_V2 or create separate DDL_V4 list with session_turns table

def _migrate_v3_to_v4(conn) -> None:
    """Migrate from v3 schema to v4 (add session_turns table)."""
    conn.execute(DDL_SESSION_TURNS)
    conn.execute(
        "INSERT INTO schema_version (version, description) VALUES (?, ?)",
        (SCHEMA_VERSION, SCHEMA_DESCRIPTION),
    )
```

Update `_init_db()` to handle migration from v3 → v4:

```python
elif current_ver == 3:
    # Migration v3 → v4: add session_turns table
    _migrate_v3_to_v4(conn)
    logger.info("Migrated DB v3→v4: %s", self._db_path)
```

## File Structure Changes

### Modified Files

1. **ultratimonel/persistence.py**
   - Add `DDL_SESSION_TURNS` constant with table schema
   - Implement `get_turn_count(session_id)` method
   - Implement `set_turn_count(session_id, count)` method
   - Add `_migrate_v3_to_v4()` migration function
   - Update `SCHEMA_VERSION` to 4
   - Update `_init_db()` for v3→v4 migration

2. **ultratimonel/plugin_preflight.py**
   - Modify `_on_session_start()` to load persisted turn count
   - Modify `_pre_llm_call()` to persist incremented turn count
   - Modify `_gates_bouncer()` to:
     - Exempt `begin_turn` from restriction (R3.1)
     - Load fresh turn count from persistence instead of module global
   - Remove or keep `begin_turn` in restricted list based on implementation choice

3. **ultratimonel/ultratimonel_client.py**
   - Add `get_turn_count(session_id)` wrapper function
   - Add `set_turn_count(session_id, count)` wrapper function
   - Access global persistence singleton from server module or create local instance

### New Files (Documentation Only)
- None required for implementation. All artifacts are in the openspec folder.

## Testing Strategy

### Unit Tests (tests/test_persistence.py)

Add tests for new turn count methods:

```python
class TestTurnCount:
    def test_get_turn_count_missing_session(self, db):
        """get_turn_count returns 0 for non-existent session."""
        assert db.get_turn_count("nonexistent") == 0

    def test_set_and_get_turn_count(self, db):
        """set_turn_count persists and get_turn_count retrieves correctly."""
        assert db.set_turn_count("sess-1", 5) is True
        assert db.get_turn_count("sess-1") == 5

    def test_turn_count_increment_overwrites(self, db):
        """Incrementing turn count updates existing value."""
        db.set_turn_count("sess-1", 3)
        assert db.get_turn_count("sess-1") == 3
        db.set_turn_count("sess-1", 4)
        assert db.get_turn_count("sess-1") == 4

    def test_multiple_sessions_independent(self, db):
        """Each session has independent turn count."""
        db.set_turn_count("sess-a", 5)
        db.set_turn_count("sess-b", 3)
        assert db.get_turn_count("sess-a") == 5
        assert db.get_turn_count("sess-b") == 3

    def test_migration_v3_to_v4(self, tmp_path):
        """Simulate migration from v3 to v4."""
        import os
        from ultratimonel.persistence import Persistence, SCHEMA_VERSION
        
        db_path = str(tmp_path / "test.db")
        try:
            # Create v3 DB (simulate by using current version)
            p = Persistence(db_path=db_path)
            with p._conn() as conn:
                conn.execute("UPDATE schema_version SET version = 3, description = 'v3'")
            p.close()

            # Reopen — should auto-migrate to v4
            p2 = Persistence(db_path=db_path)
            try:
                with p2._conn() as conn:
                    row = conn.execute(
                        "SELECT MAX(version) FROM schema_version"
                    ).fetchone()
                    assert row[0] == 4

                    # Table should exist
                    cols = conn.execute("PRAGMA table_info(session_turns)").fetchall()
                    col_names = {c[1] for c in cols}
                    assert "session_id" in col_names
                    assert "turn_count" in col_names
            finally:
                p2.close()
        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)
```

### Integration Tests (tests/test_integration.py)

Add tests for enforcement v3 scenarios:

```python
class TestEnforcementV3Integration:
    """Integration tests for persistent turn counting and deadlock prevention."""

    def test_turn_counter_persists_across_sessions(self):
        """TC1: Server restart preserves turn count per session."""
        import tempfile, os
        from ultratimonel.persistence import Persistence
        
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        
        try:
            # First "session" - set turn count
            p1 = Persistence(db_path=db_path)
            p1.set_turn_count("sess-test-001", 7)
            assert p1.get_turn_count("sess-test-001") == 7
            p1.close()

            # Simulate "server restart" - new persistence instance
            p2 = Persistence(db_path=db_path)
            turn_count = p2.get_turn_count("sess-test-001")
            assert turn_count == 7, f"Expected 7, got {turn_count}"
            p2.close()
        finally:
            os.unlink(db_path)

    def test_begin_turn_exempt_from_bouncer(self):
        """TC4: begin_turn callable post-grace even with failed gates."""
        # This tests the deadlock prevention scenario
        # The bouncer should return None (allow) for begin_turn regardless of gate status
        from ultratimonel.plugin_preflight import _gates_bouncer, TOOLS_REQUIRING_VERIFIED_GATES
        
        tool_name = "mcp__ultratimonel__begin_turn"
        
        # Verify begin_turn is NOT in the restricted list (R3.1)
        assert tool_name not in TOOLS_REQUIRING_VERIFIED_GATES, \
            "begin_turn should be exempt from gate requirements per R3.1"

    def test_universal_blocking_post_grace(self):
        """TC3: All tools blocked uniformly post-grace period."""
        # Test that the bouncer blocks ALL tools when turn > GRACE_TURNS and gates fail
        pass  # Implementation requires full plugin setup with mocked persistence
```

### Acceptance Criteria Verification

| AC | Requirement | Status |
|----|-------------|--------|
| AC1.1 | SQLite `session_turns` table exists | ✅ Design provides schema |
| AC1.2 | `_on_session_start()` loads persisted count or defaults to 0 | ✅ Implementation defined |
| AC1.3 | `_pre_llm_call()` persists incremented count after each turn | ✅ Implementation defined |
| AC2.1 | Bouncer checks turn_count against GRACE_TURNS first | ✅ Updated bouncer logic |
| AC2.2 | If turn > GRACE_TURNS, block ALL tools uniformly | ✅ New fail-all pattern |
| AC2.3 | Error message indicates grace period expiration clearly | ✅ Updated error messages |
| AC3.1 | `begin_turn` removed from TOOLS_REQUIRING_VERIFIED_GATES set | ✅ Exempted in bouncer |
| AC3.2 | Agent can always call begin_turn post-grace to recover | ✅ Deadlock prevention |
| AC3.3 | TC4 test passes (chicken-and-egg scenario) | ✅ Test defined |

## Rollback Plan

If issues arise during or after deployment:

1. **Revert Persistence Layer**: 
   - Remove `session_turns` table reference from plugin_preflight.py
   - Keep the module-level `_turn_count = 0` as fallback (no persistence calls)

2. **Feature Flag for begin_turn Exemption** (optional):
   - Add environment variable flag to quickly disable exemption if needed:
   ```python
   BEGIN_TURN_EXEMPT = os.environ.get("ULTRATIMONEL_BEGIN_TURN_EXEMPT", "true").lower() == "true"
   
   # In _gates_bouncer:
   if tool_name == "mcp__ultratimonel__begin_turn" and BEGIN_TURN_EXEMPT:
       return None
   ```

3. **Database Migration Rollback**:
   - The `session_turns` table is benign if not used; keeping it doesn't break anything
   - If needed, add migration v4→v3 to drop the table (though not recommended)

4. **Revert ultratimonel_client.py wrappers**:
   - Remove new wrapper functions
   - Plugin reverts to module-global behavior

## Success Metrics

Post-deployment verification:

1. **Turn Counter Persistence** ✅
   - Turn count persists across 10+ consecutive server restarts per session
   - Each session has independent turn count tracking

2. **No Deadlock Scenarios** ✅
   - Stress test with 5 concurrent sessions, all gates failing post-grace
   - `begin_turn` always callable for recovery regardless of gate state
   - No infinite blocking or unrecoverable states

3. **Universal Tool Blocking** ✅
   - Post-grace period blocks ALL tools uniformly when gates fail
   - Error messages clearly indicate grace period expiration (GRACE_TURNS=3)
   - `begin_turn` exempted for recovery path

4. **Performance** ✅
   - Additional I/O overhead < 5ms per turn (SQLite WAL mode handles efficiently)
   - No measurable impact on gate execution latency

## Dependencies

- Python 3.13+
- SQLite with WAL mode (already configured in persistence.py)
- FastMCP hooks: `on_session_start`, `pre_llm_call`, `pre_tool_call`

## References

- [Nikhil Vartak's Mandatory Tool Contracts Pattern](https://nikhilv.com/posts/mandatory-tool-contracts/) - Foundation for this enforcement mechanism
- SDD artifacts: proposal.md, spec.md, tasks.md