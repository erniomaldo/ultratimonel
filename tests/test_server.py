"""
Unit tests for server.py — tool handler output schemas, no-op behavior.
"""

import sys
import os
import json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch, MagicMock

import pytest


class TestSyncTasksMarkdownFallback:
    """Test sync_tasks markdown checklist fallback (card #141)."""

    _SAMPLE_MARKDOWN_DESC = (
        "Tarea de prueba\n\n"
        "- [ ] Paso uno sin completar\n"
        "- [x] Paso dos ya hecho\n"
        "- [ ] Paso tres pendiente\n"
    )
    _SAMPLE_STACKS_DESC = "Descripción desde stacks (no markdown)"

    def _make_stacks_response(self, cards):
        return {"stacks": [{"id": 1, "title": "To Do", "cards": cards}]}

    def _make_card(self, card_id, title, description=""):
        card = {"id": card_id, "title": title}
        if description:
            card["description"] = description
        return card

    def _make_card_detail(self, desc_with_checklist):
        return {"id": 99, "description": desc_with_checklist}

    @patch("ultratimonel.mcp_client.call_mcp_tool")
    @patch("ultratimonel.server.persistence")
    @patch("ultratimonel.context_extractor.get_project_maps")
    def test_fallback_uses_card_detail_description(
        self, mock_get_maps, mock_persistence, mock_call_mcp
    ):
        """Stacks no trae description; card_detail sí tiene markdown con checklists.

        El fallback debe reactivar el parseo de `- [ ]` / `- [x]`.
        """
        from ultratimonel.server import sync_tasks

        mock_get_maps.return_value = {"testproj": {"deck_board_id": 42}}

        card = self._make_card(106, "Card sin desc en stacks")
        card_detail = self._make_card_detail(self._SAMPLE_MARKDOWN_DESC)

        def call_mcp_side_effect(tool_name, tool_fn, params, **kwargs):
            if tool_fn == "deck_get_stacks":
                return (self._make_stacks_response([card]), None)
            elif tool_fn == "deck_get_card":
                return (card_detail, None)
            return (None, "unknown tool")

        mock_call_mcp.side_effect = call_mcp_side_effect
        mock_persistence.upsert_mission.return_value = 1
        mock_persistence.upsert_checklist_item.return_value = None

        result = json.loads(sync_tasks("testproj"))

        assert result["synced"] == 1
        # Verificar que upsert_mission se llamó con checklist_total=3, done=1
        upsert_mission_calls = mock_persistence.upsert_mission.call_args_list
        assert len(upsert_mission_calls) >= 1
        mission_kwargs = upsert_mission_calls[0][1]
        assert mission_kwargs["checklist_total"] == 3
        assert mission_kwargs["checklist_done"] == 1
        # La descripción debe ser la del card_detail (fallback)
        assert mission_kwargs["description"] == self._SAMPLE_MARKDOWN_DESC

        # Verificar que se crearon los items de checklist
        assert mock_persistence.upsert_checklist_item.call_count == 3

    @patch("ultratimonel.mcp_client.call_mcp_tool")
    @patch("ultratimonel.server.persistence")
    @patch("ultratimonel.context_extractor.get_project_maps")
    def test_stacks_description_takes_priority(
        self, mock_get_maps, mock_persistence, mock_call_mcp
    ):
        """Stacks SÍ trae description: debe usarse esa (regresión).

        El fallback NO SHALL interferir cuando stacks ya provee descripción.
        """
        from ultratimonel.server import sync_tasks

        mock_get_maps.return_value = {"testproj": {"deck_board_id": 42}}

        card = self._make_card(
            99, "Card con desc en stacks", description=self._SAMPLE_STACKS_DESC
        )
        card_detail = self._make_card_detail(self._SAMPLE_MARKDOWN_DESC)

        def call_mcp_side_effect(tool_name, tool_fn, params, **kwargs):
            if tool_fn == "deck_get_stacks":
                return (self._make_stacks_response([card]), None)
            elif tool_fn == "deck_get_card":
                return (card_detail, None)
            return (None, "unknown tool")

        mock_call_mcp.side_effect = call_mcp_side_effect
        mock_persistence.upsert_mission.return_value = 2
        mock_persistence.upsert_checklist_item.return_value = None

        result = json.loads(sync_tasks("testproj"))

        assert result["synced"] == 1
        mission_kwargs = mock_persistence.upsert_mission.call_args_list[0][1]
        # Debe usar la descripción de stacks, no la del card_detail
        assert mission_kwargs["description"] == self._SAMPLE_STACKS_DESC
        # Y no debe haber items de checklist parseados (stacks description no tiene markdown)
        assert mock_persistence.upsert_checklist_item.call_count == 0

    @patch("ultratimonel.mcp_client.call_mcp_tool")
    @patch("ultratimonel.server.persistence")
    @patch("ultratimonel.context_extractor.get_project_maps")
    def test_neither_has_description_no_crash(
        self, mock_get_maps, mock_persistence, mock_call_mcp
    ):
        """Ni stacks ni card_detail tienen description: debe completar sin crash."""
        from ultratimonel.server import sync_tasks

        mock_get_maps.return_value = {"testproj": {"deck_board_id": 42}}

        card = self._make_card(77, "Card sin descripción en ningún lado")
        card_detail = {"id": 77}  # sin campo description

        def call_mcp_side_effect(tool_name, tool_fn, params, **kwargs):
            if tool_fn == "deck_get_stacks":
                return (self._make_stacks_response([card]), None)
            elif tool_fn == "deck_get_card":
                return (card_detail, None)
            return (None, "unknown tool")

        mock_call_mcp.side_effect = call_mcp_side_effect
        mock_persistence.upsert_mission.return_value = 3

        result = json.loads(sync_tasks("testproj"))
        assert result["synced"] == 1
        assert result["total_errors"] == 0


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
        from ultratimonel.gate_engine import GateResult, PASS, SKIP, WARN

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
    """begin_turn tool behavior — executes fresh gates internally."""

    def setup_method(self):
        """Reset turn state before each test."""
        import ultratimonel.server as srv
        srv._clear_active_intento()

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_begin_turn_executes_fresh_gates(self, mock_persistence, mock_extract, mock_triple):
        """begin_turn executes 4 gates fresh and persists them."""
        from ultratimonel.server import begin_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP

        mock_extract.return_value = {
            "sender": "user", "topic": "test", "project": "voy-rojo"
        }
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS, message="ok", result_data={"memory_snippets": []}),
            GateResult(name="1b", state=PASS, message="ok", result_data={"checkpoint_state": {}}),
            GateResult(name="1c", state=SKIP, message="n/a", result_data={"steering_docs": []}),
            GateResult(name="1e", state=PASS, message="deck ok", result_data={"deck_cards": []}),
        ]
        mock_persistence.create_intento.return_value = 42

        result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10, "test msg", "user"))
        assert result["status"] == "started"
        assert result["intento_id"] == 42
        assert result["gates_captured"] == 4
        assert result["gates_passed_so_far"] == 4
        assert result["overall"] == "PASS"

        # Verify gates were executed fresh, not read from DB
        mock_triple.assert_called_once()
        mock_extract.assert_called_once_with("test msg", "sess-1", sender="user")

        # Verify each gate was persisted via upsert_gate_state
        assert mock_persistence.upsert_gate_state.call_count == 4

        # Verify intento created with correct project (from context, not param)
        create_call = mock_persistence.create_intento.call_args
        assert create_call[1]["project"] == "voy-rojo"

        mock_persistence.capture_gates_for_intento.assert_called_once()

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_begin_turn_services_unavailable_returns_warn(self, mock_persistence, mock_extract, mock_triple):
        """begin_turn with services down returns WARN gates and still creates intento."""
        from ultratimonel.server import begin_turn
        from ultratimonel.gate_engine import GateResult, WARN

        mock_extract.return_value = {
            "sender": "user", "topic": "test", "project": "voy-rojo"
        }
        # All gates fail (services unavailable)
        mock_triple.return_value = [
            GateResult(name="1a", state=WARN, message="AgentMemory timeout"),
            GateResult(name="1b", state=WARN, message="Checkpoint timeout"),
            GateResult(name="1c", state=WARN, message="Collective unavailable"),
            GateResult(name="1e", state=WARN, message="Deck error: timeout"),
        ]
        mock_persistence.create_intento.return_value = 43

        result = json.loads(begin_turn("sess-2", "voy-rojo", 1, 1, "msg", "user"))
        assert result["status"] == "started"
        assert result["intento_id"] == 43
        assert result["gates_captured"] == 4
        assert result["gates_passed_so_far"] == 0  # WARN gates don't count as passed
        assert result["overall"] == "WARN"

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_begin_turn_orphaned_auto_cleanup(self, mock_persistence, mock_extract, mock_triple):
        """begin_turn auto-cleans orphaned active turn instead of blocking."""
        from ultratimonel.server import begin_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP
        import ultratimonel.server as srv

        # Simulate orphaned active turn (different session/project)
        srv._set_active_intento(99, "sess-old", "old-proj")

        mock_extract.return_value = {
            "sender": "user", "topic": "test", "project": "voy-rojo"
        }
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS, message="ok"),
            GateResult(name="1b", state=PASS, message="ok"),
            GateResult(name="1c", state=SKIP, message="n/a"),
            GateResult(name="1e", state=PASS, message="deck ok"),
        ]
        mock_persistence.create_intento.return_value = 60
        # _resolve_requesting_intento returns None (no running intento for new session)
        mock_persistence._conn.return_value.__enter__.return_value.execute.fetchone.return_value = None

        result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10, "msg", "user"))
        assert result["status"] == "started"
        assert result["intento_id"] == 60
        # Orphaned intento 99 should have been auto-completed as fail
        mock_persistence.complete_intento.assert_called_once_with(
            intento_id=99, status="fail", gates_passed=0
        )

        srv._clear_active_intento()

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_begin_turn_after_failed_turn(self, mock_persistence, mock_extract, mock_triple):
        """begin_turn works fine after a previous turn ended as fail."""
        from ultratimonel.server import begin_turn, end_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP
        import ultratimonel.server as srv

        mock_extract.return_value = {
            "sender": "user", "topic": "test", "project": "voy-rojo"
        }
        all_pass_gates = [
            GateResult(name="1a", state=PASS, message="ok"),
            GateResult(name="1b", state=PASS, message="ok"),
            GateResult(name="1c", state=SKIP, message="n/a"),
            GateResult(name="1e", state=PASS, message="deck ok"),
        ]

        mock_triple.return_value = all_pass_gates

        # First turn: all PASS → success
        mock_persistence.create_intento.side_effect = [70, 71]  # two begin_turn calls
        # end_turn needs list_gate_states for validation + final capture
        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1c", "state": "SKIP", "mandatory": 0, "message": "n/a"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "deck ok"},
        ]

        begin_result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10, "msg", "user"))
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
        begin_result2 = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10, "msg", "user"))
        assert begin_result2["status"] == "started"
        assert begin_result2["intento_id"] == 71

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_begin_turn_returns_context_info(self, mock_persistence, mock_extract, mock_triple):
        """begin_turn response includes extracted context."""
        from ultratimonel.server import begin_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP

        mock_extract.return_value = {
            "sender": "alice", "topic": "design review", "project": "voy-rojo"
        }
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS, message="ok"),
            GateResult(name="1b", state=PASS, message="ok"),
            GateResult(name="1c", state=SKIP, message="n/a"),
            GateResult(name="1e", state=PASS, message="deck ok"),
        ]
        mock_persistence.create_intento.return_value = 44

        result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10, "review please", "alice"))
        assert result["status"] == "started"
        assert result["context"]["sender"] == "alice"
        assert result["context"]["topic"] == "design review"
        assert result["context"]["project"] == "voy-rojo"

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_begin_turn_backward_compat_no_message(self, mock_persistence, mock_extract, mock_triple):
        """begin_turn works with old signature (no message/sender)."""
        from ultratimonel.server import begin_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP

        mock_extract.return_value = {
            "sender": "user", "topic": "", "project": "voy-rojo"
        }
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS, message="ok"),
            GateResult(name="1b", state=PASS, message="ok"),
            GateResult(name="1c", state=SKIP, message="n/a"),
            GateResult(name="1e", state=PASS, message="deck ok"),
        ]
        mock_persistence.create_intento.return_value = 45

        # Old signature: only session_id, project, mission_id, checklist_item_id
        result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10))
        assert result["status"] == "started"
        assert result["intento_id"] == 45
        assert result["gates_captured"] == 4

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_begin_turn_gate_execution_failure_degraded(self, mock_persistence, mock_extract, mock_triple):
        """begin_turn degrades gracefully when run_triple_match raises."""
        from ultratimonel.server import begin_turn

        mock_extract.return_value = {
            "sender": "user", "topic": "test", "project": "voy-rojo"
        }
        mock_triple.side_effect = RuntimeError("MCP bridge down")
        mock_persistence.create_intento.return_value = 46

        result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10, "msg", "user"))
        assert result["status"] == "started"
        assert result["intento_id"] == 46
        assert result["gates_captured"] == 0
        assert result["gates_passed_so_far"] == 0

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_begin_turn_persistence_failure_degraded(self, mock_persistence, mock_extract, mock_triple):
        """begin_turn still creates intento even if gate persistence fails."""
        from ultratimonel.server import begin_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP

        mock_extract.return_value = {
            "sender": "user", "topic": "test", "project": "voy-rojo"
        }
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS, message="ok"),
            GateResult(name="1b", state=PASS, message="ok"),
            GateResult(name="1c", state=SKIP, message="n/a"),
            GateResult(name="1e", state=PASS, message="deck ok"),
        ]
        # First call (upsert_session) works, second (create_intento) works, third (upsert_gate_state) fails
        mock_persistence.upsert_gate_state.side_effect = Exception("DB locked")
        mock_persistence.create_intento.return_value = 47

        result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10, "msg", "user"))
        assert result["status"] == "started"
        assert result["intento_id"] == 47


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

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_end_turn_gate_capture_failure_completes(self, mock_persistence, mock_extract, mock_triple):
        """end_turn when list_gate_states fails in step 5 still completes."""
        from ultratimonel.server import begin_turn, end_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP

        mock_extract.return_value = {
            "sender": "user", "topic": "test", "project": "voy-rojo"
        }
        # begin_turn: all gates PASS
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS, message="ok"),
            GateResult(name="1b", state=PASS, message="ok"),
            GateResult(name="1c", state=PASS, message="ok"),
            GateResult(name="1e", state=PASS, message="ok"),
        ]
        # end_turn: list_gate_states fails for both validation and final capture
        mock_persistence.list_gate_states.side_effect = [
            Exception("DB connection lost"),  # end_turn validation fails
            Exception("DB connection lost again"),  # end_turn final capture fails
        ]
        mock_persistence.create_intento.return_value = 51
        mock_persistence.get_intento.return_value = {
            "id": 51, "session_id": "sess-1", "project": "voy-rojo"
        }

        begin_turn("sess-1", "voy-rojo", 5, 10, "msg", "user")

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
    """Full consolidated 2-call workflow — begin_turn executes gates fresh."""

    def setup_method(self):
        import ultratimonel.server as srv
        srv._clear_active_intento()

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_full_workflow_begin_then_end(self, mock_persistence, mock_extract, mock_triple):
        """begin_turn → work → end_turn = complete workflow WITHOUT assert_gates manual."""
        from ultratimonel.server import begin_turn, end_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP

        mock_extract.return_value = {
            "sender": "user", "topic": "test", "project": "voy-rojo"
        }
        # begin_turn executes 4 gates fresh (ALL PASS)
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS, message="ok"),
            GateResult(name="1b", state=PASS, message="ok"),
            GateResult(name="1c", state=SKIP, message="n/a"),
            GateResult(name="1e", state=PASS, message="deck ok"),
        ]
        # end_turn: list_gate_states for validation + final capture
        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1c", "state": "SKIP", "mandatory": 0, "message": "n/a"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "deck ok"},
        ]
        mock_persistence.create_intento.return_value = 140
        mock_persistence.get_intento.return_value = {
            "id": 140, "session_id": "sess-1", "project": "voy-rojo"
        }

        # Step 1: begin_turn — executes gates FRESH, no assert_gates needed
        begin_result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10, "msg", "user"))
        assert begin_result["status"] == "started"
        assert begin_result["intento_id"] == 140
        assert begin_result["gates_captured"] == 4
        assert begin_result["gates_passed_so_far"] == 4

        # Step 2: [work happens here — gates already executed fresh]

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

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_workflow_no_assert_gates_required(self, mock_persistence, mock_extract, mock_triple):
        """The 2-call workflow does NOT require manual assert_gates call."""
        from ultratimonel.server import begin_turn, end_turn
        from ultratimonel.gate_engine import GateResult, PASS, WARN, SKIP

        mock_extract.return_value = {
            "sender": "user", "topic": "test", "project": "voy-rojo"
        }
        # Gates: 1a=PASS, 1b=WARN (agentmemory down), 1c=SKIP, 1e=PASS
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS, message="ok"),
            GateResult(name="1b", state=WARN, message="AgentMemory timeout"),
            GateResult(name="1c", state=SKIP, message="n/a"),
            GateResult(name="1e", state=PASS, message="deck ok"),
        ]
        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "WARN", "mandatory": 1, "message": "AgentMemory timeout"},
            {"gate_name": "1c", "state": "SKIP", "mandatory": 0, "message": "n/a"},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1, "message": "deck ok"},
        ]
        mock_persistence.create_intento.return_value = 141
        mock_persistence.get_intento.return_value = {
            "id": 141, "session_id": "sess-1", "project": "voy-rojo"
        }

        # begin_turn executes gates fresh — NO assert_gates call needed
        begin_result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10, "msg", "user"))
        assert begin_result["status"] == "started"
        assert begin_result["intento_id"] == 141
        assert begin_result["gates_captured"] == 4
        assert begin_result["overall"] == "WARN"

        # end_turn completes as fail (only 3/4 PASS+SKIP)
        end_result = json.loads(end_turn(141))
        assert end_result["status"] == "ok"
        assert end_result["final_status"] == "fail"
        assert end_result["gates_passed"] == 3

        # Verify no manual assert_gates was needed (triple_match was called directly)
        mock_triple.assert_called_once()

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_workflow_with_block_gate(self, mock_persistence, mock_extract, mock_triple):
        """begin_turn with BLOCK gate -> intent created, end_turn completes as fail."""
        from ultratimonel.server import begin_turn, end_turn
        from ultratimonel.gate_engine import GateResult, PASS, BLOCK, SKIP

        mock_extract.return_value = {
            "sender": "user", "topic": "test", "project": "voy-rojo"
        }
        # 1e is BLOCK (overdue cards)
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS, message="ok"),
            GateResult(name="1b", state=PASS, message="ok"),
            GateResult(name="1c", state=SKIP, message="n/a"),
            GateResult(name="1e", state=BLOCK, message="overdue cards"),
        ]
        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1b", "state": "PASS", "mandatory": 1, "message": "ok"},
            {"gate_name": "1c", "state": "SKIP", "mandatory": 0, "message": "n/a"},
            {"gate_name": "1e", "state": "BLOCK", "mandatory": 1, "message": "overdue cards"},
        ]
        mock_persistence.create_intento.return_value = 142
        mock_persistence.get_intento.return_value = {
            "id": 142, "session_id": "sess-1", "project": "voy-rojo"
        }

        begin_result = json.loads(begin_turn("sess-1", "voy-rojo", 5, 10, "msg", "user"))
        assert begin_result["status"] == "started"
        assert begin_result["intento_id"] == 142
        assert begin_result["overall"] == "BLOCK"

        end_result = json.loads(end_turn(142))
        assert end_result["status"] == "ok"
        assert end_result["final_status"] == "fail"
        assert end_result["gates_passed"] == 3


