"""
Unit tests for server.py — tool handler output schemas, no-op behavior.
"""

import sys
import os
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock

import pytest


class TestCompleteGate:
    """complete_gate output schema and no-op behavior."""

    @patch("ultratimonel.server.persistence")
    def test_complete_gate_no_op_on_pass(self, mock_persistence):
        """complete_gate on already-PASS gate returns no-op with current state."""
        from ultratimonel.server import complete_gate

        mock_persistence.get_session.return_value = {"project": "testproj"}
        mock_persistence.get_gate_state.return_value = {
            "state": "PASS",
            "gate_name": "1a",
        }

        result = json.loads(complete_gate("1a", "sess-001", "already done"))
        assert result["state"] == "PASS"
        assert "no change" in result["message"].lower()
        assert "updated_at" in result

    @patch("ultratimonel.server.persistence")
    def test_complete_gate_no_op_on_skip(self, mock_persistence):
        """complete_gate on SKIP gate returns no-op with current state."""
        from ultratimonel.server import complete_gate

        mock_persistence.get_session.return_value = {"project": "testproj"}
        mock_persistence.get_gate_state.return_value = {
            "state": "SKIP",
            "gate_name": "1b",
        }

        result = json.loads(complete_gate("1b", "sess-001", "skip"))
        assert result["state"] == "SKIP"
        assert "no change" in result["message"].lower()
        assert "updated_at" in result

    @patch("ultratimonel.server.persistence")
    def test_complete_gate_transition_output(self, mock_persistence):
        """complete_gate BLOCK→PASS returns state=PASS with updated_at."""
        from ultratimonel.server import complete_gate

        mock_persistence.get_session.return_value = {"project": "testproj"}
        mock_persistence.get_gate_state.return_value = {
            "state": "BLOCK",
            "gate_name": "1a",
        }

        result = json.loads(complete_gate("1a", "sess-001", "reviewed"))
        assert result["state"] == "PASS"
        assert result["name"] == "1a"
        assert "updated_at" in result
        assert "transitioned" in result["message"].lower()

    @patch("ultratimonel.server.persistence")
    def test_complete_gate_without_session_falls_back(self, mock_persistence):
        """complete_gate without session uses 'unknown' project but does not crash."""
        from ultratimonel.server import complete_gate

        mock_persistence.get_session.return_value = None
        mock_persistence.get_gate_state.return_value = None

        result = json.loads(complete_gate("1a", "sess-none", "test"))
        # No prior state → defaults to BLOCK, can transition
        assert result["state"] == "PASS"
        assert "updated_at" in result

    @patch("ultratimonel.server.persistence")
    def test_complete_gate_unknown_gate(self, mock_persistence):
        """complete_gate with invalid gate name returns error."""
        from ultratimonel.server import complete_gate

        result = json.loads(complete_gate("99z", "sess-001", "test"))
        assert "error" in result
        assert "not found" in result["error"].lower()


class TestCheckGate:
    """check_gate output schema."""

    @patch("ultratimonel.server.persistence")
    def test_check_gate_has_updated_at(self, mock_persistence):
        """check_gate response includes updated_at."""
        from ultratimonel.server import check_gate

        mock_persistence.get_session.return_value = {"project": "testproj"}
        mock_persistence.get_gate_state.return_value = {
            "gate_name": "1a",
            "state": "PASS",
            "mandatory": 1,
            "message": "ok",
            "updated_at": "2026-06-28T12:00:00",
        }

        result = json.loads(check_gate("1a", "sess-001"))
        assert result["name"] == "1a"
        assert result["state"] == "PASS"
        assert "updated_at" in result
        assert result["updated_at"] == "2026-06-28T12:00:00"

    @patch("ultratimonel.server.persistence")
    def test_check_gate_pending(self, mock_persistence):
        """check_gate for unrun gate returns PENDING."""
        from ultratimonel.server import check_gate

        mock_persistence.get_session.return_value = {"project": "testproj"}
        mock_persistence.get_gate_state.return_value = None

        result = json.loads(check_gate("1a", "sess-001"))
        assert result["state"] == "PENDING"
        assert "updated_at" in result


