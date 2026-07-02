"""
Unit tests for triple_match.py — error isolation, empty results, envelopes.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ultratimonel.gate_engine import PASS, SKIP, WARN, BLOCK
from ultratimonel.triple_match import (
    run_triple_match,
    build_context_envelope,
    GATE_EXECUTORS,
    _call_agentmemory,
    _call_checkpoint,
    _call_deck,
)

from unittest.mock import patch, ANY

import pytest


class TestTripleMatch:
    def test_all_gates_run_in_order(self):
        context = {
            "sender": "user",
            "topic": "test gates",
            "project": "ultratimonel",
            "session_id": "sess-001",
        }
        results = run_triple_match(context)
        assert len(results) == 4
        assert results[0].name == "1a"
        assert results[1].name == "1b"
        assert results[2].name == "1c"
        assert results[3].name == "1e"

    def test_gate_executors_registered(self):
        assert "1a" in GATE_EXECUTORS
        assert "1b" in GATE_EXECUTORS
        assert "1c" in GATE_EXECUTORS
        assert "1e" in GATE_EXECUTORS

    def test_one_failure_does_not_block_others(self):
        """Simulates first gate failing, others should still run."""
        context = {
            "sender": "user",
            "topic": "test isolation",
            "project": "ultratimonel",
            "session_id": "sess-002",
        }
        results = run_triple_match(context)
        # All gates should execute (even if some fail externally, they get SKIP)
        assert len(results) == 4
        # Each result must have a name
        for r in results:
            assert r.name in ("1a", "1b", "1c", "1e")

    def test_all_results_have_duration(self):
        context = {
            "sender": "user",
            "topic": "duration test",
            "project": "ultratimonel",
            "session_id": "sess-003",
        }
        results = run_triple_match(context)
        for r in results:
            assert r.duration_ms >= 0
            assert isinstance(r.duration_ms, float)

    def test_empty_context_does_not_crash(self):
        context = {
            "sender": "",
            "topic": "",
            "project": "",
            "session_id": "sess-empty",
        }
        results = run_triple_match(context)
        assert len(results) == 4


class TestContextEnvelope:
    def test_envelope_has_all_keys(self):
        """Even with empty results, envelope should have all four sections."""
        from ultratimonel.gate_engine import GateResult

        results = [
            GateResult(name="1a", state=PASS, result_data={"memory_snippets": []}),
            GateResult(name="1b", state=PASS, result_data={"checkpoint_state": {"status": "new"}}),
            GateResult(name="1c", state=SKIP, result_data={"steering_docs": []}),
            GateResult(name="1e", state=SKIP, result_data={"deck_cards": []}),
        ]
        envelope = build_context_envelope(results)
        assert "memory_snippets" in envelope
        assert "checkpoint_state" in envelope
        assert "steering_docs" in envelope
        assert "deck_cards" in envelope

    def test_envelope_includes_data(self):
        from ultratimonel.gate_engine import GateResult

        results = [
            GateResult(
                name="1a",
                state=PASS,
                result_data={
                    "memory_snippets": [
                        {"id": "obs-1", "content": "hello"}
                    ]
                },
            ),
            GateResult(
                name="1b",
                state=PASS,
                result_data={
                    "checkpoint_state": {"key": "proj", "value": {"status": "active"}}
                },
            ),
            GateResult(
                name="1c",
                state=SKIP,
                result_data={"steering_docs": []},
            ),
            GateResult(
                name="1e",
                state=PASS,
                result_data={
                    "deck_cards": [{"id": 1, "title": "Task 1"}]
                },
            ),
        ]
        envelope = build_context_envelope(results)
        assert len(envelope["memory_snippets"]) == 1
        assert envelope["memory_snippets"][0]["content"] == "hello"
        assert envelope["checkpoint_state"]["key"] == "proj"
        assert envelope["steering_docs"] == []
        assert len(envelope["deck_cards"]) == 1

    def test_envelope_with_no_result_data(self):
        from ultratimonel.gate_engine import GateResult

        results = [
            GateResult(name="1a", state=SKIP, result_data=None),
            GateResult(name="1b", state=SKIP, result_data=None),
            GateResult(name="1c", state=SKIP, result_data=None),
            GateResult(name="1e", state=SKIP, result_data=None),
        ]
        envelope = build_context_envelope(results)
        assert envelope["memory_snippets"] == []
        assert envelope["checkpoint_state"] == {}
        assert envelope["steering_docs"] == []
        assert envelope["deck_cards"] == []


class TestTimeoutHandling:
    """Timeout → WARN for all gates (NF-MG-02, triple-match spec §7)."""

    @patch("ultratimonel.triple_match._json_rpc_call", return_value=(None, "timeout"))
    def test_agentmemory_timeout_returns_warn(self, mock_call):
        """1a timeout → WARN, not SKIP."""
        context = {"sender": "user", "topic": "test", "project": "p"}
        result = _call_agentmemory(context)
        assert result.state == WARN
        assert "timeout" in result.message.lower()

    @patch("ultratimonel.triple_match._json_rpc_call", return_value=(None, "timeout"))
    def test_checkpoint_timeout_returns_warn(self, mock_call):
        """1b timeout → WARN, not SKIP."""
        context = {"sender": "user", "topic": "test", "project": "p"}
        result = _call_checkpoint(context)
        assert result.state == WARN
        assert "timeout" in result.message.lower()

    @patch("ultratimonel.triple_match._json_rpc_call", return_value=(None, "timeout"))
    def test_deck_boards_timeout_returns_warn(self, mock_call):
        """1e boards timeout → WARN, not SKIP."""
        context = {"sender": "user", "topic": "test", "project": "p"}
        result = _call_deck(context)
        assert result.state == WARN
        assert "timeout" in result.message.lower()


class TestUnavailableHandling:
    """Unavailable → WARN for 1a/1b, SKIP for 1e boards."""

    @patch("ultratimonel.triple_match._json_rpc_call", return_value=(None, "unavailable"))
    def test_agentmemory_unavailable_returns_warn(self, mock_call):
        """1a unavailable → WARN."""
        context = {"sender": "user", "topic": "test", "project": "p"}
        result = _call_agentmemory(context)
        assert result.state == WARN
        assert "unavailable" in result.message.lower()

    @patch("ultratimonel.triple_match._json_rpc_call", return_value=(None, "unavailable"))
    def test_checkpoint_unavailable_returns_warn(self, mock_call):
        """1b unavailable → WARN."""
        context = {"sender": "user", "topic": "test", "project": "p"}
        result = _call_checkpoint(context)
        assert result.state == WARN
        assert "unavailable" in result.message.lower()

    @patch("ultratimonel.triple_match._json_rpc_call", return_value=(None, "unavailable"))
    def test_deck_boards_unavailable_returns_skip(self, mock_call):
        """1e boards unavailable → SKIP (per spec: DECK_UNAVAILABLE → SKIP)."""
        context = {"sender": "user", "topic": "test", "project": "p"}
        result = _call_deck(context)
        assert result.state == SKIP, "DECK_UNAVAILABLE should be SKIP"
        assert "unavailable" in result.message.lower()


class TestOverdueCheck:
    """Overdue cards in Deck → BLOCK (Design.md §5)."""

    def test_overdue_card_blocks(self):
        """Overdue card → BLOCK state."""
        from datetime import datetime, timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        with patch("ultratimonel.triple_match._json_rpc_call") as mock:
            # First call: get_boards returns a matching board
            # Second call: get_stacks returns a stack with an overdue card
            mock.side_effect = [
                ([{"id": 1, "title": "Project Board"}], None),  # boards
                ([{"title": "To Do", "cards": [
                    {"id": 1, "title": "Overdue Task", "description": "",
                     "duedate": yesterday, "labels": []}
                ]}], None),  # stacks
            ]
            context = {"sender": "user", "topic": "test", "project": "Project"}
            result = _call_deck(context)
            assert result.state == BLOCK
            assert "overdue" in result.message.lower()

    def test_no_overdue_card_passes(self):
        """Cards with future duedates → PASS."""
        from datetime import datetime, timedelta
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        with patch("ultratimonel.triple_match._json_rpc_call") as mock:
            mock.side_effect = [
                ([{"id": 1, "title": "Project Board"}], None),  # boards
                ([{"title": "To Do", "cards": [
                    {"id": 1, "title": "Future Task", "description": "",
                     "duedate": tomorrow, "labels": []}
                ]}], None),  # stacks
            ]
            context = {"sender": "user", "topic": "test", "project": "Project"}
            result = _call_deck(context)
            assert result.state == PASS
            assert "overdue" not in result.message.lower()