class TestDashboardStability:
    """Tests for dashboard stability fixes (PR #11 port)."""

    @patch("ultratimonel.server.os.path.dirname")
    def test_dashboard_log_dir_uses_db_parent(self, mock_dirname):
        """_dashboard_log_dir uses parent of db_path when valid."""
        from ultratimonel.server import _dashboard_log_dir
        import ultratimonel.server as srv

        original = srv.db_path
        srv.db_path = "/home/user/.hermes/ultratimonel.db"
        mock_dirname.return_value = "/home/user/.hermes"
        try:
            result = _dashboard_log_dir()
            assert result == "/home/user/.hermes/logs"
        finally:
            srv.db_path = original

    @patch("ultratimonel.server.os.path.dirname")
    def test_dashboard_log_dir_fallback_on_root(self, mock_dirname):
        """_dashboard_log_dir falls back when dirname is '/'."""
        from ultratimonel.server import _dashboard_log_dir
        import ultratimonel.server as srv

        original = srv.db_path
        srv.db_path = "/ultratimonel.db"
        mock_dirname.return_value = "/"
        try:
            result = _dashboard_log_dir()
            assert result == os.path.expanduser("~/.hermes/logs")
        finally:
            srv.db_path = original

    @patch("ultratimonel.server.os.path.dirname")
    def test_dashboard_log_dir_fallback_on_empty(self, mock_dirname):
        """_dashboard_log_dir falls back when dirname is empty."""
        from ultratimonel.server import _dashboard_log_dir
        import ultratimonel.server as srv

        original = srv.db_path
        srv.db_path = "ultratimonel.db"
        mock_dirname.return_value = ""
        try:
            result = _dashboard_log_dir()
            assert result == os.path.expanduser("~/.hermes/logs")
        finally:
            srv.db_path = original

    def test_read_stderr_tail_from_file(self, tmp_path):
        """_read_stderr_tail reads the last 2000 chars from the log file."""
        from ultratimonel.server import _read_stderr_tail

        log_dir = str(tmp_path)
        log_file = os.path.join(log_dir, "dashboard_stderr.log")
        # Write enough content so line2 appears in the last 2000 chars
        prefix = "a" * 2100
        tail_content = "line1\nline2\nERROR: crash here"
        with open(log_file, "w") as f:
            f.write(prefix + tail_content)

        result = _read_stderr_tail(log_dir)
        assert len(result) == 2000
        assert "line2" in result
        assert "crash here" in result

    def test_read_stderr_tail_missing_file(self, tmp_path):
        """_read_stderr_tail returns empty when log file is missing."""
        from ultratimonel.server import _read_stderr_tail

        result = _read_stderr_tail(str(tmp_path))
        assert result == ""

    @patch("ultratimonel.server.subprocess.Popen")
    @patch("ultratimonel.server._dashboard_script")
    @patch("ultratimonel.server.os.makedirs")
    def test_spawn_closes_handles_on_success(self, mock_makedirs, mock_script, mock_popen):
        """Log handles are closed after Popen succeeds (CRÍTICO 2)."""
        from ultratimonel.server import server
        import ultratimonel.server as srv

        mock_script.return_value = "/fake/dashboard_server.py"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        original_port = srv._dashboard_port
        srv._dashboard_port = 3005
        try:
            result = json.loads(server("start"))
            assert result["running"] is True
            # Handles should be closed (Popen called with them, then closed)
            mock_popen.assert_called_once()
        finally:
            srv._dashboard_port = original_port

    @patch("ultratimonel.server.subprocess.Popen")
    @patch("ultratimonel.server._dashboard_script")
    @patch("ultratimonel.server.os.makedirs")
    def test_spawn_closes_handles_on_crash(self, mock_makedirs, mock_script, mock_popen):
        """Log handles are closed even when dashboard crashes immediately (CRÍTICO 2)."""
        from ultratimonel.server import server
        import ultratimonel.server as srv

        mock_script.return_value = "/fake/dashboard_server.py"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # immediate crash
        mock_popen.return_value = mock_proc

        original_port = srv._dashboard_port
        srv._dashboard_port = 3005
        try:
            result = json.loads(server("start"))
            assert "hint" in result
            assert result["error"] is not None
        finally:
            srv._dashboard_port = original_port

    @patch("ultratimonel.server.subprocess.Popen")
    @patch("ultratimonel.server._dashboard_script")
    @patch("ultratimonel.server.os.makedirs")
    def test_status_returns_stderr_tail_from_file(self, mock_makedirs, mock_script, mock_popen, tmp_path):
        """status action reads stderr_tail from log file (CRÍTICO 1)."""
        from ultratimonel.server import server
        import ultratimonel.server as srv

        mock_script.return_value = "/fake/dashboard_server.py"

        # Write some content to the fake log file
        log_dir = str(tmp_path)
        log_file = os.path.join(log_dir, "dashboard_stderr.log")
        with open(log_file, "w") as f:
            f.write("ERROR: dashboard crashed\ntraceback here\n")

        # Patch _dashboard_log_dir to return our temp dir
        with patch("ultratimonel.server._dashboard_log_dir", return_value=log_dir):
            # Simulate a crashed process
            mock_proc = MagicMock()
            mock_proc.poll.return_value = 2
            original_proc = srv._dashboard_proc
            srv._dashboard_proc = mock_proc

            try:
                result = json.loads(server("status"))
                assert "exit_code" in result
                assert result["exit_code"] == 2
                assert "stderr_tail" in result
                assert "crashed" in result["stderr_tail"]
            finally:
                srv._dashboard_proc = original_proc

    @patch("ultratimonel.server.subprocess.Popen")
    @patch("ultratimonel.server._dashboard_script")
    @patch("ultratimonel.server.os.makedirs")
    def test_start_uses_fixed_port(self, mock_makedirs, mock_script, mock_popen):
        """start action uses DASHBOARD_PORT directly, not _find_free_port."""
        from ultratimonel.server import server, DASHBOARD_PORT
        import ultratimonel.server as srv

        mock_script.return_value = "/fake/dashboard_server.py"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        original_port = srv._dashboard_port
        srv._dashboard_port = 9999  # different from DASHBOARD_PORT
        try:
            result = json.loads(server("start"))
            assert result["port"] == DASHBOARD_PORT
        finally:
            srv._dashboard_port = original_port

    @patch("ultratimonel.server.subprocess.Popen")
    @patch("ultratimonel.server._dashboard_script")
    @patch("ultratimonel.server.os.makedirs")
    def test_restart_returns_hint_on_crash(self, mock_makedirs, mock_script, mock_popen):
        """restart action returns hint on immediate crash (F-DS-06)."""
        from ultratimonel.server import server, DASHBOARD_PORT
        import ultratimonel.server as srv

        mock_script.return_value = "/fake/dashboard_server.py"
        mock_proc = MagicMock()
        mock_proc.poll.return_value = 1  # crash
        mock_popen.return_value = mock_proc

        original_port = srv._dashboard_port
        srv._dashboard_port = DASHBOARD_PORT
        try:
            result = json.loads(server("restart"))
            assert "hint" in result
            assert "error" in result
        finally:
            srv._dashboard_port = original_port


