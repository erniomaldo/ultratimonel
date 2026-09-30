"""
Unit tests for persistence.py — CRUD, upsert, mission lifecycle.
"""

import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ultratimonel.persistence import Persistence, SCHEMA_VERSION

import pytest


@pytest.fixture
def db():
    """Create a fresh temp-file persistence layer for each test."""
    p = Persistence(db_path=":memory:")
    yield p
    p.close()  # cleans up temp file


class TestSchema:
    def test_schema_version(self, db):
        with db._conn() as conn:
            row = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
            assert row[0] == SCHEMA_VERSION

    def test_tables_exist(self, db):
        with db._conn() as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall()
            names = {r[0] for r in tables}
            assert "schema_version" in names
            assert "sessions" in names
            assert "gate_state" in names
            assert "gate_logs" in names
            assert "checkpoints" in names
            assert "missions" in names

    def test_fresh_missions_has_deck_stack_id(self, db):
        """Fresh-DB DDL includes the v5 deck_stack_id column (WU1, D9)."""
        with db._conn() as conn:
            cols = {
                c[1]
                for c in conn.execute("PRAGMA table_info(missions)").fetchall()
            }
            assert "deck_stack_id" in cols


class TestSessions:
    def test_upsert_session(self, db):
        db.upsert_session("sess-1", "alice", "design gates", "ultratimonel")
        session = db.get_session("sess-1")
        assert session is not None
        assert session["sender"] == "alice"
        assert session["topic"] == "design gates"
        assert session["project"] == "ultratimonel"

    def test_upsert_updates_existing(self, db):
        db.upsert_session("sess-1", "alice", "old topic", "old")
        db.upsert_session("sess-1", "bob", "new topic", "new")
        session = db.get_session("sess-1")
        assert session["sender"] == "bob"
        assert session["topic"] == "new topic"

    def test_get_missing_returns_none(self, db):
        assert db.get_session("nonexistent") is None


class TestGateState:
    def test_upsert_and_retrieve(self, db):
        db.upsert_gate_state("sess-1", "ultratimonel", "1a", "PASS")
        state = db.get_gate_state("sess-1", "ultratimonel", "1a")
        assert state is not None
        assert state["state"] == "PASS"

    def test_unique_per_session_project_gate(self, db):
        db.upsert_gate_state("sess-1", "ultratimonel", "1a", "PASS")
        db.upsert_gate_state("sess-1", "ultratimonel", "1a", "BLOCK")
        state = db.get_gate_state("sess-1", "ultratimonel", "1a")
        assert state["state"] == "BLOCK"

    def test_list_gate_states(self, db):
        db.upsert_gate_state("sess-1", "ultratimonel", "1a", "PASS")
        db.upsert_gate_state("sess-1", "ultratimonel", "1b", "BLOCK")
        db.upsert_gate_state("sess-1", "ultratimonel", "1e", "SKIP")
        states = db.list_gate_states("sess-1", "ultratimonel")
        assert len(states) == 3
        names = [s["gate_name"] for s in states]
        assert names == ["1a", "1b", "1e"]

    def test_missing_gate_returns_none(self, db):
        assert db.get_gate_state("sess-1", "ultratimonel", "99z") is None

    def test_mandatory_default(self, db):
        db.upsert_gate_state("sess-1", "p", "1a", "PASS")
        state = db.get_gate_state("sess-1", "p", "1a")
        assert state["mandatory"] == 1

    def test_result_data_roundtrip(self, db):
        data = {"memory_snippets": [{"id": "obs-1"}]}
        db.upsert_gate_state("sess-1", "p", "1a", "PASS", result_data=data)
        state = db.get_gate_state("sess-1", "p", "1a")
        assert state["result_data"] == data


class TestGateLog:
    def test_log_transition(self, db):
        db.log_transition("sess-1", "1a", "BLOCK", "PASS", "completed manually")
        with db._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM gate_logs WHERE session_id = ?", ("sess-1",)
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["from_state"] == "BLOCK"
            assert rows[0]["to_state"] == "PASS"
            assert rows[0]["reason"] == "completed manually"


