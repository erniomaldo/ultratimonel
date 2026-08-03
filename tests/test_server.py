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


class TestBeginTurn:
    """begin_turn tool behavior."""

    def setup_method(self):
        """Reset turn state before each test."""
        import ultratimonel.server as srv
        srv._clear_active_intento()

    @patch("ultratimonel.server.persistence")
    def test_begin_turn_creates_intento_with_gates(self, mock_persistence):
        """begin_turn creates intento and captures gate states."""
        from ultratimonel.server import begin_turn

        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1c", "state": "SKIP", "mandatory": 0, "message": "n/a"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "deck ok"},
        ]
        mock_persistence.create_intento.return_value = 42

        result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10))
        assert result["status"] == "started"
        assert result["intento_id"] == 42
        assert result["gates_captured"] == 4
        assert result["gates_passed_so_far"] == 4

        mock_persistence.create_intento.assert_called_once_with(
            session_id="sess-1", project="voy-rojo", mission_id=5, checklist_item_id=10
        )
        mock_persistence.capture_gates_for_intento.assert_called_once()

    @patch("ultratimonel.server.persistence")
    def test_begin_turn_no_prev_gates(self, mock_persistence):
        """begin_turn with no prior gates creates intento with empty array."""
        from ultratimonel.server import begin_turn

        mock_persistence.list_gate_states.return_value = []
        mock_persistence.create_intento.return_value = 43

        result = json.loads(begin_turn("sess-2", "alpha", 1, 1))
        assert result["status"] == "started"
        assert result["intento_id"] == 43
        assert result["gates_captured"] == 0
        assert result["gates_passed_so_far"] == 0

    @patch("ultratimonel.server.persistence")
    def test_begin_turn_orphaned_auto_cleanup(self, mock_persistence):
        """begin_turn auto-cleans orphaned active turn instead of blocking."""
        from ultratimonel.server import begin_turn
        import ultratimonel.server as srv

        # Simulate orphaned active turn (different session/project)
        srv._set_active_intento(99, "sess-old", "old-proj")

        mock_persistence.list_gate_states.return_value = []
        mock_persistence.create_intento.return_value = 60
        # _resolve_requesting_intento returns None (no running intento for new session)
        mock_persistence._conn.return_value.__enter__.return_value.execute.fetchone.return_value = None

        result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10))
        assert result["status"] == "started"
        assert result["intento_id"] == 60
        # Orphaned intento 99 should have been auto-completed as fail
        mock_persistence.complete_intento.assert_called_once_with(
            intento_id=99, status="fail", gates_passed=0
        )

        srv._clear_active_intento()

    @patch("ultratimonel.server.persistence")
    def test_begin_turn_after_failed_turn(self, mock_persistence):
        """begin_turn works fine after a previous turn ended as fail."""
        from ultratimonel.server import begin_turn, end_turn
        import ultratimonel.server as srv

        # First turn: all PASS → success
        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1c", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
        ]
        mock_persistence.create_intento.side_effect = [70, 71]  # two begin_turn calls

        # First begin + end (success)
        begin_result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10))
        assert begin_result["status"] == "started"
        assert begin_result["intento_id"] == 70

        mock_persistence.get_intento.return_value = {
            "id": 70, "session_id": "sess-1", "project": "voy-rojo"
        }
        end_result = json.loads(end_turn(70))
        assert end_result["final_status"] == "success"

        # Second begin — should work fine (turno was cleaned)
        srv._clear_active_intento()  # ensure clean state
        mock_persistence.get_intento.return_value = {
            "id": 71, "session_id": "sess-1", "project": "voy-rojo"
        }
        begin_result2 = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10))
        assert begin_result2["status"] == "started"
        assert begin_result2["intento_id"] == 71