class TestMissionListLightMode:
    @patch("ultratimonel.server.persistence")
    def test_default_returns_full_payload_backward_compatible(self, mock_persistence):
        """F-TU-07: default (no param) returns full payload — dashboard unchanged."""
        from ultratimonel.server import mission_list
        full_mission = {"id": 1, "title": "A", "description": "desc", "status": "pendiente", "checklist_items": [{"id": 10}]}
        mock_persistence.list_missions.return_value = [full_mission]

        result = json.loads(mission_list("testproj"))
        assert result["missions"][0]["description"] == "desc"
        assert result["missions"][0]["checklist_items"] == [{"id": 10}]
        assert result["total"] == 1

    @patch("ultratimonel.server.persistence")
    def test_include_description_false_returns_light_mode(self, mock_persistence):
        """F-TU-03: opt-in light mode omits description and checklist_items."""
        from ultratimonel.server import mission_list
        full_mission = {"id": 1, "title": "A", "description": "desc", "status": "pendiente", "checklist_items": [{"id": 10}]}
        mock_persistence.list_missions.return_value = [full_mission]

        result = json.loads(mission_list("testproj", include_description=False))
        assert result["missions"][0] == {"id": 1, "title": "A", "status": "pendiente"}
        assert "description" not in result["missions"][0]
        assert "checklist_items" not in result["missions"][0]