class TestCheckpoints:
    def test_save_checkpoint(self, db):
        db.save_checkpoint("sess-1", "1a", '{"raw": "data"}', '{"extracted": "data"}')
        with db._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM checkpoints WHERE session_id = ?", ("sess-1",)
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["gate_name"] == "1a"


class TestMissions:
    """Tests for Deck-synced missions (v2 schema).

    Schema v2 uses deck_task_id as the natural key: upsert_mission() takes
    a Deck task id + project + title, and get_mission() looks up by
    internal mission id.
    """

    def test_upsert_mission(self, db):
        mission_id = db.upsert_mission(
            deck_task_id=42,
            project="ultratimonel",
            title="Wire up MCP",
        )
        assert mission_id > 0
        mission = db.get_mission(mission_id)
        assert mission is not None
        assert mission["deck_task_id"] == 42
        assert mission["project"] == "ultratimonel"
        assert mission["title"] == "Wire up MCP"
        assert mission["status"] == "pendiente"
        assert mission["checklist_total"] == 0
        assert mission["checklist_done"] == 0

    def test_upsert_updates_existing(self, db):
        db.upsert_mission(deck_task_id=10, project="p", title="Old", status="pendiente")
        mid = db.upsert_mission(deck_task_id=10, project="p", title="New", status="completada", checklist_done=3, checklist_total=3)
        mission = db.get_mission(mid)
        assert mission["title"] == "New"
        assert mission["status"] == "completada"
        assert mission["checklist_done"] == 3
        assert mission["checklist_total"] == 3

    def test_upsert_mission_with_checklist(self, db):
        mid = db.upsert_mission(
            deck_task_id=99, project="p", title="Task",
            checklist_total=5, checklist_done=2,
        )
        mission = db.get_mission(mid)
        assert mission["checklist_total"] == 5
        assert mission["checklist_done"] == 2

    def test_get_missing_mission(self, db):
        assert db.get_mission(99999) is None

    def test_list_missions_for_project(self, db):
        db.upsert_mission(deck_task_id=1, project="alpha", title="A")
        db.upsert_mission(deck_task_id=2, project="alpha", title="B")
        db.upsert_mission(deck_task_id=3, project="beta", title="C")
        alpha = db.list_missions("alpha")
        beta = db.list_missions("beta")
        assert len(alpha) == 2
        assert len(beta) == 1
        assert {m["title"] for m in alpha} == {"A", "B"}

    def test_rlock_prevents_deadlock_on_reentrant_call(self, db):
        """Reproduce the deadlock scenario that RLock fixes.

        list_missions() acquires self._lock, then calls list_checklist_items()
        per mission row, which also acquires self._lock. With a plain Lock()
        the inner call would block forever (same thread, same lock). With
        RLock() the reentrant acquire succeeds.
        """
        mid = db.upsert_mission(deck_task_id=42, project="reentrant", title="RLock Test")
        db.upsert_checklist_item(mid, item_index=0, text="Item 1")
        db.upsert_checklist_item(mid, item_index=1, text="Item 2")

        # This is the critical call: list_missions → with self._lock → list_checklist_items → with self._lock
        missions = db.list_missions("reentrant")

        assert len(missions) == 1
        assert missions[0]["title"] == "RLock Test"
        assert len(missions[0]["checklist_items"]) == 2
        assert missions[0]["checklist_items"][0]["text"] == "Item 1"


