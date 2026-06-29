"""
persistence.py — SQLite layer for Ultratimonel gate state persistence.

Schema v1 with six tables:
  - schema_version:  incremental migration tracking
  - sessions:        per-gen context (sender, topic, project)
  - gate_state:      per-gate status per session+project
  - gate_logs:       audit trail for every state transition
  - checkpoints:     triple-match raw/extracted snapshots
  - missions:        top-level mission lifecycle

Database path:  ~/.hermes/ultratimonel.db
PRAGMA:         WAL, synchronous=NORMAL, busy_timeout=5000
"""

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Schema ──────────────────────────────────────────────────────────────

SCHEMA_VERSION = 1
SCHEMA_DESCRIPTION = "MVP gate persistence schema"

DDL = [
    # Table 1: schema versioning
    """CREATE TABLE IF NOT EXISTS schema_version (
        version     INTEGER PRIMARY KEY,
        description TEXT NOT NULL,
        applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    # Table 2: session context
    """CREATE TABLE IF NOT EXISTS sessions (
        id         TEXT PRIMARY KEY,
        sender     TEXT,
        topic      TEXT,
        project    TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    )""",
    # Table 3: per-gate status
    """CREATE TABLE IF NOT EXISTS gate_state (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT NOT NULL,
        project     TEXT NOT NULL,
        gate_name   TEXT NOT NULL,
        state       TEXT NOT NULL DEFAULT 'BLOCK'
                    CHECK(state IN ('PASS','SKIP','WARN','BLOCK','PENDING')),
        mandatory   INTEGER NOT NULL DEFAULT 1,
        duration_ms INTEGER,
        message     TEXT,
        result_data TEXT,
        created_at  TEXT NOT NULL DEFAULT (datetime('now')),
        updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
        UNIQUE(session_id, project, gate_name)
    )""",
    # Index for gate_state lookups
    "CREATE INDEX IF NOT EXISTS idx_gate_state_lookup ON gate_state(session_id, project)",
    # Table 4: audit log
    """CREATE TABLE IF NOT EXISTS gate_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT,
        gate_name   TEXT,
        from_state  TEXT,
        to_state    TEXT,
        reason      TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    )""",
    # Table 5: triple-match checkpoints
    """CREATE TABLE IF NOT EXISTS checkpoints (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT,
        gate_name   TEXT,
        raw_result  TEXT,
        extracted   TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    )""",
    # Table 6: missions
    """CREATE TABLE IF NOT EXISTS missions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id    TEXT NOT NULL,
        project       TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'active'
                      CHECK(status IN ('active','completed','failed','aborted')),
        gates_passed  INTEGER NOT NULL DEFAULT 0,
        gates_total   INTEGER NOT NULL DEFAULT 3,
        started_at    TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at  TEXT,
        last_gate_run TEXT,
        UNIQUE(session_id, project)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_missions_active ON missions(status, started_at)",
]

# ── Persistence class ───────────────────────────────────────────────────