class TestMissionGet:
    @patch("ultratimonel.server.persistence")
    def test_mission_get_returns_minimal_fields(self, mock_persistence):
        """F-TU-01: mission_get returns id, title, checklist_item_ids only."""
        from ultratimonel.server import mission_get
        mock_persistence.get_mission.return_value = {"id": 123, "title": "Sprint Planning", "description": "..."}
        mock_persistence.list_checklist_items.return_value = [{"id": 456}, {"id": 457}]

        result = json.loads(mission_get(123))
        assert result == {"id": 123, "title": "Sprint Planning", "checklist_item_ids": [456, 457]}
        assert "description" not in result
        assert "checklist_items" not in result

    @patch("ultratimonel.server.persistence")
    def test_mission_get_not_found(self, mock_persistence):
        """F-TU-05: returns error for non-existent mission."""
        from ultratimonel.server import mission_get
        mock_persistence.get_mission.return_value = None

        result = json.loads(mission_get(9999))
        assert "error" in result
        assert "9999" in result["error"]


class TestChecklistItemGet:
    @patch("ultratimonel.server.persistence")
    def test_checklist_item_get_returns_item(self, mock_persistence):
        """F-TU-02: returns item by ID."""
        from ultratimonel.server import checklist_item_get
        mock_persistence.get_checklist_item_by_id.return_value = {
            "id": 456, "mission_id": 123, "item_index": 1, "text": "Review backlog", "done": 0
        }

        result = json.loads(checklist_item_get(456))
        assert result["id"] == 456
        assert result["text"] == "Review backlog"

    @patch("ultratimonel.server.persistence")
    def test_checklist_item_get_not_found(self, mock_persistence):
        """F-TU-06: returns error for non-existent item."""
        from ultratimonel.server import checklist_item_get
        mock_persistence.get_checklist_item_by_id.return_value = None

        result = json.loads(checklist_item_get(9999))
        assert "error" in result


