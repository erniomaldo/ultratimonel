"""
persistence.py — SQLite layer for Ultratimonel gate state persistence.

Hierarchy:
  Project → Mission (Deck task, always has checklist)
              └── Checklist
                    └── Item
                          └── Intento (assert_gates 1a→1e cycle)
                                ├── Gate 1a → acción
                                ├── Gate 1b → acción
                                ├── Gate 1c → acción
                                └── Gate 1e → acción

Schema v2:
  - schema_version:  incremental migration tracking
  - sessions:        per-gen context (sender, topic, project)
  - gate_state:      per-gate status per session+project
  - gate_logs:       audit trail for every state transition
  - checkpoints:     triple-match raw/extracted snapshots
  - actions:         session-level summary (legacy, migrated from old missions)
  - missions:        Deck-linked tasks (synced one-way from Nextcloud)
  - checklist_items: items inside a mission's checklist
  - intentos:        assert_gates run for a specific checklist item

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

SCHEMA_VERSION = 3
SCHEMA_DESCRIPTION = "v3: gates_detail JSON column on intentos for turn completeness"

DDL_V2 = [
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
    # Table 3: per-gate status (unchanged from v1)
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
    "CREATE INDEX IF NOT EXISTS idx_gate_state_lookup ON gate_state(session_id, project)",
    # Table 4: audit log (unchanged from v1)
    """CREATE TABLE IF NOT EXISTS gate_logs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT,
        gate_name   TEXT,
        from_state  TEXT,
        to_state    TEXT,
        reason      TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    )""",
    # Table 5: triple-match checkpoints (unchanged from v1)
    """CREATE TABLE IF NOT EXISTS checkpoints (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id  TEXT,
        gate_name   TEXT,
        raw_result  TEXT,
        extracted   TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    )""",
    # Table 6: actions — session-level summary (replaces old missions table)
    """CREATE TABLE IF NOT EXISTS actions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id    TEXT NOT NULL,
        project       TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'active'
                      CHECK(status IN ('active','completed','failed','aborted')),
        gates_passed  INTEGER NOT NULL DEFAULT 0,
        gates_total   INTEGER NOT NULL DEFAULT 4,
        started_at    TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at  TEXT,
        last_gate_run TEXT,
        UNIQUE(session_id, project)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_actions_project ON actions(project)",
    "CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status)",
    # Table 7: missions — Deck-linked tasks (synced from Nextcloud)
    """CREATE TABLE IF NOT EXISTS missions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        deck_task_id    INTEGER UNIQUE,
        project         TEXT NOT NULL,
        title           TEXT NOT NULL,
        description     TEXT DEFAULT '',
        status          TEXT NOT NULL DEFAULT 'pendiente'
                        CHECK(status IN ('pendiente','en_progreso','completada','bloqueada')),
        checklist_total INTEGER NOT NULL DEFAULT 0,
        checklist_done  INTEGER NOT NULL DEFAULT 0,
        last_sync       TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_missions_project ON missions(project)",
    "CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status)",
    # Table 8: checklist_items — items inside a mission's checklist
    """CREATE TABLE IF NOT EXISTS checklist_items (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        mission_id  INTEGER NOT NULL REFERENCES missions(id),
        item_index  INTEGER NOT NULL,
        text        TEXT NOT NULL,
        done        INTEGER NOT NULL DEFAULT 0,
        UNIQUE(mission_id, item_index)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_checklist_mission ON checklist_items(mission_id)",
    # Table 9: intentos — one assert_gates cycle (1a→1e) for a checklist item
    """CREATE TABLE IF NOT EXISTS intentos (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id        TEXT NOT NULL,
        project           TEXT NOT NULL,
        mission_id        INTEGER NOT NULL REFERENCES missions(id),
        checklist_item_id INTEGER NOT NULL REFERENCES checklist_items(id),
        status            TEXT NOT NULL DEFAULT 'running'
                          CHECK(status IN ('running','success','fail')),
        gates_passed      INTEGER NOT NULL DEFAULT 0,
        gates_total       INTEGER NOT NULL DEFAULT 4,
        started_at        TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at      TEXT
    )""",
    "CREATE INDEX IF NOT EXISTS idx_intentos_checklist ON intentos(checklist_item_id)",
    "CREATE INDEX IF NOT EXISTS idx_intentos_mission ON intentos(mission_id)",
    "CREATE INDEX IF NOT EXISTS idx_intentos_session ON intentos(session_id)",
]