class TestDbFile:
    def test_creates_db_file(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            p = Persistence(db_path=db_path)
            assert os.path.exists(db_path)
            with p._conn() as conn:
                row = conn.execute(
                    "SELECT MAX(version) FROM schema_version"
                ).fetchone()
                assert row[0] == SCHEMA_VERSION
        finally:
            os.unlink(db_path)

    def test_wal_mode(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            p = Persistence(db_path=db_path)
            with p._conn() as conn:
                row = conn.execute("PRAGMA journal_mode").fetchone()
                assert row[0] == "wal"
        finally:
            os.unlink(db_path)


class TestGatesDetail:
    """Tests for gates_detail column (v3 schema)."""

    def test_schema_version_v4(self, db):
        """Verify DB initializes at the current schema version."""
        from ultratimonel.persistence import SCHEMA_VERSION
        with db._conn() as conn:
            row = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
            assert row[0] == SCHEMA_VERSION

    def test_gates_detail_column_exists(self, db):
        with db._conn() as conn:
            cols = conn.execute("PRAGMA table_info(intentos)").fetchall()
            col_names = {c[1] for c in cols}
            assert "gates_detail" in col_names

    def test_capture_gates_for_intento(self, db):
        mid = db.upsert_mission(deck_task_id=1, project="p", title="T")
        cid = db.upsert_checklist_item(mid, item_index=0, text="Item")
        iid = db.create_intento("s1", "p", mid, cid)

        gates = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "BLOCK", "mandatory": 1, "message": "fail"},
        ]
        db.capture_gates_for_intento(iid, gates)

        with db._conn() as conn:
            row = conn.execute(
                "SELECT gates_detail FROM intentos WHERE id = ?", (iid,)
            ).fetchone()
        import json
        captured = json.loads(row["gates_detail"])
        assert len(captured) == 2
        assert captured[0]["gate_name"] == "1a"
        assert captured[0]["state"] == "PASS"

    def test_complete_intento_with_gates(self, db):
        mid = db.upsert_mission(deck_task_id=2, project="p", title="T")
        cid = db.upsert_checklist_item(mid, item_index=0, text="Item")
        iid = db.create_intento("s1", "p", mid, cid)

        gates = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1c", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
        ]
        db.complete_intento_with_gates(iid, "success", 4, gates)

        intento = db.get_intento(iid)
        assert intento["status"] == "success"
        assert intento["gates_passed"] == 4
        assert intento["completed_at"] is not None

class TestChecklistItemById:
    def test_get_checklist_item_by_id(self, db):
        mid = db.upsert_mission(deck_task_id=1, project="p", title="T")
        cid = db.upsert_checklist_item(mid, item_index=0, text="Item 1")
        item = db.get_checklist_item_by_id(cid)
        assert item is not None
        assert item["id"] == cid
        assert item["text"] == "Item 1"
        assert item["mission_id"] == mid

    def test_get_checklist_item_by_id_not_found(self, db):
        assert db.get_checklist_item_by_id(99999) is None


def _build_legacy_v2_db(db_path: str) -> None:
    """Create a REAL v2 database.

    A genuine v2 DB has neither ``session_turns`` (v4) nor
    ``missions.deck_stack_id`` (v5) and its ``intentos`` table lacks
    ``gates_detail`` (v3).
    """
    import sqlite3

    raw = sqlite3.connect(db_path)
    raw.executescript(
        """
        CREATE TABLE schema_version (
            version     INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE missions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            deck_task_id    INTEGER UNIQUE,
            project         TEXT NOT NULL,
            title           TEXT NOT NULL,
            description     TEXT DEFAULT '',
            status          TEXT NOT NULL DEFAULT 'pendiente',
            checklist_total INTEGER NOT NULL DEFAULT 0,
            checklist_done  INTEGER NOT NULL DEFAULT 0,
            last_sync       TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE intentos (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id        TEXT NOT NULL,
            project           TEXT NOT NULL,
            mission_id        INTEGER NOT NULL,
            checklist_item_id INTEGER NOT NULL,
            status            TEXT NOT NULL DEFAULT 'running',
            gates_passed      INTEGER NOT NULL DEFAULT 0,
            gates_total       INTEGER NOT NULL DEFAULT 4,
            started_at        TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at      TEXT
        );
        INSERT INTO schema_version (version, description) VALUES (2, 'v2');
        INSERT INTO missions (deck_task_id, project, title, status)
        VALUES (7, 'ultratimonel', 'v2 mission', 'en_progreso');
        """
    )
    raw.commit()
    raw.close()