class TestBeginTurnProjectFix:
    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_explicit_project_wins_over_context(self, mock_persistence, mock_extract, mock_triple):
        """S7: explicit project param preferred over context extraction."""
        from ultratimonel.server import begin_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP

        mock_extract.return_value = {"sender": "user", "topic": "test", "project": "unknown"}
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS), GateResult(name="1b", state=PASS),
            GateResult(name="1c", state=SKIP), GateResult(name="1e", state=PASS),
        ]
        mock_persistence.create_intento.return_value = 70

        result = json.loads(begin_turn("sess-x", "voy-rojo", 5, 10, "some context extracting unknown", "user"))

        create_call = mock_persistence.create_intento.call_args
        assert create_call[1]["project"] == "voy-rojo"

        upsert_calls = mock_persistence.upsert_gate_state.call_args_list
        for call in upsert_calls:
            assert call[1]["project"] == "voy-rojo"

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_gates_execute_against_explicit_project(self, mock_persistence, mock_extract, mock_triple):
        """Regression: gates execute against explicit project, not "unknown" from extraction.

        S7 execution check: extract_context returns project="unknown" (message doesn't
        mention a known project) but begin_turn receives explicit "voy-rojo". run_triple_match
        MUST receive a context whose project is "voy-rojo", so gates 1c/1e execute against
        the correct project maps instead of SKIPping on "unknown".
        """
        from ultratimonel.server import begin_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP

        mock_extract.return_value = {"sender": "user", "topic": "test", "project": "unknown"}
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS), GateResult(name="1b", state=PASS),
            GateResult(name="1c", state=SKIP), GateResult(name="1e", state=PASS),
        ]
        mock_persistence.create_intento.return_value = 72

        begin_turn("sess-x", "voy-rojo", 5, 10, "some context extracting unknown", "user")

        assert mock_triple.call_count == 1
        context_arg = mock_triple.call_args[0][0]
        assert context_arg["project"] == "voy-rojo"

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_gates_execute_with_fallback_to_context(self, mock_persistence, mock_extract, mock_triple):
        """S9 execution check: empty project param falls back to extracted project."""
        from ultratimonel.server import begin_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP

        mock_extract.return_value = {"sender": "user", "topic": "test", "project": "ultratimonel"}
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS), GateResult(name="1b", state=PASS),
            GateResult(name="1c", state=SKIP), GateResult(name="1e", state=PASS),
        ]
        mock_persistence.create_intento.return_value = 73

        begin_turn("sess-x", "", 5, 10, "talk about ultratimonel", "user")

        assert mock_triple.call_count == 1
        context_arg = mock_triple.call_args[0][0]
        assert context_arg["project"] == "ultratimonel"

    @patch("ultratimonel.server.run_triple_match")
    @patch("ultratimonel.server.extract_context")
    @patch("ultratimonel.server.persistence")
    def test_empty_project_falls_back_to_context(self, mock_persistence, mock_extract, mock_triple):
        """S9: empty project param falls back to context extraction."""
        from ultratimonel.server import begin_turn
        from ultratimonel.gate_engine import GateResult, PASS, SKIP

        mock_extract.return_value = {"sender": "user", "topic": "test", "project": "ultratimonel"}
        mock_triple.return_value = [
            GateResult(name="1a", state=PASS), GateResult(name="1b", state=PASS),
            GateResult(name="1c", state=SKIP), GateResult(name="1e", state=PASS),
        ]
        mock_persistence.create_intento.return_value = 71

        begin_turn("sess-x", "", 5, 10, "talk about ultratimonel", "user")

        create_call = mock_persistence.create_intento.call_args
        assert create_call[1]["project"] == "ultratimonel"

    @patch("ultratimonel.server.persistence")
    def test_end_turn_validates_against_persisted_project(self, mock_persistence):
        """S8: end_turn gates validated against correct project (regression)."""
        from ultratimonel.server import begin_turn, end_turn

        mock_persistence.get_intento.return_value = {
            "id": 70, "session_id": "sess-x", "project": "voy-rojo"
        }
        mock_persistence.list_gate_states.return_value = [
            {"gate_name": "1a", "state": "PASS", "mandatory": 1},
            {"gate_name": "1b", "state": "PASS", "mandatory": 1},
            {"gate_name": "1c", "state": "SKIP", "mandatory": 0},
            {"gate_name": "1e", "state": "PASS", "mandatory": 1},
        ]
        mock_persistence.create_intento.return_value = 70

        begin_turn("sess-x", "voy-rojo", 5, 10, "msg", "user")
        result = json.loads(end_turn(70))

        assert result["final_status"] == "success"
        list_call = mock_persistence.list_gate_states.call_args
        if list_call[1]:
            assert list_call[1]["project"] == "voy-rojo"
        else:
            assert list_call[0][1] == "voy-rojo"