def _is_v1_style_missions_table(conn) -> bool:
    """Check if the missions table has the old schema (session_id column)."""
    cursor = conn.execute("PRAGMA table_info(missions)")
    cols = {row[1] for row in cursor.fetchall()}
    return "session_id" in cols


def _migrate_v1_to_v2(conn) -> None:
    """Migrate from v1 schema to v2.

    v1 table `missions` (session_id-based) → renamed to `actions`.
    New `missions` table (Deck-linked) created.
    New `checklist_items` and `intentos` tables created.
    """
    # 1. Create actions table if it doesn't exist
    conn.execute("""CREATE TABLE IF NOT EXISTS actions (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id    TEXT NOT NULL,
        project       TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'active'
                      CHECK(status IN ('active','completed','failed','aborted')),
        gates_passed  INTEGER NOT NULL DEFAULT 0,
        gates_total   INTEGER NOT NULL DEFAULT 4,
        started_at    TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at  TEXT,
        last_gate_run TEXT,
        UNIQUE(session_id, project)
    )""")

    # 2. Check if old missions table has data and migrate if needed
    has_old_missions = False
    old_count = 0
    try:
        row = conn.execute("SELECT COUNT(*) FROM missions").fetchone()
        if row and row[0] > 0 and _is_v1_style_missions_table(conn):
            has_old_missions = True
            old_count = row[0]
    except sqlite3.OperationalError:
        pass  # missions table doesn't exist yet

    if has_old_missions:
        # Migrate old missions data into actions
        conn.execute("""INSERT OR IGNORE INTO actions
            (session_id, project, status, gates_passed, gates_total, started_at, completed_at, last_gate_run)
            SELECT session_id, project, status, gates_passed, gates_total,
                   started_at, completed_at, last_gate_run
            FROM missions
        """)
        # Drop old missions table
        conn.execute("DROP TABLE IF EXISTS missions")
        logger.info("Migrated %d records from old missions → actions", old_count)

    # 3. Create NEW missions table (Deck-linked)
    conn.execute("""CREATE TABLE IF NOT EXISTS missions (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        deck_task_id    INTEGER UNIQUE,
        project         TEXT NOT NULL,
        title           TEXT NOT NULL,
        description     TEXT DEFAULT '',
        status          TEXT NOT NULL DEFAULT 'pendiente'
                        CHECK(status IN ('pendiente','en_progreso','completada','bloqueada')),
        checklist_total INTEGER NOT NULL DEFAULT 0,
        checklist_done  INTEGER NOT NULL DEFAULT 0,
        last_sync       TEXT,
        created_at      TEXT NOT NULL DEFAULT (datetime('now'))
    )""")

    # 4. Create checklist_items table
    conn.execute("""CREATE TABLE IF NOT EXISTS checklist_items (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        mission_id  INTEGER NOT NULL REFERENCES missions(id),
        item_index  INTEGER NOT NULL,
        text        TEXT NOT NULL,
        done        INTEGER NOT NULL DEFAULT 0,
        UNIQUE(mission_id, item_index)
    )""")

    # 5. Create intentos table
    conn.execute("""CREATE TABLE IF NOT EXISTS intentos (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id        TEXT NOT NULL,
        project           TEXT NOT NULL,
        mission_id        INTEGER NOT NULL REFERENCES missions(id),
        checklist_item_id INTEGER NOT NULL REFERENCES checklist_items(id),
        status            TEXT NOT NULL DEFAULT 'running'
                          CHECK(status IN ('running','success','fail')),
        gates_passed      INTEGER NOT NULL DEFAULT 0,
        gates_total       INTEGER NOT NULL DEFAULT 4,
        started_at        TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at      TEXT
    )""")

    # 6. Create indexes
    for idx in [
        "CREATE INDEX IF NOT EXISTS idx_actions_project ON actions(project)",
        "CREATE INDEX IF NOT EXISTS idx_actions_status ON actions(status)",
        "CREATE INDEX IF NOT EXISTS idx_actions_session ON actions(session_id)",
        "CREATE INDEX IF NOT EXISTS idx_missions_project ON missions(project)",
        "CREATE INDEX IF NOT EXISTS idx_missions_status ON missions(status)",
        "CREATE INDEX IF NOT EXISTS idx_checklist_mission ON checklist_items(mission_id)",
        "CREATE INDEX IF NOT EXISTS idx_intentos_checklist ON intentos(checklist_item_id)",
        "CREATE INDEX IF NOT EXISTS idx_intentos_mission ON intentos(mission_id)",
        "CREATE INDEX IF NOT EXISTS idx_intentos_session ON intentos(session_id)",
    ]:
        conn.execute(idx)


