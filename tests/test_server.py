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