class TestRecordIntento:
    """record_intento input validation and happy path."""

    @patch("ultratimonel.server.persistence")
    def test_rejects_mission_id_zero(self, mock_persistence):
        """record_intento with mission_id=0 returns error JSON."""
        from ultratimonel.server import record_intento

        result = json.loads(record_intento("sess-1", "p", 0, 42))
        assert "error" in result
        assert "mission_id must be > 0" in result["error"]
        assert result["mission_id"] == 0
        # Should NOT call persistence.create_intento
        mock_persistence.create_intento.assert_not_called()

    @patch("ultratimonel.server.persistence")
    def test_rejects_mission_id_negative(self, mock_persistence):
        """record_intento with mission_id=-1 returns error JSON."""
        from ultratimonel.server import record_intento

        result = json.loads(record_intento("sess-1", "p", -5, 42))
        assert "error" in result
        assert "mission_id must be > 0" in result["error"]
        mock_persistence.create_intento.assert_not_called()

    @patch("ultratimonel.server.persistence")
    def test_accepts_valid_mission_id(self, mock_persistence):
        """record_intento with valid mission_id calls persistence."""
        from ultratimonel.server import record_intento

        mock_persistence.create_intento.return_value = 7
        result = json.loads(record_intento("sess-1", "p", 3, 42))
        assert result["status"] == "ok"
        assert result["intento_id"] == 7
        mock_persistence.create_intento.assert_called_once_with(
            session_id="sess-1", project="p", mission_id=3, checklist_item_id=42
        )

    @patch("ultratimonel.server.persistence")
    def test_rejects_checklist_item_id_zero(self, mock_persistence):
        """record_intento with checklist_item_id=0 returns error JSON."""
        from ultratimonel.server import record_intento

        result = json.loads(record_intento("sess-1", "p", 5, 0))
        assert "error" in result
        assert "checklist_item_id must be > 0" in result["error"]
        mock_persistence.create_intento.assert_not_called()

    @patch("ultratimonel.server.persistence")
    def test_rejects_checklist_item_id_negative(self, mock_persistence):
        """record_intento with negative checklist_item_id returns error JSON."""
        from ultratimonel.server import record_intento

        result = json.loads(record_intento("sess-1", "p", 5, -3))
        assert "error" in result
        assert "checklist_item_id must be > 0" in result["error"]
        mock_persistence.create_intento.assert_not_called()


class TestCompleteIntento:
    """complete_intento turn-check enforcement (GAP-1)."""

    @patch("ultratimonel.server.persistence")
    def test_completes_intento_in_same_turn(self, mock_persistence):
        """complete_intento accepts intento from current turn."""
        from ultratimonel.server import complete_intento

        mock_persistence.get_session.return_value = {"project": "testproj"}
        mock_persistence.list_gate_states.return_value = []
        mock_persistence.get_intento.return_value = {
            "id": 42,
            "session_id": "sess-1",
            "turno": 3,
            "project": "p",
        }
        mock_persistence.get_session_turn.return_value = 3

        result = json.loads(complete_intento(42, status="success"))
        assert result["status"] == "ok"
        assert result["intento_id"] == 42
        mock_persistence.complete_intento.assert_called_once_with(
            intento_id=42, status="success", gates_passed=0
        )

    @patch("ultratimonel.server.persistence")
    def test_rejects_foreign_turn(self, mock_persistence):
        """complete_intento rejects intento from a different turn."""
        from ultratimonel.server import complete_intento

        mock_persistence.get_session.return_value = {"project": "testproj"}
        mock_persistence.list_gate_states.return_value = []
        mock_persistence.get_intento.return_value = {
            "id": 42,
            "session_id": "sess-1",
            "turno": 2,
            "project": "p",
        }
        mock_persistence.get_session_turn.return_value = 5

        result = json.loads(complete_intento(42, status="success"))
        assert result["status"] == "error"
        assert "does not belong to the current turn" in result["error"]
        mock_persistence.complete_intento.assert_not_called()

    @patch("ultratimonel.server.persistence")
    def test_rejects_nonexistent_intento(self, mock_persistence):
        """complete_intento returns error when intento_id not found."""
        from ultratimonel.server import complete_intento

        mock_persistence.get_session.return_value = {"project": "testproj"}
        mock_persistence.list_gate_states.return_value = []
        mock_persistence.get_intento.return_value = None

        result = json.loads(complete_intento(999, status="success"))
        assert result["status"] == "error"
        assert "not found" in result["error"]


