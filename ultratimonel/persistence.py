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

SCHEMA_VERSION = 9
SCHEMA_DESCRIPTION = (
    "v9: quest_identity_migrations audit ledger (marker identity migration)"
)

# v6 tables — shared by the fresh-DB DDL and the v5→v6 migration (additive, D9).
DDL_V6_TABLES = [
    # Table 11: attempt_grants — append-only ledger of granted attempts (D1)
    """CREATE TABLE IF NOT EXISTS attempt_grants (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        mission_id        INTEGER NOT NULL,
        checklist_item_id INTEGER NOT NULL,
        amount            INTEGER NOT NULL,
        granted_by        TEXT NOT NULL,
        created_at        TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_attempt_grants_item ON attempt_grants(checklist_item_id)",
    # Table 12: turn_bitacora — append-only turn log (D8)
    """CREATE TABLE IF NOT EXISTS turn_bitacora (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        intento_id        INTEGER NOT NULL,
        session_id        TEXT NOT NULL,
        project           TEXT NOT NULL,
        mission_id        INTEGER NOT NULL,
        checklist_item_id INTEGER NOT NULL,
        final_status      TEXT NOT NULL,
        gates_passed      INTEGER NOT NULL,
        summary           TEXT,
        created_at        TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_turn_bitacora_mission ON turn_bitacora(mission_id)",
]

# v6 columns — idempotent ALTERs applied by the v5→v6 migration.
DDL_V6_ALTERS = [
    "ALTER TABLE checklist_items ADD COLUMN attempts_authorized INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE checklist_items ADD COLUMN attempts_used INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE intentos ADD COLUMN summary TEXT",
    "ALTER TABLE intentos ADD COLUMN evidence TEXT",
    "ALTER TABLE intentos ADD COLUMN closed_at TEXT",
]

# v7: intentos.status widens to the honest terminal vocabulary. SQLite cannot
# ALTER a CHECK constraint, so v6→v7 rebuilds the table (see _migrate_v6_to_v7).
DDL_V7_INTENTOS = """CREATE TABLE IF NOT EXISTS intentos (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id        TEXT NOT NULL,
        project           TEXT NOT NULL,
        mission_id        INTEGER NOT NULL REFERENCES missions(id),
        checklist_item_id INTEGER NOT NULL REFERENCES checklist_items(id),
        status            TEXT NOT NULL DEFAULT 'running'
                          CHECK(status IN ('running','success','fail','aborted','partial')),
        gates_passed      INTEGER NOT NULL DEFAULT 0,
        gates_total       INTEGER NOT NULL DEFAULT 4,
        started_at        TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at      TEXT,
        summary           TEXT,
        evidence          TEXT,
        closed_at         TEXT,
        gates_detail      TEXT
    )"""

DDL_V7_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_intentos_checklist ON intentos(checklist_item_id)",
    "CREATE INDEX IF NOT EXISTS idx_intentos_mission ON intentos(mission_id)",
    "CREATE INDEX IF NOT EXISTS idx_intentos_session ON intentos(session_id)",
]

# Columns copied verbatim by the v6→v7 table rebuild (identity + data only).
INTENTOS_V7_COLUMNS = (
    "id, session_id, project, mission_id, checklist_item_id, status, "
    "gates_passed, gates_total, started_at, completed_at, summary, evidence, "
    "closed_at, gates_detail"
)