class Persistence:
    """Thread-safe SQLite persistence layer for gate state."""

    def __init__(self, db_path: Optional[str] = None):
        raw_path = db_path or os.path.expanduser("~/.hermes/ultratimonel.db")
        self._is_memory = raw_path == ":memory:"
        if self._is_memory:
            # Use a temp file instead of :memory: — WAL mode doesn't work
            # reliably with SQLite shared-memory across connections.
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            tmp.close()
            self._db_path = tmp.name
            self._cleanup_path = self._db_path
        else:
            self._db_path = raw_path
            self._cleanup_path = None
        self._lock = threading.Lock()
        self._init_db()

    def close(self) -> None:
        """Clean up temp file if one was created."""
        if self._cleanup_path and os.path.exists(self._cleanup_path):
            try:
                os.unlink(self._cleanup_path)
            except OSError:
                pass

    def __del__(self) -> None:
        self.close()

    # ── public helpers ──────────────────────────────────────────────────

    @contextmanager
    def _conn(self):
        """Yield a sqlite3 connection with retry on SQLITE_BUSY.

        Retries up to 3 times with 100ms backoff when SQLITE_BUSY is
        encountered, per gate-persistence spec §6 DB_LOCKED error handling.
        """
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except sqlite3.OperationalError as exc:
            if "database is locked" in str(exc):
                import time as _time
                for attempt in range(3):
                    _time.sleep(0.1 * (attempt + 1))
                    try:
                        conn.commit()
                        break
                    except sqlite3.OperationalError as retry_exc:
                        if "database is locked" not in str(retry_exc):
                            conn.rollback()
                            raise
                        if attempt == 2:
                            conn.rollback()
                            raise
            else:
                conn.rollback()
                raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Create / migrate the database."""
        if not self._is_memory:
            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        with self._lock:
            with self._conn() as conn:
                if not self._is_memory:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    conn.execute("PRAGMA busy_timeout=5000")

                # Ensure schema_version table exists first
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_version ("
                    "  version INTEGER PRIMARY KEY,"
                    "  description TEXT NOT NULL,"
                    "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
                    ")"
                )

                # get current schema version
                cur = conn.execute(
                    "SELECT COALESCE(MAX(version),0) FROM schema_version"
                )
                current_ver = cur.fetchone()[0]

                if current_ver < SCHEMA_VERSION:
                    for stmt in DDL:
                        try:
                            conn.execute(stmt)
                        except sqlite3.OperationalError as exc:
                            # Table may already exist in :memory: context
                            if "already exists" not in str(exc):
                                raise
                    if current_ver == 0:
                        conn.execute(
                            "INSERT OR IGNORE INTO schema_version"
                            " (version, description) VALUES (?, ?)",
                            (SCHEMA_VERSION, SCHEMA_DESCRIPTION),
                        )
                    logger.info(
                        "DB schema v%s applied at %s",
                        SCHEMA_VERSION, self._db_path,
                    )

    # ── session CRUD ────────────────────────────────────────────────────

    def upsert_session(
        self,
        session_id: str,
        sender: str,
        topic: str,
        project: str,
    ) -> None:
        """Insert or update a session row."""
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO sessions (id, sender, topic, project)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                           sender=excluded.sender,
                           topic=excluded.topic,
                           project=excluded.project""",
                    (session_id, sender, topic, project),
                )

    def get_session(self, session_id: str) -> Optional[dict]:
        """Retrieve a session by id."""
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM sessions WHERE id = ?",
                    (session_id,),
                ).fetchone()
                return dict(row) if row else None

    # ── gate_state CRUD ─────────────────────────────────────────────────

    def upsert_gate_state(
        self,
        session_id: str,
        project: str,
        gate_name: str,
        state: str,
        mandatory: bool = True,
        duration_ms: Optional[int] = None,
        message: str = "",
        result_data: Optional[dict] = None,
    ) -> None:
        """Insert or update a gate's state."""
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO gate_state
                           (session_id, project, gate_name, state,
                            mandatory, duration_ms, message, result_data)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(session_id, project, gate_name) DO UPDATE SET
                           state      = excluded.state,
                           mandatory  = excluded.mandatory,
                           duration_ms= excluded.duration_ms,
                           message    = excluded.message,
                           result_data= excluded.result_data,
                           updated_at = datetime('now')""",
                    (
                        session_id,
                        project,
                        gate_name,
                        state,
                        1 if mandatory else 0,
                        duration_ms,
                        message,
                        json.dumps(result_data) if result_data else None,
                    ),
                )

    def get_gate_state(
        self,
        session_id: str,
        project: str,
        gate_name: str,
    ) -> Optional[dict]:
        """Get current gate state for a gate."""
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    """SELECT gate_name, state, mandatory, duration_ms,
                              message, result_data, updated_at
                       FROM gate_state
                       WHERE session_id = ? AND project = ? AND gate_name = ?""",
                    (session_id, project, gate_name),
                ).fetchone()
                if row is None:
                    return None
                result = dict(row)
                if result.get("result_data"):
                    try:
                        result["result_data"] = json.loads(result["result_data"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                return result

    def list_gate_states(
        self,
        session_id: str,
        project: str,
    ) -> list[dict]:
        """List all gate states for a session+project."""
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT gate_name, state, mandatory, duration_ms,
                              message, result_data, updated_at
                       FROM gate_state
                       WHERE session_id = ? AND project = ?
                       ORDER BY gate_name""",
                    (session_id, project),
                ).fetchall()
                results = []
                for r in rows:
                    d = dict(r)
                    if d.get("result_data"):
                        try:
                            d["result_data"] = json.loads(d["result_data"])
                        except (json.JSONDecodeError, TypeError):
                            pass
                    results.append(d)
                return results

    # ── gate_log ────────────────────────────────────────────────────────

    def log_transition(
        self,
        session_id: str,
        gate_name: str,
        from_state: str,
        to_state: str,
        reason: str = "",
    ) -> None:
        """Record a gate state transition."""
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO gate_logs
                           (session_id, gate_name, from_state, to_state, reason)
                       VALUES (?, ?, ?, ?, ?)""",
                    (session_id, gate_name, from_state, to_state, reason),
                )

    # ── checkpoints ─────────────────────────────────────────────────────

    def save_checkpoint(
        self,
        session_id: str,
        gate_name: str,
        raw_result: str,
        extracted: str = "",
    ) -> None:
        """Store a triple-match checkpoint snapshot."""
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO checkpoints
                           (session_id, gate_name, raw_result, extracted)
                       VALUES (?, ?, ?, ?)""",
                    (session_id, gate_name, raw_result, extracted),
                )

    # ── missions ────────────────────────────────────────────────────────

    def upsert_mission(
        self,
        session_id: str,
        project: str,
        gates_passed: int = 0,
        gates_total: int = 3,
    ) -> None:
        """Create or update a mission record."""
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO missions
                           (session_id, project, status,
                            gates_passed, gates_total, last_gate_run)
                       VALUES (?, ?, 'active', ?, ?, datetime('now'))
                       ON CONFLICT(session_id, project) DO UPDATE SET
                           gates_passed  = excluded.gates_passed,
                           gates_total   = excluded.gates_total,
                           last_gate_run = datetime('now')""",
                    (session_id, project, gates_passed, gates_total),
                )

    def complete_mission(
        self,
        session_id: str,
        project: str,
        status: str = "completed",
    ) -> None:
        """Mark a mission as completed/failed/aborted."""
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE missions
                       SET status = ?, completed_at = datetime('now')
                       WHERE session_id = ? AND project = ?""",
                    (status, session_id, project),
                )

    def get_mission(
        self,
        session_id: str,
        project: str,
    ) -> Optional[dict]:
        """Get mission record."""
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM missions WHERE session_id = ? AND project = ?",
                    (session_id, project),
                ).fetchone()
                return dict(row) if row else None
