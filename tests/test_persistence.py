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
    def test_upsert_mission(self, db):
        db.upsert_mission("sess-1", "ultratimonel", gates_passed=2, gates_total=3)
        mission = db.get_mission("sess-1", "ultratimonel")
        assert mission is not None
        assert mission["status"] == "active"
        assert mission["gates_passed"] == 2
        assert mission["gates_total"] == 3

    def test_upsert_updates_existing(self, db):
        db.upsert_mission("sess-1", "p", gates_passed=1)
        db.upsert_mission("sess-1", "p", gates_passed=3)
        mission = db.get_mission("sess-1", "p")
        assert mission["gates_passed"] == 3

    def test_complete_mission(self, db):
        db.upsert_mission("sess-1", "ultratimonel")
        db.complete_mission("sess-1", "ultratimonel", status="completed")
        mission = db.get_mission("sess-1", "ultratimonel")
        assert mission["status"] == "completed"
        assert mission["completed_at"] is not None

    def test_get_missing_mission(self, db):
        assert db.get_mission("nonexistent", "p") is None


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