# v8 tables — append-only audit of replica-only mission deletions.
#
# ``turn_bitacora`` cannot carry this event: its rows are keyed by mission_id
# and are themselves deleted with the mission, so an audit row stored there
# would vanish in the same transaction. ``gate_logs`` is gate-specific. The
# deletion ledger therefore lives in its own table and outlives the mission.
DDL_V8_TABLES = [
    """CREATE TABLE IF NOT EXISTS mission_deletions (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        mission_id        INTEGER NOT NULL,
        deck_task_id      INTEGER,
        project           TEXT,
        title             TEXT,
        reason            TEXT NOT NULL,
        requested_by      TEXT NOT NULL,
        quests_deleted    INTEGER NOT NULL DEFAULT 0,
        intentos_deleted  INTEGER NOT NULL DEFAULT 0,
        grants_deleted    INTEGER NOT NULL DEFAULT 0,
        bitacora_deleted  INTEGER NOT NULL DEFAULT 0,
        deleted_ids       TEXT,
        created_at        TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_mission_deletions_mission"
    " ON mission_deletions(mission_id)",
    # ``mission_deletions`` is mission-scoped and cannot describe a single
    # quest; ``quest_delete`` needs its own append-only ledger so the deleted
    # quest ids and their dependent rows survive the quest itself.
    """CREATE TABLE IF NOT EXISTS quest_deletions (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        mission_id        INTEGER NOT NULL,
        deck_task_id      INTEGER,
        quest_id          INTEGER NOT NULL,
        project           TEXT,
        text              TEXT,
        item_index        INTEGER,
        reason            TEXT NOT NULL,
        requested_by      TEXT NOT NULL,
        forced            INTEGER NOT NULL DEFAULT 0,
        intentos_deleted  INTEGER NOT NULL DEFAULT 0,
        grants_deleted    INTEGER NOT NULL DEFAULT 0,
        bitacora_deleted  INTEGER NOT NULL DEFAULT 0,
        deleted_ids       TEXT,
        created_at        TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_quest_deletions_mission"
    " ON quest_deletions(mission_id)",
]

# v9 table — append-only audit of quest identity migrations (card #218, quest 4).
#
# ``quest_deletions`` describes removals and ``mission_deletions`` whole
# missions; neither can record "this mission's quest lines gained their stable
# ids". The migration ledger therefore follows the same pattern: its own table,
# written in the same transaction as the mission description refresh.
DDL_V9_TABLES = [
    """CREATE TABLE IF NOT EXISTS quest_identity_migrations (
        id                INTEGER PRIMARY KEY AUTOINCREMENT,
        mission_id        INTEGER NOT NULL,
        deck_task_id      INTEGER,
        project           TEXT,
        reason            TEXT NOT NULL,
        requested_by      TEXT NOT NULL,
        quests_migrated   INTEGER NOT NULL DEFAULT 0,
        quest_ids         TEXT,
        migrated_ids      TEXT,
        created_at        TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    "CREATE INDEX IF NOT EXISTS idx_quest_identity_migrations_mission"
    " ON quest_identity_migrations(mission_id)",
]

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
        deck_stack_id   INTEGER,
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
        attempts_authorized INTEGER NOT NULL DEFAULT 0,
        attempts_used       INTEGER NOT NULL DEFAULT 0,
        UNIQUE(mission_id, item_index)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_checklist_mission ON checklist_items(mission_id)",
    # Table 9: intentos — one assert_gates cycle (1a→1e) for a checklist item
    DDL_V7_INTENTOS,
    "CREATE INDEX IF NOT EXISTS idx_intentos_checklist ON intentos(checklist_item_id)",
    "CREATE INDEX IF NOT EXISTS idx_intentos_mission ON intentos(mission_id)",
    "CREATE INDEX IF NOT EXISTS idx_intentos_session ON intentos(session_id)",
    # Table 10: session_turns — persistent turn counting per session (v4)
    """CREATE TABLE IF NOT EXISTS session_turns (
        session_id TEXT PRIMARY KEY,
        turn_count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
    # Tables 11–12: v6 attempt budget + append-only bitácora
    *DDL_V6_TABLES,
]


DDL_SESSION_TURNS = [
    """CREATE TABLE IF NOT EXISTS session_turns (
        session_id TEXT PRIMARY KEY,
        turn_count INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    )""",
]


# ── Migration Functions ─────────────────────────────────────────────────────

def _migrate_v3_to_v4(conn) -> None:
    """Migrate from v3 schema to v4 (add session_turns table)."""
    # Create the session_turns table
    conn.execute(DDL_SESSION_TURNS[0])

    # Record the target version explicitly so the migration chain stays
    # correct when SCHEMA_VERSION is bumped again (v4→v5 and beyond).
    conn.execute(
        "INSERT INTO schema_version (version, description) VALUES (?, ?)",
        (4, "v4: session_turns table for persistent turn counting"),
    )
    logger.info("Migrated DB v3→v4: added session_turns table")


def _migrate_v4_to_v5(conn) -> None:
    """Migrate from v4 schema to v5 (add missions.deck_stack_id).

    Additive only (NF-GP-05): a nullable column, no data rewrite, no
    destructive DDL. Older server code fails safe by ignoring the unknown
    version (SCHEMA_AHEAD contract in the gate-persistence spec).
    """
    try:
        conn.execute("ALTER TABLE missions ADD COLUMN deck_stack_id INTEGER")
    except sqlite3.OperationalError:
        pass  # column already exists (idempotent)
    conn.execute(
        "INSERT INTO schema_version (version, description) VALUES (?, ?)",
        (5, "v5: missions.deck_stack_id for deterministic Deck stack writes"),
    )
    logger.info("Migrated DB v4→v5: added missions.deck_stack_id")


def _migrate_v5_to_v6(conn) -> None:
    """v5→v6: additive attempt-budget columns/tables; idempotent (D9)."""
    for stmt in DDL_V6_ALTERS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists (idempotent)
    for stmt in DDL_V6_TABLES:
        conn.execute(stmt)
    # INSERT OR IGNORE keeps the migration replay-safe (a plain INSERT would
    # raise on the schema_version PK when the v6 row already exists). The
    # version is pinned to 6 so a later SCHEMA_VERSION bump cannot make this
    # step stamp a version whose migration has not run yet.
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (6, "v6: attempt budget (attempt_grants + checklist counters) and turn_bitacora"),
    )
    logger.info("Migrated DB v5→v6: attempt budget + turn_bitacora")


def _intentos_status_check_allows_honest_states(conn) -> bool:
    """True when the live ``intentos`` table already accepts aborted/partial."""
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='intentos'"
    ).fetchone()
    if row is None:
        return True  # no table yet: nothing to widen, fresh DDL will be used
    return "aborted" in (row[0] or "")


def _migrate_v6_to_v7(conn) -> None:
    """v6→v7: widen ``intentos.status`` CHECK to aborted/partial.

    SQLite cannot alter a CHECK constraint in place, so the table is rebuilt:
    rename, create the v7 table, copy every row verbatim, drop the old table,
    recreate the indexes. The whole rebuild runs inside one explicit
    transaction so a failure cannot leave a half-renamed table behind, and the
    guard against an already-widened CHECK makes replay a no-op.
    """
    if not _intentos_status_check_allows_honest_states(conn):
        if not conn.in_transaction:
            conn.execute("BEGIN IMMEDIATE")
        conn.execute("ALTER TABLE intentos RENAME TO intentos_v6_backup")
        conn.execute(DDL_V7_INTENTOS)
        conn.execute(
            f"INSERT INTO intentos ({INTENTOS_V7_COLUMNS}) "
            f"SELECT {INTENTOS_V7_COLUMNS} FROM intentos_v6_backup"
        )
        conn.execute("DROP TABLE intentos_v6_backup")
        for stmt in DDL_V7_INDEXES:
            conn.execute(stmt)
        logger.info("Migrated DB v6→v7: rebuilt intentos with honest status states")

    # INSERT OR IGNORE keeps the migration replay-safe. The version is pinned
    # to 7 so a later SCHEMA_VERSION bump cannot make this step stamp a version
    # whose migration has not run yet.
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (7, "v7: intentos.status accepts aborted/partial (honest terminal states)"),
    )