def _build_legacy_v3_db(db_path: str) -> None:
    """Create a REAL v3 database (gates_detail added, still no v4/v5 pieces)."""
    import sqlite3

    _build_legacy_v2_db(db_path)
    raw = sqlite3.connect(db_path)
    raw.executescript(
        """
        ALTER TABLE intentos ADD COLUMN gates_detail TEXT;
        DELETE FROM schema_version;
        INSERT INTO schema_version (version, description) VALUES (3, 'v3');
        """
    )
    raw.commit()
    raw.close()


class TestDbMigrationV2ToV5:
    def test_migration_v2_to_v5_creates_session_turns(self):
        """A REAL v2 DB migrates through v3→v4→v5 and gains session_turns."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _build_legacy_v2_db(db_path)

            p = Persistence(db_path=db_path)
            try:
                with p._conn() as conn:
                    version = conn.execute(
                        "SELECT MAX(version) FROM schema_version"
                    ).fetchone()[0]
                    assert version == SCHEMA_VERSION

                    cols = {
                        c[1]
                        for c in conn.execute(
                            "PRAGMA table_info(session_turns)"
                        ).fetchall()
                    }
                    assert {"session_id", "turn_count"} <= cols

                    mission_cols = {
                        c[1]
                        for c in conn.execute(
                            "PRAGMA table_info(missions)"
                        ).fetchall()
                    }
                    assert "deck_stack_id" in mission_cols

                # get_turn_count works (no OperationalError) and persists.
                assert p.get_turn_count("sess-v2") == 0
                assert p.set_turn_count("sess-v2", 3) is True
                assert p.get_turn_count("sess-v2") == 3

                # Pre-existing v2 row survives the migration.
                mission = p.get_mission(1)
                assert mission is not None
                assert mission["deck_task_id"] == 7
                assert mission["title"] == "v2 mission"
            finally:
                p.close()
        finally:
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(db_path + suffix):
                    os.unlink(db_path + suffix)


class TestTurnCount:
    """Tests for turn count persistence methods (v4 schema)."""

    def test_get_turn_count_missing_session(self, db):
        """get_turn_count returns 0 for non-existent session."""
        assert db.get_turn_count("nonexistent") == 0

    def test_set_and_get_turn_count(self, db):
        """set_turn_count persists and get_turn_count retrieves correctly."""
        assert db.set_turn_count("sess-1", 5) is True
        assert db.get_turn_count("sess-1") == 5

    def test_multiple_sessions_independent(self, db):
        """Each session has independent turn count."""
        db.set_turn_count("sess-a", 5)
        db.set_turn_count("sess-b", 3)
        assert db.get_turn_count("sess-a") == 5
        assert db.get_turn_count("sess-b") == 3


class TestDbMigrationV3ToV5:
    def test_migration_v3_to_v5_creates_session_turns(self):
        """A REAL v3 DB routes through v3→v4→v5 before being stamped v5."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            _build_legacy_v3_db(db_path)

            p = Persistence(db_path=db_path)
            try:
                with p._conn() as conn:
                    version = conn.execute(
                        "SELECT MAX(version) FROM schema_version"
                    ).fetchone()[0]
                    assert version == SCHEMA_VERSION

                    cols = {
                        c[1]
                        for c in conn.execute(
                            "PRAGMA table_info(session_turns)"
                        ).fetchall()
                    }
                    assert {"session_id", "turn_count"} <= cols

                assert p.get_turn_count("sess-v3") == 0
                assert p.set_turn_count("sess-v3", 1) is True
                assert p.get_turn_count("sess-v3") == 1
            finally:
                p.close()
        finally:
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(db_path + suffix):
                    os.unlink(db_path + suffix)