class TestEndTurn:
    """end_turn tool behavior."""

    def setup_method(self):
        """Reset turn state before each test."""
        import ultratimonel.server as srv
        srv._clear_active_intento()

    @patch("ultratimonel.server.persistence")
    def test_end_turn_success_4_4(self, mock_persistence):
        """end_turn with all gates PASS completes intento successfully."""
        from ultratimonel.server import begin_turn, end_turn

        # Start turn
        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1c", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
        ]
        mock_persistence.create_intento.return_value = 42
        mock_persistence.get_intento.return_value = {
            "id": 42, "session_id": "sess-1", "project": "voy-rojo"
        }

        begin_turn("sess-1", "voy-rojo", 5, 10)

        # End turn — gates still PASS (classical signature: intento_id only)
        result = json.loads(end_turn(42))
        assert result["status"] == "ok"
        assert result["intento_id"] == 42
        assert result["final_status"] == "success"
        assert result["gates_passed"] == 4
        assert len(result["gates"]) == 4

        mock_persistence.complete_intento_with_gates.assert_called_once()

    @patch("ultratimonel.server.persistence")
    def test_end_turn_blocked_by_block_gate(self, mock_persistence):
        """end_turn with BLOCK gate completes as fail — never blocks permanently."""
        from ultratimonel.server import begin_turn, end_turn

        # Start turn
        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "BLOCK", "mandatory": 1, "message": "missing thing"},
            {"gate_name": "1c", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
        ]
        mock_persistence.create_intento.return_value = 44
        mock_persistence.get_intento.return_value = {
            "id": 44, "session_id": "sess-1", "project": "voy-rojo"
        }

        begin_turn("sess-1", "voy-rojo", 5, 10)

        # End turn — gate 1b is BLOCK, but end_turn NEVER blocks permanently
        result = json.loads(end_turn(44))
        assert result["status"] == "ok"
        assert result["final_status"] == "fail"
        assert result["gates_passed"] == 3  # 1a PASS + 1c PASS + 1e PASS

        mock_persistence.complete_intento_with_gates.assert_called_once()

    @patch("ultratimonel.server.persistence")
    def test_end_turn_warn_gates_completes_as_fail(self, mock_persistence):
        """end_turn with WARN gates (external services down) completes as fail + limpio."""
        from ultratimonel.server import begin_turn, end_turn

        # Gates: 1a=PASS, 1b=WARN (agentmemory down), 1c=SKIP, 1e=PASS
        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "WARN", "mandatory": 1, "message": "agentmemory unreachable"},
            {"gate_name": "1c", "state": "SKIP", "mandatory": 0, "message": "n/a"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "deck ok"},
        ]
        mock_persistence.create_intento.return_value = 50
        mock_persistence.get_intento.return_value = {
            "id": 50, "session_id": "sess-1", "project": "voy-rojo"
        }

        begin_turn("sess-1", "voy-rojo", 5, 10)

        result = json.loads(end_turn(50))
        assert result["status"] == "ok"
        assert result["final_status"] == "fail"  # only 3/4 PASS+SKIP
        assert result["gates_passed"] == 3
        assert len(result["gates"]) == 4

        # Turno debe estar limpio
        import ultratimonel.server as srv
        assert srv._get_active_intento() is None

    @patch("ultratimonel.server.persistence")
    def test_end_turn_gate_capture_failure_completes(self, mock_persistence):
        """end_turn when list_gate_states fails in step 5 still completes."""
        from ultratimonel.server import begin_turn, end_turn

        # First call (begin_turn) succeeds, second+third (end_turn capture + validation) fail
        mock_persistence.list_gate_states.side_effect = [
            [  # begin_turn capture — all PASS
                {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1c", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
            ],
            Exception("DB connection lost"),  # end_turn capture fails
            Exception("DB connection lost again"),  # end_turn validation also fails
        ]
        mock_persistence.create_intento.return_value = 51
        mock_persistence.get_intento.return_value = {
            "id": 51, "session_id": "sess-1", "project": "voy-rojo"
        }

        begin_turn("sess-1", "voy-rojo", 5, 10)

        # Should complete with empty gates, not crash
        result = json.loads(end_turn(51))
        assert result["status"] == "ok"
        assert result["final_status"] == "fail"  # 0/4 gates captured
        assert result["gates_passed"] == 0

        import ultratimonel.server as srv
        assert srv._get_active_intento() is None

    @patch("ultratimonel.server.persistence")
    def test_end_turn_no_active_turn(self, mock_persistence):
        """end_turn without active turn but intento not in DB returns error."""
        from ultratimonel.server import end_turn

        mock_persistence.get_intento.return_value = None
        result = json.loads(end_turn(999))
        assert result["status"] == "error"
        assert "not found" in result["error"].lower()

    @patch("ultratimonel.server.persistence")
    def test_end_turn_recover_running_orphan(self, mock_persistence):
        """end_turn recovers a running intento even when not _active_intento."""
        from ultratimonel.server import begin_turn, end_turn
        import ultratimonel.server as srv

        # Set up an active turno that is DIFFERENT from the one we want to close
        srv._set_active_intento(45, "sess-1", "voy-rojo")

        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "WARN", "mandatory": 1, "message": "down"},
            {"gate_name": "1c", "state": "SKIP", "mandatory": 0, "message": "n/a"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
        ]
        # intento #55 is running but NOT the active one — should be recoverable
        mock_persistence.get_intento.return_value = {
            "id": 55, "session_id": "sess-2", "project": "alpha", "status": "running"
        }

        result = json.loads(end_turn(55))
        assert result["status"] == "ok"
        assert result["intento_id"] == 55
        # Orphaned active turno (45) should have been completed as fail
        mock_persistence.complete_intento.assert_any_call(
            intento_id=45, status="fail", gates_passed=0
        )
        assert srv._get_active_intento() is None

    @patch("ultratimonel.server.persistence")
    def test_end_turn_non_running_mismatch_still_errors(self, mock_persistence):
        """end_turn with wrong intento_id that is NOT running still returns scoping error."""
        from ultratimonel.server import begin_turn, end_turn
        import ultratimonel.server as srv

        # Start turn — creates intento #45 (active)
        mock_persistence.list_gate_states.return_value = []
        mock_persistence.create_intento.return_value = 45
        mock_persistence.get_intento.return_value = {
            "id": 45, "session_id": "sess-1", "project": "voy-rojo"
        }

        begin_turn("sess-1", "voy-rojo", 5, 10)

        # End turn with a DIFFERENT intento_id that is NOT running → scoping error
        mock_persistence.get_intento.return_value = {
            "id": 999, "session_id": "sess-1", "project": "voy-rojo", "status": "success"
        }
        result = json.loads(end_turn(999))
        assert result["status"] == "error"
        assert "Turn-scoping mismatch" in result["error"]

    @patch("ultratimonel.server.persistence")
    def test_end_turn_partial_pass(self, mock_persistence):
        """end_turn with 3/4 gates PASS (one BLOCK non-mandatory) completes as fail."""
        from ultratimonel.server import begin_turn, end_turn

        # Start turn — initial state has a non-mandatory gate in WARN
        mock_persistence.list_gate_states.side_effect = [
            [  # begin_turn capture
                {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1c", "state": "WARN", "mandatory": 0, "message": "caution"},
                {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
            ],
            [  # _validate_gates_for_completion in end_turn
                {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1c", "state": "WARN", "mandatory": 0, "message": "caution"},
                {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
            ],
            [  # final capture in end_turn
                {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1c", "state": "WARN", "mandatory": 0, "message": "caution"},
                {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
            ],
        ]
        mock_persistence.create_intento.return_value = 46
        mock_persistence.get_intento.return_value = {
            "id": 46, "session_id": "sess-1", "project": "voy-rojo"
        }

        begin_turn("sess-1", "voy-rojo", 5, 10)

        # End turn — all mandatory gates are PASS (1c is non-mandatory WARN), so bouncer allows
        # But only 3/4 gates passed (1c is WARN, not PASS/SKIP)
        result = json.loads(end_turn(46))
        assert result["status"] == "ok"
        assert result["final_status"] == "fail"
        assert result["gates_passed"] == 3

    @patch("ultratimonel.server.persistence")
    def test_end_turn_clears_active_turn(self, mock_persistence):
        """end_turn clears the active turn state."""
        from ultratimonel.server import begin_turn, end_turn
        import ultratimonel.server as srv

        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1c", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
        ]
        mock_persistence.create_intento.return_value = 47
        mock_persistence.get_intento.return_value = {
            "id": 47, "session_id": "sess-1", "project": "voy-rojo"
        }

        begin_turn("sess-1", "voy-rojo", 5, 10)
        assert srv._get_active_intento() is not None

        end_turn(47)
        assert srv._get_active_intento() is None


class TestCompleteIntentoBackwardCompat:
    """complete_intento backward compatibility."""

    @patch("ultratimonel.server.persistence")
    def test_complete_intento_with_bouncer_pass(self, mock_persistence):
        """complete_intento with session_id/project validates gates."""
        from ultratimonel.server import complete_intento

        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1c", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
        ]

        result = json.loads(complete_intento(42, "success", 4, "sess-1", "p"))
        assert result["status"] == "ok"
        assert result["intento_id"] == 42
        assert result["gates_passed"] == 4

    @patch("ultratimonel.server.persistence")
    def test_complete_intento_bouncer_blocks_on_block(self, mock_persistence):
        """complete_intento blocks when gate is BLOCK."""
        from ultratimonel.server import complete_intento

        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "BLOCK", "mandatory": 1, "message": "missing"},
            {"gate_name": "1c", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
        ]

        result = json.loads(complete_intento(42, "success", 4, "sess-1", "p"))
        assert result["status"] == "blocked"
        assert "mandatory gate" in result["error"]

    @patch("ultratimonel.server.persistence")
    def test_complete_intento_without_bouncer(self, mock_persistence):
        """complete_intento without session_id/project skips bouncer."""
        from ultratimonel.server import complete_intento

        result = json.loads(complete_intento(42, "success", 4))
        assert result["status"] == "ok"
        mock_persistence.list_gate_states.assert_not_called()


class TestFluxConsolidated:
    """Full consolidated 2-call workflow."""

    def setup_method(self):
        import ultratimonel.server as srv
        srv._clear_active_intento()

    @patch("ultratimonel.server.persistence")
    def test_full_workflow_begin_then_end(self, mock_persistence):
        """begin_turn → work → end_turn = complete workflow."""
        from ultratimonel.server import begin_turn, end_turn

        # Simulate gates that pass during the turn
        # begin_turn: 1 call to list_gate_states
        # end_turn: 2 calls (validate + final capture)
        mock_persistence.list_gate_states.side_effect = [
            # 1st: begin_turn captures initial state (all PASS)
            [
                {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1c", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
            ],
            # 2nd: end_turn validation (all still PASS)
            [
                {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1c", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
            ],
            # 3rd: end_turn final capture (all still PASS)
            [
                {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1c", "state": "PASS", "mandatory": 1, "message": "ok"},
                {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "ok"},
            ],
        ]
        mock_persistence.create_intento.return_value = 140
        mock_persistence.get_intento.return_value = {
            "id": 140, "session_id": "sess-1", "project": "voy-rojo"
        }

        # Step 1: begin_turn
        begin_result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10))
        assert begin_result["status"] == "started"
        assert begin_result["intento_id"] == 140
        assert begin_result["gates_captured"] == 4

        # Step 2: [work happens here — gates already PASS]

        # Step 3: end_turn (classical signature)
        end_result = json.loads(end_turn(140))
        assert end_result["status"] == "ok"
        assert end_result["intento_id"] == 140
        assert end_result["final_status"] == "success"
        assert end_result["gates_passed"] == 4
        assert len(end_result["gates"]) == 4

        # Verify persistence calls
        mock_persistence.create_intento.assert_called_once()
        mock_persistence.capture_gates_for_intento.assert_called_once()
        mock_persistence.complete_intento_with_gates.assert_called_once()

        # Verify turno limpio despues de end_turn
        import ultratimonel.server as srv
        assert srv._get_active_intento() is None