# ── Persistence class ───────────────────────────────────────────────────

class Persistence:
    """Thread-safe SQLite persistence layer for gate state."""

    def __init__(self, db_path: Optional[str] = None):
        raw_path = db_path or os.path.expanduser("~/.hermes/ultratimonel.db")
        self._is_memory = raw_path == ":memory:"
        if self._is_memory:
            import tempfile
            tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
            tmp.close()
            self._db_path = tmp.name
            self._cleanup_path = self._db_path
        else:
            self._db_path = raw_path
            self._cleanup_path = None
        # RLock (reentrant) so nested methods like list_missions() can call
        # list_checklist_items() without deadlocking. With a plain Lock the
        # inner call would block forever waiting for the outer call to release.
        self._lock = threading.RLock()
        self._init_db()

    def close(self) -> None:
        if self._cleanup_path and os.path.exists(self._cleanup_path):
            try:
                os.unlink(self._cleanup_path)
            except OSError:
                pass

    def __del__(self) -> None:
        self.close()

    # ── helpers ────────────────────────────────────────────────────────

    @contextmanager
    def _conn(self):
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
        if not self._is_memory:
            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)
        with self._lock:
            with self._conn() as conn:
                if not self._is_memory:
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    conn.execute("PRAGMA busy_timeout=5000")

                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_version ("
                    "  version INTEGER PRIMARY KEY,"
                    "  description TEXT NOT NULL,"
                    "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
                    ")"
                )

                cur = conn.execute(
                    "SELECT COALESCE(MAX(version),0) FROM schema_version"
                )
                current_ver = cur.fetchone()[0]

                if current_ver == 0:
                    # Fresh DB — apply v2 DDL then add v3 columns
                    for stmt in DDL_V2:
                        try:
                            conn.execute(stmt)
                        except sqlite3.OperationalError as exc:
                            if "already exists" not in str(exc):
                                raise
                    # Add v3 additions for fresh install
                    try:
                        conn.execute(
                            "ALTER TABLE intentos ADD COLUMN gates_detail TEXT"
                        )
                    except sqlite3.OperationalError:
                        pass
                    conn.execute(
                        "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                        (SCHEMA_VERSION, SCHEMA_DESCRIPTION),
                    )
                    logger.info("Fresh DB initialized at schema v3: %s", self._db_path)
                elif current_ver == 1:
                    # Migration v1 → v2
                    _migrate_v1_to_v2(conn)
                    conn.execute(
                        "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                        (SCHEMA_VERSION, SCHEMA_DESCRIPTION),
                    )
                    logger.info("Migrated DB v1→v2: %s", self._db_path)
                elif current_ver == 2:
                    # Migration v2 → v3: add gates_detail column to intentos
                    try:
                        conn.execute(
                            "ALTER TABLE intentos ADD COLUMN gates_detail TEXT"
                        )
                        logger.info("Migrated DB v2→v3: added gates_detail to intentos")
                    except sqlite3.OperationalError:
                        pass  # column already exists (idempotent)
                    conn.execute(
                        "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                        (SCHEMA_VERSION, SCHEMA_DESCRIPTION),
                    )
                    logger.info("Migrated DB v2→v3: %s", self._db_path)
                elif current_ver == SCHEMA_VERSION:
                    # Already current — ensure all tables exist
                    for stmt in DDL_V2:
                        try:
                            conn.execute(stmt)
                        except sqlite3.OperationalError as exc:
                            if "already exists" not in str(exc):
                                raise
                    # Ensure v3 column exists (idempotent)
                    try:
                        conn.execute("ALTER TABLE intentos ADD COLUMN gates_detail TEXT")
                    except sqlite3.OperationalError:
                        pass  # column already exists
                    logger.debug("DB schema up to date (v%s)", SCHEMA_VERSION)

    # ── session CRUD ───────────────────────────────────────────────────

    def upsert_session(
        self,
        session_id: str,
        sender: str,
        topic: str,
        project: str,
    ) -> None:
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
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    """SELECT gate_name, state, mandatory, duration_ms,
                              message, result_data, updated_at
                       FROM gate_state
                       WHERE id IN (
                           SELECT MAX(id)
                           FROM gate_state
                           WHERE session_id = ? AND project = ?
                           GROUP BY gate_name
                       )
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

    def get_latest_gate_states_by_project(self, project: str) -> list[dict]:
        """Get the most recent gate states for each gate_name in a project.

        Returns one row per gate_name with the latest session's state.
        """
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT gs.gate_name, gs.state, gs.mandatory,
                           gs.duration_ms, gs.message, gs.updated_at
                    FROM gate_state gs
                    INNER JOIN (
                        SELECT gate_name, MAX(id) as max_id
                        FROM gate_state
                        WHERE project = ?
                        GROUP BY gate_name
                    ) latest ON gs.id = latest.max_id
                    ORDER BY gs.gate_name
                """, (project,)).fetchall()
                return [dict(r) for r in rows]

    # ── gate_log ────────────────────────────────────────────────────────

    def log_transition(
        self,
        session_id: str,
        gate_name: str,
        from_state: str,
        to_state: str,
        reason: str = "",
    ) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO gate_logs
                           (session_id, gate_name, from_state, to_state, reason)
                       VALUES (?, ?, ?, ?, ?)""",
                    (session_id, gate_name, from_state, to_state, reason),
                )

    def get_gate_logs_for_project(
        self,
        project: str,
        gate_name: str,
        limit: int = 50,
    ) -> list[dict]:
        """Get gate transition logs for a specific gate in a project."""
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT gl.id, gl.session_id, gl.gate_name,
                           gl.from_state, gl.to_state, gl.reason, gl.created_at
                    FROM gate_logs gl
                    JOIN sessions s ON s.id = gl.session_id
                    WHERE s.project = ? AND gl.gate_name = ?
                    ORDER BY gl.created_at DESC
                    LIMIT ?
                """, (project, gate_name, limit)).fetchall()
                return [dict(r) for r in rows]

    # ── checkpoints ─────────────────────────────────────────────────────

    def save_checkpoint(
        self,
        session_id: str,
        gate_name: str,
        raw_result: str,
        extracted: str = "",
    ) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO checkpoints
                           (session_id, gate_name, raw_result, extracted)
                       VALUES (?, ?, ?, ?)""",
                    (session_id, gate_name, raw_result, extracted),
                )

    # ── actions (session-level summary, migrated from old missions) ─────

    def upsert_action(
        self,
        session_id: str,
        project: str,
        gates_passed: int = 0,
        gates_total: int = 4,
    ) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO actions
                           (session_id, project, status,
                            gates_passed, gates_total, last_gate_run)
                       VALUES (?, ?, 'active', ?, ?, datetime('now'))
                       ON CONFLICT(session_id, project) DO UPDATE SET
                           gates_passed  = excluded.gates_passed,
                           gates_total   = excluded.gates_total,
                           last_gate_run = datetime('now')""",
                    (session_id, project, gates_passed, gates_total),
                )

    def complete_action(
        self,
        session_id: str,
        project: str,
        status: str = "completed",
    ) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE actions
                       SET status = ?, completed_at = datetime('now')
                       WHERE session_id = ? AND project = ?""",
                    (status, session_id, project),
                )

    def list_actions(self, project: str) -> list[dict]:
        """List action records (session-level) for a project."""
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT id, session_id, project, status,
                           gates_passed, gates_total,
                           started_at, completed_at, last_gate_run
                    FROM actions
                    WHERE project = ?
                    ORDER BY started_at DESC
                """, (project,)).fetchall()
                return [dict(r) for r in rows]

    # ── missions (Deck-linked) ──────────────────────────────────────────

    def upsert_mission(
        self,
        deck_task_id: int,
        project: str,
        title: str,
        description: str = "",
        status: str = "pendiente",
        checklist_total: int = 0,
        checklist_done: int = 0,
    ) -> int:
        """Insert or update a mission (Deck task sync). Returns mission id."""
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO missions
                           (deck_task_id, project, title, description, status,
                            checklist_total, checklist_done, last_sync)
                       VALUES (?, ?, ?, ?, ?, ?, ?, datetime('now'))
                       ON CONFLICT(deck_task_id) DO UPDATE SET
                           title           = excluded.title,
                           description     = excluded.description,
                           status          = excluded.status,
                           checklist_total = excluded.checklist_total,
                           checklist_done  = excluded.checklist_done,
                           last_sync       = datetime('now')""",
                    (deck_task_id, project, title, description, status,
                     checklist_total, checklist_done),
                )
                row = conn.execute(
                    "SELECT id FROM missions WHERE deck_task_id = ?",
                    (deck_task_id,),
                ).fetchone()
                return row["id"] if row else 0

    def get_mission(self, mission_id: int) -> Optional[dict]:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM missions WHERE id = ?",
                    (mission_id,),
                ).fetchone()
                return dict(row) if row else None

    def list_missions(self, project: str) -> list[dict]:
        """List missions for a project."""
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT id, deck_task_id, project, title, description,
                           status, checklist_total, checklist_done, last_sync, created_at
                    FROM missions
                    WHERE project = ?
                    ORDER BY created_at DESC
                """, (project,)).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    d["checklist_items"] = self.list_checklist_items(d["id"])
                    result.append(d)
                return result

    def count_missions_by_project(self, project: str) -> int:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM missions WHERE project = ?",
                    (project,),
                ).fetchone()
                return row[0] if row else 0

    def get_mission_counts_by_project(self) -> list[dict]:
        """Get mission counts grouped by project."""
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT project,
                           COUNT(*) as mission_count,
                           SUM(CASE WHEN status = 'completada' THEN 1 ELSE 0 END) as completed_count,
                           MAX(created_at) as last_activity
                    FROM missions
                    GROUP BY project
                    ORDER BY last_activity DESC
                """).fetchall()
                result = []
                for r in rows:
                    d = dict(r)
                    d["mission_count"] = d.get("mission_count") or 0
                    d["completed_count"] = d.get("completed_count") or 0
                    result.append(d)
                return result

    # ── checklist_items ─────────────────────────────────────────────────

    def upsert_checklist_item(
        self,
        mission_id: int,
        item_index: int,
        text: str,
        done: int = 0,
    ) -> int:
        """Insert or update a checklist item. Returns item id."""
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO checklist_items
                           (mission_id, item_index, text, done)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(mission_id, item_index) DO UPDATE SET
                           text = excluded.text,
                           done = excluded.done""",
                    (mission_id, item_index, text, done),
                )
                row = conn.execute(
                    "SELECT id FROM checklist_items WHERE mission_id = ? AND item_index = ?",
                    (mission_id, item_index),
                ).fetchone()
                return row["id"] if row else 0

    def list_checklist_items(self, mission_id: int) -> list[dict]:
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT id, mission_id, item_index, text, done
                    FROM checklist_items
                    WHERE mission_id = ?
                    ORDER BY item_index
                """, (mission_id,)).fetchall()
                return [dict(r) for r in rows]

    def get_checklist_item_by_id(self, checklist_item_id: int) -> "Optional[dict]":
        """Retrieve a single checklist item by its primary key."""
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT id, mission_id, item_index, text, done"
                    " FROM checklist_items WHERE id = ?",
                    (checklist_item_id,),
                ).fetchone()
                return dict(row) if row else None

    # ── intentos ────────────────────────────────────────────────────────

    def create_intento(
        self,
        session_id: str,
        project: str,
        mission_id: int,
        checklist_item_id: int,
    ) -> int:
        """Create a new intento (assert_gates cycle for a checklist item). Returns id."""
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO intentos
                           (session_id, project, mission_id, checklist_item_id, status)
                       VALUES (?, ?, ?, ?, 'running')""",
                    (session_id, project, mission_id, checklist_item_id),
                )
                return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def complete_intento(
        self,
        intento_id: int,
        status: str,
        gates_passed: int,
    ) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE intentos
                       SET status = ?, gates_passed = ?, completed_at = datetime('now')
                       WHERE id = ?""",
                    (status, gates_passed, intento_id),
                )

    def capture_gates_for_intento(
        self,
        intento_id: int,
        gates: list[dict],
    ) -> None:
        """Persist gate snapshot into the intento's gates_detail column.

        Args:
            intento_id: Numeric intento ID.
            gates: List of gate dicts from list_gate_states().
        """
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE intentos
                       SET gates_detail = ?
                       WHERE id = ?""",
                    (json.dumps(gates, ensure_ascii=False, default=str), intento_id),
                )

    def complete_intento_with_gates(
        self,
        intento_id: int,
        status: str,
        gates_passed: int,
        gates_detail: list[dict],
    ) -> None:
        """Complete an intento with full gate detail snapshot.

        Args:
            intento_id:     Numeric intento ID.
            status:         Final status ('success' or 'fail').
            gates_passed:   Count of gates that passed (PASS + SKIP).
            gates_detail:   Full gate snapshot as list of dicts.
        """
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE intentos
                       SET status = ?,
                           gates_passed = ?,
                           gates_detail = ?,
                           completed_at = datetime('now')
                       WHERE id = ?""",
                    (
                        status,
                        gates_passed,
                        json.dumps(gates_detail, ensure_ascii=False, default=str),
                        intento_id,
                    ),
                )

    def get_intento(self, intento_id: int) -> Optional[dict]:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM intentos WHERE id = ?",
                    (intento_id,),
                ).fetchone()
                return dict(row) if row else None

    def list_intentos_by_checklist_item(self, checklist_item_id: int) -> list[dict]:
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT id, session_id, project, mission_id,
                           checklist_item_id, status, gates_passed, gates_total,
                           started_at, completed_at
                    FROM intentos
                    WHERE checklist_item_id = ?
                    ORDER BY started_at DESC
                """, (checklist_item_id,)).fetchall()
                return [dict(r) for r in rows]

    def get_intento_with_gates(self, intento_id: int) -> Optional[dict]:
        """Return intento with its gate states."""
        with self._lock:
            with self._conn() as conn:
                intento = conn.execute(
                    "SELECT * FROM intentos WHERE id = ?",
                    (intento_id,),
                ).fetchone()
                if not intento:
                    return None
                result = dict(intento)

                # Get gates for this session
                gates = conn.execute("""
                    SELECT gate_name, state, mandatory, duration_ms, message,
                           result_data, updated_at
                    FROM gate_state
                    WHERE session_id = ? AND project = ?
                    ORDER BY gate_name
                """, (result["session_id"], result["project"])).fetchall()
                result["gates"] = [dict(g) for g in gates]

                return result

    def delete_intento(self, intento_id: int) -> bool:
        """Delete an intento by id. Returns True if deleted, False if not found."""
        with self._lock:
            with self._conn() as conn:
                cursor = conn.execute("DELETE FROM intentos WHERE id = ?", (intento_id,))
                return cursor.rowcount > 0

    # ── backward compat (old upsert_mission name → routes to actions) ───

    def upsert_mission_legacy(
        self,
        session_id: str,
        project: str,
        gates_passed: int = 0,
        gates_total: int = 4,
    ) -> None:
        """Legacy: old code calling upsert_mission now writes to actions."""
        self.upsert_action(session_id, project, gates_passed, gates_total)