class TestDbMigrationV4ToV5:
    """WU1: the v4→v5 migration is additive and lossless (D9, NF-GP-05)."""

    def test_migration_v4_to_v5_adds_deck_stack_id_without_data_loss(self):
        import sqlite3

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            # Build a genuine v4 database with only the tables the migration
            # touches, populated before the upgrade.
            raw = sqlite3.connect(db_path)
            raw.executescript(
                """
                CREATE TABLE schema_version (
                    version     INTEGER PRIMARY KEY,
                    description TEXT NOT NULL,
                    applied_at  TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE TABLE missions (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    deck_task_id    INTEGER UNIQUE,
                    project         TEXT NOT NULL,
                    title           TEXT NOT NULL,
                    description     TEXT DEFAULT '',
                    status          TEXT NOT NULL DEFAULT 'pendiente',
                    checklist_total INTEGER NOT NULL DEFAULT 0,
                    checklist_done  INTEGER NOT NULL DEFAULT 0,
                    last_sync       TEXT,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                INSERT INTO schema_version (version, description)
                VALUES (4, 'v4: session_turns table for persistent turn counting');
                INSERT INTO missions (deck_task_id, project, title, status)
                VALUES (42, 'ultratimonel', 'Existing mission', 'en_progreso');
                """
            )
            raw.commit()
            raw.close()

            # Reopen: Persistence must run the v4→v5 migration.
            p = Persistence(db_path=db_path)
            try:
                with p._conn() as conn:
                    version = conn.execute(
                        "SELECT MAX(version) FROM schema_version"
                    ).fetchone()[0]
                    assert version == SCHEMA_VERSION

                    cols = {
                        c[1]
                        for c in conn.execute(
                            "PRAGMA table_info(missions)"
                        ).fetchall()
                    }
                    assert "deck_stack_id" in cols

                # The pre-existing row survives untouched; the new column is NULL.
                mission = p.get_mission(1)
                assert mission is not None
                assert mission["deck_task_id"] == 42
                assert mission["project"] == "ultratimonel"
                assert mission["title"] == "Existing mission"
                assert mission["status"] == "en_progreso"
                assert mission["deck_stack_id"] is None
            finally:
                p.close()
        finally:
            for suffix in ("", "-wal", "-shm"):
                if os.path.exists(db_path + suffix):
                    os.unlink(db_path + suffix)


class TestQuestHelpers:
    """WU1 helpers: set_quest_done + get_mission_by_deck_task."""

    def test_set_quest_done_updates_flag(self, db):
        mid = db.upsert_mission(deck_task_id=7, project="p", title="T")
        qid = db.upsert_checklist_item(mid, item_index=0, text="Q", done=0)
        assert db.set_quest_done(qid, True) is True
        assert db.get_checklist_item_by_id(qid)["done"] == 1
        assert db.set_quest_done(qid, False) is True
        assert db.get_checklist_item_by_id(qid)["done"] == 0

    def test_set_quest_done_missing_returns_false(self, db):
        assert db.set_quest_done(99999, True) is False

    def test_get_mission_by_deck_task(self, db):
        mid = db.upsert_mission(deck_task_id=55, project="p", title="T")
        mission = db.get_mission_by_deck_task(55)
        assert mission is not None
        assert mission["id"] == mid
        assert mission["deck_task_id"] == 55

    def test_get_mission_by_deck_task_missing(self, db):
        assert db.get_mission_by_deck_task(12345) is None

    def test_delete_checklist_items_beyond_keeps_prefix(self, db):
        """W3: only rows with item_index >= keep_count are removed."""
        mid = db.upsert_mission(deck_task_id=77, project="p", title="T")
        for idx in range(3):
            db.upsert_checklist_item(mid, item_index=idx, text=f"Q{idx}", done=0)

        deleted = db.delete_checklist_items_beyond(mid, 1)

        assert deleted == 2
        remaining = db.list_checklist_items(mid)
        assert [(q["item_index"], q["text"]) for q in remaining] == [(0, "Q0")]

    def test_delete_checklist_items_beyond_no_rows(self, db):
        mid = db.upsert_mission(deck_task_id=78, project="p", title="T")
        db.upsert_checklist_item(mid, item_index=0, text="Q0", done=0)
        assert db.delete_checklist_items_beyond(mid, 5) == 0
        assert len(db.list_checklist_items(mid)) == 1
