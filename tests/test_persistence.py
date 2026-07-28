"""
Unit tests for persistence.py — CRUD, upsert, mission lifecycle.
"""

import sqlite3
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
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
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
        mid = db.upsert_mission(
            deck_task_id=10,
            project="p",
            title="New",
            status="completada",
            checklist_done=3,
            checklist_total=3,
        )
        mission = db.get_mission(mid)
        assert mission["title"] == "New"
        assert mission["status"] == "completada"
        assert mission["checklist_done"] == 3
        assert mission["checklist_total"] == 3

    def test_upsert_mission_with_checklist(self, db):
        mid = db.upsert_mission(
            deck_task_id=99,
            project="p",
            title="Task",
            checklist_total=5,
            checklist_done=2,
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
        mid = db.upsert_mission(
            deck_task_id=42, project="reentrant", title="RLock Test"
        )
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
                row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
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


class TestCreateIntento:
    """Tests for create_intento validation and foreign key enforcement."""

    def test_rejects_mission_id_zero(self, db):
        with pytest.raises(ValueError, match="mission_id must be > 0"):
            db.create_intento("sess-1", "p", mission_id=0, checklist_item_id=42)

    def test_rejects_mission_id_negative(self, db):
        with pytest.raises(ValueError, match="mission_id must be > 0"):
            db.create_intento("sess-1", "p", mission_id=-99, checklist_item_id=42)

    def test_accepts_valid_mission_id(self, db):
        mid = db.upsert_mission(deck_task_id=7, project="p", title="Test")
        cid = db.upsert_checklist_item(mid, item_index=0, text="Item 1")
        intento_id = db.create_intento(
            "sess-1", "p", mission_id=mid, checklist_item_id=cid
        )
        assert intento_id > 0

    def test_foreign_keys_enabled_on_connection(self):
        """Verify PRAGMA foreign_keys=ON fires on every new connection."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            p = Persistence(db_path=db_path)

            # First connection — should be ON
            with p._conn() as conn:
                row = conn.execute("PRAGMA foreign_keys").fetchone()
                assert row[0] == 1, "foreign_keys must be ON on first _conn()"

            # Create a second independent connection to verify it's also ON
            with p._conn() as conn:
                row = conn.execute("PRAGMA foreign_keys").fetchone()
                assert row[0] == 1, "foreign_keys must be ON on subsequent connections"
        finally:
            os.unlink(db_path)

    def test_foreign_key_violation_blocks_insert(self):
        """Verify that a FK violation (bad checklist_item_id) is rejected."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            p = Persistence(db_path=db_path)

            # Try to create an intento referencing a non-existent checklist item.
            # With foreign_keys=ON this should raise an OperationalError.
            with pytest.raises(
                sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"
            ):
                p.create_intento("sess-1", "p", mission_id=1, checklist_item_id=99999)
        finally:
            os.unlink(db_path)