class TestBeginTurn:
    """begin_turn happy path and validation."""

    @patch("ultratimonel.server.persistence")
    def test_begin_turn_returns_intento_id_and_turno(self, mock_persistence):
        """begin_turn with valid inputs creates intento and returns turno."""
        from ultratimonel.server import begin_turn

        mock_persistence.get_session_turn.return_value = 1
        mock_persistence.create_intento.return_value = 7

        result = json.loads(begin_turn("sess-1", "p", 5, 10))
        assert result["status"] == "ok"
        assert result["intento_id"] == 7
        assert result["turno"] == 1
        mock_persistence.create_intento.assert_called_once_with(
            session_id="sess-1", project="p", mission_id=5, checklist_item_id=10, turno=1
        )

    @patch("ultratimonel.server.persistence")
    def test_begin_turn_rejects_mission_id_zero(self, mock_persistence):
        """begin_turn with mission_id=0 returns error."""
        from ultratimonel.server import begin_turn

        result = json.loads(begin_turn("sess-1", "p", 0, 10))
        assert "error" in result
        assert "mission_id must be > 0" in result["error"]
        mock_persistence.create_intento.assert_not_called()


class TestEndTurn:
    """end_turn happy path and turn-scope validation."""

    @patch("ultratimonel.server.persistence")
    def test_end_turn_completes_current_turn(self, mock_persistence):
        """end_turn with matching turno completes the intento."""
        from ultratimonel.server import end_turn

        mock_persistence.get_intento.return_value = {
            "id": 7,
            "session_id": "sess-1",
            "turno": 3,
        }
        mock_persistence.get_session_turn.return_value = 3
        mock_persistence.increment_session_turn.return_value = 4

        result = json.loads(end_turn(7, status="success"))
        assert result["status"] == "ok"
        assert result["intento_id"] == 7
        assert result["turno"] == 3
        mock_persistence.complete_intento.assert_called_once_with(
            intento_id=7, status="success", gates_passed=0
        )
        mock_persistence.increment_session_turn.assert_called_once_with("sess-1")

    @patch("ultratimonel.server.persistence")
    def test_end_turn_rejects_foreign_turn(self, mock_persistence):
        """end_turn rejects intento from a different turn."""
        from ultratimonel.server import end_turn

        mock_persistence.get_intento.return_value = {
            "id": 7,
            "session_id": "sess-1",
            "turno": 2,
        }
        mock_persistence.get_session_turn.return_value = 5

        result = json.loads(end_turn(7))
        assert result["status"] == "error"
        assert "belongs to turn 2, but current turn is 5" in result["error"]
        mock_persistence.complete_intento.assert_not_called()


class TestAssertGates:
    """assert_gates output schema."""

    @patch("ultratimonel.server.persistence")
    @patch("ultratimonel.server.run_triple_match")
    def test_assert_gates_uses_status_key(self, mock_triple, mock_persistence):
        """assert_gates returns 'status' (not 'overall')."""
        from ultratimonel.server import assert_gates
        from ultratimonel.gate_engine import GateResult, PASS, WARN

        mock_triple.return_value = [
            GateResult(name="1a", state=PASS, message="ok"),
            GateResult(name="1b", state=PASS, message="ok"),
            GateResult(name="1e", state=WARN, message="no cards"),
        ]

        result = json.loads(assert_gates("test message", "sess-001"))
        assert "status" in result
        assert "overall" not in result
        assert result["status"] in ("PASS", "BLOCK", "WARN")
        assert "gates" in result
        assert "context_envelope" in result
        assert "timestamp" in result