def _migrate_v7_to_v8(conn) -> None:
    """v7→v8: add the deletion audit ledgers.

    Additive only: ``mission_deletions`` and ``quest_deletions`` plus their
    indexes, no data rewrite and no destructive DDL. ``CREATE TABLE IF NOT
    EXISTS`` plus ``INSERT OR IGNORE`` make replay a no-op, and older code
    keeps working against the extra tables (SCHEMA_AHEAD).
    """
    for stmt in DDL_V8_TABLES:
        conn.execute(stmt)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (8, "v8: mission_deletions audit ledger (replica-only mission_delete)"),
    )
    logger.info("Migrated DB v7→v8: added mission_deletions audit ledger")


def _migrate_v8_to_v9(conn) -> None:
    """v8→v9: add the quest identity migration audit ledger.

    Additive only: ``quest_identity_migrations`` plus its index, no data
    rewrite and no destructive DDL. ``CREATE TABLE IF NOT EXISTS`` plus
    ``INSERT OR IGNORE`` make replay a no-op, and older code keeps working
    against the extra table (SCHEMA_AHEAD).
    """
    for stmt in DDL_V9_TABLES:
        conn.execute(stmt)
    conn.execute(
        "INSERT OR IGNORE INTO schema_version (version, description) VALUES (?, ?)",
        (
            9,
            "v9: quest_identity_migrations audit ledger "
            "(marker identity migration)",
        ),
    )
    logger.info("Migrated DB v8→v9: added quest identity migration ledger")


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
        deck_stack_id   INTEGER,
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
                    # Fresh DB — apply v2 DDL then add v3/v4/v5 additions
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
                    # Add v4 session_turns table for fresh install
                    conn.execute(DDL_SESSION_TURNS[0])
                    # v8 audit ledger (additive)
                    for stmt in DDL_V8_TABLES:
                        conn.execute(stmt)
                    # v9 quest identity migration ledger (additive)
                    for stmt in DDL_V9_TABLES:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT INTO schema_version (version, description) VALUES (?, ?)",
                        (SCHEMA_VERSION, SCHEMA_DESCRIPTION),
                    )
                    logger.info("Fresh DB initialized at schema v%s: %s", SCHEMA_VERSION, self._db_path)
                elif current_ver == 1:
                    # Migration v1 → v2
                    _migrate_v1_to_v2(conn)
                    # v2 → v3: add gates_detail column to intentos
                    try:
                        conn.execute(
                            "ALTER TABLE intentos ADD COLUMN gates_detail TEXT"
                        )
                    except sqlite3.OperationalError:
                        pass  # column already exists (idempotent)
                    # v3 → v4 → v5 → v6 → v7: session_turns + deck_stack_id +
                    # budget + honest intento statuses
                    _migrate_v3_to_v4(conn)
                    _migrate_v4_to_v5(conn)
                    _migrate_v5_to_v6(conn)
                    _migrate_v6_to_v7(conn)
                    _migrate_v7_to_v8(conn)
                    _migrate_v8_to_v9(conn)
                    logger.info("Migrated DB v1→v9: %s", self._db_path)
                elif current_ver == 2:
                    # Migration v2 → v3: add gates_detail column to intentos
                    try:
                        conn.execute(
                            "ALTER TABLE intentos ADD COLUMN gates_detail TEXT"
                        )
                        logger.info("Migrated DB v2→v3: added gates_detail to intentos")
                    except sqlite3.OperationalError:
                        pass  # column already exists (idempotent)
                    # v3 → v4 → v5 → v6 → v7: session_turns + deck_stack_id +
                    # budget + honest intento statuses. Routing through the
                    # chain keeps v2 DBs from being stamped current while
                    # session_turns is still missing.
                    _migrate_v3_to_v4(conn)
                    _migrate_v4_to_v5(conn)
                    _migrate_v5_to_v6(conn)
                    _migrate_v6_to_v7(conn)
                    _migrate_v7_to_v8(conn)
                    _migrate_v8_to_v9(conn)
                    logger.info("Migrated DB v2→v9: %s", self._db_path)
                elif current_ver == 3:
                    # Migration v3 → v4 → v5 → v6 → v7
                    _migrate_v3_to_v4(conn)
                    _migrate_v4_to_v5(conn)
                    _migrate_v5_to_v6(conn)
                    _migrate_v6_to_v7(conn)
                    _migrate_v7_to_v8(conn)
                    _migrate_v8_to_v9(conn)
                    logger.info("Migrated DB v3→v9: %s", self._db_path)
                elif current_ver == 4:
                    # Migration v4 → v5 → v6 → v7
                    _migrate_v4_to_v5(conn)
                    _migrate_v5_to_v6(conn)
                    _migrate_v6_to_v7(conn)
                    _migrate_v7_to_v8(conn)
                    _migrate_v8_to_v9(conn)
                    logger.info("Migrated DB v4→v9: %s", self._db_path)
                elif current_ver == 5:
                    # Migration v5 → v6 → v7
                    _migrate_v5_to_v6(conn)
                    _migrate_v6_to_v7(conn)
                    _migrate_v7_to_v8(conn)
                    _migrate_v8_to_v9(conn)
                    logger.info("Migrated DB v5→v9: %s", self._db_path)
                elif current_ver == 6:
                    # Migration v6 → v7 → v8: honest intento statuses + ledger
                    _migrate_v6_to_v7(conn)
                    _migrate_v7_to_v8(conn)
                    _migrate_v8_to_v9(conn)
                    logger.info("Migrated DB v6→v9: %s", self._db_path)
                elif current_ver == 7:
                    # Migration v7 → v8 → v9: deletion + migration ledgers
                    _migrate_v7_to_v8(conn)
                    _migrate_v8_to_v9(conn)
                    logger.info("Migrated DB v7→v9: %s", self._db_path)
                elif current_ver == 8:
                    # Migration v8 → v9: quest identity migration ledger
                    _migrate_v8_to_v9(conn)
                    logger.info("Migrated DB v8→v9: %s", self._db_path)
                elif current_ver == SCHEMA_VERSION:
                    # Already current — ensure all tables exist
                    for stmt in DDL_V2:
                        try:
                            conn.execute(stmt)
                        except sqlite3.OperationalError as exc:
                            if "already exists" not in str(exc):
                                raise
                    # Ensure v4 session_turns table exists (idempotent)
                    conn.execute(DDL_SESSION_TURNS[0])
                    # Ensure v3 column exists (idempotent)
                    try:
                        conn.execute("ALTER TABLE intentos ADD COLUMN gates_detail TEXT")
                    except sqlite3.OperationalError:
                        pass  # column already exists
                    # Ensure v5 column exists (idempotent, additive)
                    try:
                        conn.execute("ALTER TABLE missions ADD COLUMN deck_stack_id INTEGER")
                    except sqlite3.OperationalError:
                        pass  # column already exists
                    # v6 tables are ensured by DDL_V2 above; columns exist on a
                    # DB stamped v6 (fresh DDL or _migrate_v5_to_v6). Self-heal
                    # a v7 stamp whose intentos CHECK is still the v6 one: the
                    # guard makes this a no-op on an honest table.
                    _migrate_v6_to_v7(conn)
                    # Ensure the v8 audit ledger exists on a current DB.
                    for stmt in DDL_V8_TABLES:
                        conn.execute(stmt)
                    # Ensure the v9 quest identity migration ledger exists.
                    for stmt in DDL_V9_TABLES:
                        conn.execute(stmt)
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

    def get_mission_by_deck_task(self, deck_task_id: int) -> Optional[dict]:
        """Look up a mission by its Deck task id. Returns None if not found."""
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM missions WHERE deck_task_id = ?",
                    (deck_task_id,),
                ).fetchone()
                return dict(row) if row else None

    def set_mission_deck_stack_id(self, mission_id: int, deck_stack_id: int) -> bool:
        """Backfill a mission's replicated Deck stack id. Returns True if found.

        Replica field only; Deck remains the source of truth. Used by
        ``sync_task`` so later writes skip the ``deck_get_stacks`` lookup (D9).
        """
        with self._lock:
            with self._conn() as conn:
                cursor = conn.execute(
                    "UPDATE missions SET deck_stack_id = ? WHERE id = ?",
                    (deck_stack_id, mission_id),
                )
                return cursor.rowcount > 0

    def prune_mission(self, mission_id: int) -> bool:
        """Delete one mission and every row that depends on it.

        Internal helper for the drift-pruning branch of ``sync_tasks`` (card
        #218). It is NOT the public ``mission_delete`` tool: callers must have
        already proven the mission is an orphan against a complete Deck read.

        Deletion is a single transaction so a mission can never be left half
        removed (mission gone, quests still behind). Returns True when a
        mission row was actually deleted.
        """
        with self._lock:
            with self._conn() as conn:
                # turn_bitacora is keyed by mission_id (no FK enforcement).
                conn.execute(
                    "DELETE FROM turn_bitacora WHERE mission_id = ?", (mission_id,)
                )
                # attempt_grants carries mission_id/checklist_item_id, no FK.
                conn.execute(
                    "DELETE FROM attempt_grants WHERE mission_id = ?", (mission_id,)
                )
                conn.execute("DELETE FROM intentos WHERE mission_id = ?", (mission_id,))
                conn.execute(
                    "DELETE FROM checklist_items WHERE mission_id = ?", (mission_id,)
                )
                cursor = conn.execute("DELETE FROM missions WHERE id = ?", (mission_id,))
                return cursor.rowcount > 0

    def delete_mission(
        self,
        mission_id: int,
        reason: str,
        requested_by: str = "hermes",
    ) -> Optional[dict]:
        """Delete ONE mission and every replica row that depends on it.

        Replica-only: this never touches Deck. The card is not deleted,
        archived, or moved — ``mission_delete`` is a local cleanup operation.

        Everything happens in a single transaction, including the audit row, so
        the mission can never be left half removed and an audit entry can never
        describe a deletion that did not happen. The audit row itself is written
        to ``mission_deletions``, which is not keyed by the mission and therefore
        survives (unlike ``turn_bitacora`` rows, which are deleted with it).

        Returns a summary dict, or ``None`` when the mission does not exist.
        Raises ``ValueError`` when ``reason`` is empty — callers must pass a
        real justification before any row is touched.
        """
        if not (reason or "").strip():
            raise ValueError("mission_delete requires a non-empty reason")
        actor = (requested_by or "").strip() or "unknown"

        with self._lock:
            with self._conn() as conn:
                mission = conn.execute(
                    "SELECT * FROM missions WHERE id = ?", (mission_id,)
                ).fetchone()
                if mission is None:
                    return None

                quest_rows = conn.execute(
                    "SELECT id FROM checklist_items WHERE mission_id = ?",
                    (mission_id,),
                ).fetchall()
                intento_rows = conn.execute(
                    "SELECT id FROM intentos WHERE mission_id = ?",
                    (mission_id,),
                ).fetchall()
                grant_rows = conn.execute(
                    "SELECT id FROM attempt_grants WHERE mission_id = ?",
                    (mission_id,),
                ).fetchall()
                bitacora_rows = conn.execute(
                    "SELECT id FROM turn_bitacora WHERE mission_id = ?",
                    (mission_id,),
                ).fetchall()

                quest_ids = [r["id"] for r in quest_rows]
                intento_ids = [r["id"] for r in intento_rows]
                grant_ids = [r["id"] for r in grant_rows]
                bitacora_ids = [r["id"] for r in bitacora_rows]

                deleted_ids = json.dumps(
                    {
                        "mission_ids": [mission_id],
                        "deck_task_id": mission["deck_task_id"],
                        "checklist_item_ids": quest_ids,
                        "intento_ids": intento_ids,
                        "attempt_grant_ids": grant_ids,
                        "turn_bitacora_ids": bitacora_ids,
                    },
                    ensure_ascii=False,
                )

                cursor = conn.execute(
                    """INSERT INTO mission_deletions
                           (mission_id, deck_task_id, project, title, reason,
                            requested_by, quests_deleted, intentos_deleted,
                            grants_deleted, bitacora_deleted, deleted_ids)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        mission_id,
                        mission["deck_task_id"],
                        mission["project"],
                        mission["title"],
                        reason.strip(),
                        actor,
                        len(quest_ids),
                        len(intento_ids),
                        len(grant_ids),
                        len(bitacora_ids),
                        deleted_ids,
                    ),
                )
                audit_id = cursor.lastrowid

                conn.execute(
                    "DELETE FROM turn_bitacora WHERE mission_id = ?", (mission_id,)
                )
                conn.execute(
                    "DELETE FROM attempt_grants WHERE mission_id = ?", (mission_id,)
                )
                conn.execute("DELETE FROM intentos WHERE mission_id = ?", (mission_id,))
                conn.execute(
                    "DELETE FROM checklist_items WHERE mission_id = ?", (mission_id,)
                )
                conn.execute("DELETE FROM missions WHERE id = ?", (mission_id,))

                return {
                    "mission_id": mission_id,
                    "deck_task_id": mission["deck_task_id"],
                    "project": mission["project"],
                    "title": mission["title"],
                    "audit_id": audit_id,
                    "quests_deleted": len(quest_ids),
                    "intentos_deleted": len(intento_ids),
                    "grants_deleted": len(grant_ids),
                    "bitacora_deleted": len(bitacora_ids),
                    "deleted_ids": {
                        "checklist_item_ids": quest_ids,
                        "intento_ids": intento_ids,
                        "attempt_grant_ids": grant_ids,
                        "turn_bitacora_ids": bitacora_ids,
                    },
                }

    def list_missions(self, project: str) -> list[dict]:
        """List missions for a project."""
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute("""
                    SELECT id, deck_task_id, deck_stack_id, project, title,
                           description, status, checklist_total, checklist_done,
                           last_sync, created_at
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

    def next_checklist_item_id(self) -> int:
        """Return the next AUTOINCREMENT id without inserting a row.

        Used by ``quest_add`` to compose the marker *before* the Deck write, so
        the operation stays Deck-first and no phantom replica row can be left
        behind by a failed write. Reading ``sqlite_sequence`` (plus the current
        max id as a safety net) keeps the id unique even after deletions.
        """
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT seq FROM sqlite_sequence WHERE name = 'checklist_items'"
                ).fetchone()
                seq = int(row["seq"]) if row and row["seq"] is not None else 0
                max_row = conn.execute(
                    "SELECT COALESCE(MAX(id), 0) FROM checklist_items"
                ).fetchone()
                current_max = int(max_row[0]) if max_row else 0
                return max(seq, current_max) + 1

    def upsert_checklist_item_with_id(
        self,
        item_id: int,
        mission_id: int,
        item_index: int,
        text: str,
        done: int = 0,
    ) -> int:
        """Insert/update a checklist item at an explicit id (marker adoption).

        ``quest_add`` composes the marker id before writing Deck; the replica
        row is then created with that exact id so the marker and the replica
        handle stay identical. Any stale row occupying the same
        ``(mission_id, item_index)`` slot under a different id is dropped first
        so the UNIQUE constraint cannot turn the adoption into a rename.
        """
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    "DELETE FROM checklist_items"
                    " WHERE mission_id = ? AND item_index = ? AND id <> ?",
                    (mission_id, item_index, item_id),
                )
                conn.execute(
                    """INSERT INTO checklist_items
                           (id, mission_id, item_index, text, done)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                           mission_id = excluded.mission_id,
                           item_index = excluded.item_index,
                           text = excluded.text,
                           done = excluded.done""",
                    (item_id, mission_id, item_index, text, done),
                )
                return item_id

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

    def set_quest_done(self, quest_id: int, done: bool) -> bool:
        """Set a quest's (checklist item) done flag. Returns True if found.

        The replica flag only; Deck is updated by the caller through the
        bridge. Returns False when no checklist item matches ``quest_id``.
        """
        with self._lock:
            with self._conn() as conn:
                cursor = conn.execute(
                    "UPDATE checklist_items SET done = ? WHERE id = ?",
                    (1 if done else 0, quest_id),
                )
                return cursor.rowcount > 0

    def refresh_mission_checklist_counts(self, mission_id: int) -> bool:
        """Recompute a mission's checklist counters from its quest rows.

        Mission-scoped replica refresh used by write operations that change
        exactly one quest (``end_turn``): the quest row is already updated, so
        ``missions.checklist_total``/``checklist_done`` must follow instead of
        keeping stale counters. Returns True when the mission row exists.
        """
        with self._lock:
            with self._conn() as conn:
                cursor = conn.execute(
                    """UPDATE missions
                           SET checklist_total = (
                                   SELECT COUNT(*) FROM checklist_items
                                   WHERE mission_id = ?
                               ),
                               checklist_done = (
                                   SELECT COUNT(*) FROM checklist_items
                                   WHERE mission_id = ? AND done = 1
                               )
                         WHERE id = ?""",
                    (mission_id, mission_id, mission_id),
                )
                return cursor.rowcount > 0

    def delete_checklist_items_beyond(self, mission_id: int, keep_count: int) -> int:
        """Delete replica checklist items whose ``item_index`` >= ``keep_count``.

        Used by ``sync_task`` to reconcile the replica after quests were removed
        on Deck (the source of truth): the surviving set is ``[0, keep_count)``.
        Returns the number of rows deleted.
        """
        with self._lock:
            with self._conn() as conn:
                cursor = conn.execute(
                    "DELETE FROM checklist_items"
                    " WHERE mission_id = ? AND item_index >= ?",
                    (mission_id, keep_count),
                )
                return cursor.rowcount

    # ── quest delete / reorder (identity-preserving) ────────────────────
    #
    # Quest ids are the replica's stable handle even though Deck lines carry no
    # id. These operations therefore never go through the positional upsert
    # (``ON CONFLICT(mission_id, item_index)``): they move ``item_index`` on the
    # existing rows, so every surviving quest keeps its id and its text.

    def quest_history_counts(self, quest_id: int) -> Optional[dict]:
        """Count the traceability rows attached to one quest.

        Returns ``None`` when the quest does not exist. ``has_history`` is True
        when the quest has any intento, attempt grant or turn bitacora row.
        """
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM checklist_items WHERE id = ?", (quest_id,)
                ).fetchone()
                if row is None:
                    return None
                intentos = conn.execute(
                    "SELECT COUNT(*) FROM intentos WHERE checklist_item_id = ?",
                    (quest_id,),
                ).fetchone()[0]
                grants = conn.execute(
                    "SELECT COUNT(*) FROM attempt_grants"
                    " WHERE checklist_item_id = ?",
                    (quest_id,),
                ).fetchone()[0]
                bitacora = conn.execute(
                    "SELECT COUNT(*) FROM turn_bitacora"
                    " WHERE checklist_item_id = ?",
                    (quest_id,),
                ).fetchone()[0]
                return {
                    "quest_id": quest_id,
                    "mission_id": row["mission_id"],
                    "item_index": row["item_index"],
                    "text": row["text"],
                    "intentos": intentos,
                    "grants": grants,
                    "bitacora": bitacora,
                    "has_history": bool(intentos or grants or bitacora),
                }

    def delete_checklist_item(
        self,
        quest_id: int,
        *,
        force: bool = False,
        reason: str = "",
        requested_by: str = "hermes",
        description: Optional[str] = None,
    ) -> Optional[dict]:
        """Delete ONE quest row without renaming any survivor.

        The surviving quests keep their ids, texts and states; only their
        ``item_index`` is recomputed so the checklist stays contiguous, and the
        mission counters and (when ``description`` is supplied) the replicated
        description follow in the same transaction.

        A quest that carries traceability rows (intentos, attempt grants, turn
        bitacora) is refused unless ``force=True``; with ``force`` those rows
        are deleted in the same transaction and their ids are recorded in the
        ``quest_deletions`` audit ledger, together with the deleted quest id.

        Returns a summary dict, a ``{"refused": True, ...}`` dict when history
        exists and ``force`` is False, or ``None`` when the quest is unknown.
        Raises ``ValueError`` when ``reason`` is empty.
        """
        if not (reason or "").strip():
            raise ValueError("quest_delete requires a non-empty reason")
        actor = (requested_by or "").strip() or "unknown"

        with self._lock:
            with self._conn() as conn:
                quest = conn.execute(
                    "SELECT * FROM checklist_items WHERE id = ?", (quest_id,)
                ).fetchone()
                if quest is None:
                    return None
                mission_id = quest["mission_id"]
                mission = conn.execute(
                    "SELECT * FROM missions WHERE id = ?", (mission_id,)
                ).fetchone()

                intento_rows = conn.execute(
                    "SELECT id FROM intentos WHERE checklist_item_id = ?",
                    (quest_id,),
                ).fetchall()
                grant_rows = conn.execute(
                    "SELECT id FROM attempt_grants WHERE checklist_item_id = ?",
                    (quest_id,),
                ).fetchall()
                bitacora_rows = conn.execute(
                    "SELECT id FROM turn_bitacora WHERE checklist_item_id = ?",
                    (quest_id,),
                ).fetchall()

                intento_ids = [r["id"] for r in intento_rows]
                grant_ids = [r["id"] for r in grant_rows]
                bitacora_ids = [r["id"] for r in bitacora_rows]
                has_history = bool(intento_ids or grant_ids or bitacora_ids)

                if has_history and not force:
                    return {
                        "refused": True,
                        "quest_id": quest_id,
                        "mission_id": mission_id,
                        "text": quest["text"],
                        "item_index": quest["item_index"],
                        "intentos": len(intento_ids),
                        "grants": len(grant_ids),
                        "bitacora": len(bitacora_ids),
                        "has_history": True,
                    }

                deleted_ids = json.dumps(
                    {
                        "quest_ids": [quest_id],
                        "intento_ids": intento_ids,
                        "attempt_grant_ids": grant_ids,
                        "turn_bitacora_ids": bitacora_ids,
                    },
                    ensure_ascii=False,
                )

                cursor = conn.execute(
                    """INSERT INTO quest_deletions
                           (mission_id, deck_task_id, quest_id, project, text,
                            item_index, reason, requested_by, forced,
                            intentos_deleted, grants_deleted,
                            bitacora_deleted, deleted_ids)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        mission_id,
                        mission["deck_task_id"] if mission else None,
                        quest_id,
                        mission["project"] if mission else None,
                        quest["text"],
                        quest["item_index"],
                        reason.strip(),
                        actor,
                        1 if force else 0,
                        len(intento_ids),
                        len(grant_ids),
                        len(bitacora_ids),
                        deleted_ids,
                    ),
                )
                audit_id = cursor.lastrowid

                if force:
                    conn.execute(
                        "DELETE FROM turn_bitacora WHERE checklist_item_id = ?",
                        (quest_id,),
                    )
                    conn.execute(
                        "DELETE FROM attempt_grants WHERE checklist_item_id = ?",
                        (quest_id,),
                    )
                    conn.execute(
                        "DELETE FROM intentos WHERE checklist_item_id = ?",
                        (quest_id,),
                    )

                conn.execute(
                    "DELETE FROM checklist_items WHERE id = ?", (quest_id,)
                )

                # Two-phase shift: move every survivor far away first, then
                # settle it at its final index. A single decrementing UPDATE
                # can collide with the UNIQUE(mission_id, item_index) constraint
                # mid-statement depending on row order.
                survivors = conn.execute(
                    "SELECT id, item_index FROM checklist_items"
                    " WHERE mission_id = ? AND item_index > ?"
                    " ORDER BY item_index",
                    (mission_id, quest["item_index"]),
                ).fetchall()
                offset = 1_000_000
                for row in survivors:
                    conn.execute(
                        "UPDATE checklist_items SET item_index = item_index + ?"
                        " WHERE id = ?",
                        (offset, row["id"]),
                    )
                for row in survivors:
                    conn.execute(
                        "UPDATE checklist_items SET item_index = ? WHERE id = ?",
                        (row["item_index"] - 1, row["id"]),
                    )

                self._refresh_mission_row(conn, mission_id, description)

                return {
                    "quest_id": quest_id,
                    "mission_id": mission_id,
                    "text": quest["text"],
                    "item_index": quest["item_index"],
                    "audit_id": audit_id,
                    "forced": bool(force),
                    "intentos_deleted": len(intento_ids),
                    "grants_deleted": len(grant_ids),
                    "bitacora_deleted": len(bitacora_ids),
                    "deleted_ids": {
                        "quest_ids": [quest_id],
                        "intento_ids": intento_ids,
                        "attempt_grant_ids": grant_ids,
                        "turn_bitacora_ids": bitacora_ids,
                    },
                }

    def reorder_checklist_items(
        self,
        mission_id: int,
        ordered_ids: list[int],
        *,
        description: Optional[str] = None,
    ) -> Optional[dict]:
        """Rewrite ``item_index`` so the mission's quests follow ``ordered_ids``.

        Ids and texts are invariants: only ``item_index`` changes, and the
        update happens in one transaction. ``ordered_ids`` must be exactly the
        mission's quest set — no duplicates, nothing missing, nothing extra —
        otherwise ``ValueError`` is raised before any row is touched.

        Returns ``{"mission_id", "ordered_ids", "quests"}`` or ``None`` when the
        mission does not exist.
        """
        ids = list(ordered_ids or [])
        if len(ids) != len(set(ids)):
            raise ValueError("quest_reorder ordered_ids contains duplicate ids")

        with self._lock:
            with self._conn() as conn:
                mission = conn.execute(
                    "SELECT id FROM missions WHERE id = ?", (mission_id,)
                ).fetchone()
                if mission is None:
                    return None

                rows = conn.execute(
                    "SELECT id, item_index, text FROM checklist_items"
                    " WHERE mission_id = ? ORDER BY item_index",
                    (mission_id,),
                ).fetchall()
                current_ids = [r["id"] for r in rows]
                missing = sorted(set(current_ids) - set(ids))
                extra = sorted(set(ids) - set(current_ids))
                if missing or extra:
                    raise ValueError(
                        "quest_reorder ordered_ids must match the mission's "
                        f"quests exactly (missing={missing}, extra={extra})"
                    )

                # Two-phase move through negative temporary indexes so the
                # UNIQUE(mission_id, item_index) constraint never collides.
                for position, quest_id in enumerate(ids):
                    conn.execute(
                        "UPDATE checklist_items SET item_index = ?"
                        " WHERE id = ? AND mission_id = ?",
                        (-(position + 1), quest_id, mission_id),
                    )
                for position, quest_id in enumerate(ids):
                    conn.execute(
                        "UPDATE checklist_items SET item_index = ?"
                        " WHERE id = ? AND mission_id = ?",
                        (position, quest_id, mission_id),
                    )

                self._refresh_mission_row(conn, mission_id, description)

                quests = conn.execute(
                    "SELECT id, item_index, text, done FROM checklist_items"
                    " WHERE mission_id = ? ORDER BY item_index",
                    (mission_id,),
                ).fetchall()
                return {
                    "mission_id": mission_id,
                    "ordered_ids": ids,
                    "quests": [dict(q) for q in quests],
                }

    def migrate_quest_markers(
        self,
        mission_id: int,
        *,
        description: str,
        reason: str,
        requested_by: str = "hermes",
        quest_ids: Optional[list[int]] = None,
        migrated_ids: Optional[list[int]] = None,
    ) -> Optional[dict]:
        """Refresh the replicated description and audit a marker migration.

        The Deck write already happened (the caller owns the bridge). This
        single transaction stores the exact description that Deck acknowledged
        and appends one ``quest_identity_migrations`` audit row, so a migration
        can never be recorded without its replica refresh or vice versa.

        Returns ``{"mission_id", "audit_id", "quests_migrated",
        "migrated_ids", "quest_ids"}`` or ``None`` when the mission is unknown.
        Raises ``ValueError`` when ``reason`` is empty.
        """
        if not (reason or "").strip():
            raise ValueError("quest_migrate_identity requires a non-empty reason")
        actor = (requested_by or "").strip() or "unknown"
        ids = [int(i) for i in (quest_ids or [])]
        added = [int(i) for i in (migrated_ids or [])]

        with self._lock:
            with self._conn() as conn:
                mission = conn.execute(
                    "SELECT * FROM missions WHERE id = ?", (mission_id,)
                ).fetchone()
                if mission is None:
                    return None

                cursor = conn.execute(
                    """INSERT INTO quest_identity_migrations
                           (mission_id, deck_task_id, project, reason,
                            requested_by, quests_migrated, quest_ids,
                            migrated_ids)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        mission_id,
                        mission["deck_task_id"],
                        mission["project"],
                        reason.strip(),
                        actor,
                        len(added),
                        json.dumps(ids, ensure_ascii=False),
                        json.dumps(added, ensure_ascii=False),
                    ),
                )
                audit_id = cursor.lastrowid
                self._refresh_mission_row(conn, mission_id, description)

                return {
                    "mission_id": mission_id,
                    "audit_id": audit_id,
                    "quests_migrated": len(added),
                    "migrated_ids": added,
                    "quest_ids": ids,
                }

    def _refresh_mission_row(
        self,
        conn,
        mission_id: int,
        description: Optional[str],
    ) -> None:
        """Recompute a mission's checklist counters (and description) in place."""
        if description is None:
            conn.execute(
                """UPDATE missions
                       SET checklist_total = (
                               SELECT COUNT(*) FROM checklist_items
                               WHERE mission_id = ?
                           ),
                           checklist_done = (
                               SELECT COUNT(*) FROM checklist_items
                               WHERE mission_id = ? AND done = 1
                           )
                     WHERE id = ?""",
                (mission_id, mission_id, mission_id),
            )
            return
        conn.execute(
            """UPDATE missions
                   SET description = ?,
                       checklist_total = (
                           SELECT COUNT(*) FROM checklist_items
                           WHERE mission_id = ?
                       ),
                       checklist_done = (
                           SELECT COUNT(*) FROM checklist_items
                           WHERE mission_id = ? AND done = 1
                       )
                 WHERE id = ?""",
            (description, mission_id, mission_id, mission_id),
        )

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
            status:         Final status ('success', 'fail', 'aborted' or 'partial').
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

    # ── attempt budget & bitácora (v6) ──────────────────────────────────

    def grant_attempts(
        self,
        mission_id: int,
        checklist_item_id: int,
        amount: int,
        granted_by: str,
    ) -> Optional[int]:
        """Authorize ``amount`` extra attempts (D1): ledger row + counter bump in
        one transaction. Returns the new authorized total, or None if missing."""
        with self._lock:
            with self._conn() as conn:
                exists = conn.execute(
                    "SELECT id FROM checklist_items WHERE id = ?",
                    (checklist_item_id,),
                ).fetchone()
                if exists is None:
                    return None
                conn.execute(
                    """INSERT INTO attempt_grants
                           (mission_id, checklist_item_id, amount, granted_by)
                       VALUES (?, ?, ?, ?)""",
                    (mission_id, checklist_item_id, amount, granted_by),
                )
                conn.execute(
                    """UPDATE checklist_items
                       SET attempts_authorized = attempts_authorized + ?
                       WHERE id = ?""",
                    (amount, checklist_item_id),
                )
                row = conn.execute(
                    "SELECT attempts_authorized FROM checklist_items WHERE id = ?",
                    (checklist_item_id,),
                ).fetchone()
                return row["attempts_authorized"] if row else None

    def get_attempt_budget(self, checklist_item_id: int) -> Optional[dict]:
        """Budget for a quest, or None if it is gone. ``unbounded`` is True
        while ``attempts_authorized == 0`` (rollout guard); ``remaining`` clamps at 0."""
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    """SELECT attempts_authorized, attempts_used
                       FROM checklist_items WHERE id = ?""",
                    (checklist_item_id,),
                ).fetchone()
                if row is None:
                    return None
                authorized = row["attempts_authorized"]
                used = row["attempts_used"]
                return {
                    "checklist_item_id": checklist_item_id,
                    "authorized": authorized,
                    "used": used,
                    "remaining": max(authorized - used, 0),
                    "unbounded": authorized == 0,
                }

    def increment_attempts_used(self, checklist_item_id: int) -> bool:
        """Consume one attempt for a quest. Returns True when it existed."""
        with self._lock:
            with self._conn() as conn:
                cursor = conn.execute(
                    """UPDATE checklist_items
                       SET attempts_used = attempts_used + 1
                       WHERE id = ?""",
                    (checklist_item_id,),
                )
                return cursor.rowcount > 0

    def append_bitacora(
        self,
        intento_id: int,
        session_id: str,
        project: str,
        mission_id: int,
        checklist_item_id: int,
        final_status: str,
        gates_passed: int,
        summary: Optional[str] = None,
    ) -> int:
        """Append one immutable turn row to ``turn_bitacora`` (D8). INSERT-only:
        no UPDATE/DELETE is exposed, so prior rows are always preserved."""
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO turn_bitacora
                           (intento_id, session_id, project, mission_id,
                            checklist_item_id, final_status, gates_passed, summary)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (intento_id, session_id, project, mission_id,
                     checklist_item_id, final_status, gates_passed, summary),
                )
                return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def complete_intento_with_summary(
        self,
        intento_id: int,
        status: str,
        gates_passed: int,
        summary: str,
        evidence: Any = None,
    ) -> None:
        """Close an intento with summary, evidence and ``closed_at`` (D2/D3).
        ``evidence`` is stored as JSON when it is not already a string."""
        if evidence is not None and not isinstance(evidence, str):
            evidence = json.dumps(evidence, ensure_ascii=False, default=str)
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    """UPDATE intentos
                       SET status = ?, gates_passed = ?, summary = ?,
                           evidence = ?, closed_at = datetime('now'),
                           completed_at = datetime('now')
                       WHERE id = ?""",
                    (status, gates_passed, summary, evidence, intento_id),
                )

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

    # ── session_turns (persistent turn counting per session) ────────────────

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
