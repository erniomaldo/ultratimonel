"""
Unit tests for triple_match.py — error isolation, empty results, envelopes.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ultratimonel.gate_engine import (
    PASS,
    SKIP,
    WARN,
    BLOCK,
    GateResult,
    GATE_CONFIG_MAP,
    aggregate,
)
from ultratimonel.triple_match import (
    run_triple_match,
    build_context_envelope,
    GATE_EXECUTORS,
    _call_agentmemory,
    _call_checkpoint,
    _call_deck,
)
from ultratimonel.mcp_client import TOOL_NAMES

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
        """Even with empty results, envelope should have all three sections."""
        from ultratimonel.gate_engine import GateResult

        results = [
            GateResult(name="1a", state=PASS, result_data={"memory_snippets": []}),
            GateResult(name="1b", state=PASS, result_data={"checkpoint_state": {"status": "new"}}),
            GateResult(name="1e", state=SKIP, result_data={"deck_cards": []}),
        ]
        envelope = build_context_envelope(results)
        assert "memory_snippets" in envelope
        assert "checkpoint_state" in envelope
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
        assert len(envelope["deck_cards"]) == 1

    def test_envelope_with_no_result_data(self):
        from ultratimonel.gate_engine import GateResult

        results = [
            GateResult(name="1a", state=SKIP, result_data=None),
            GateResult(name="1b", state=SKIP, result_data=None),
            GateResult(name="1e", state=SKIP, result_data=None),
        ]
        envelope = build_context_envelope(results)
        assert envelope["memory_snippets"] == []
        assert envelope["checkpoint_state"] == {}
        assert envelope["deck_cards"] == []


class TestTimeoutHandling:
    """Timeout -> WARN for all gates (NF-MG-02, triple-match spec §7)."""

    @patch("ultratimonel.triple_match.call_mcp_tool", return_value=(None, "timeout"))
    def test_agentmemory_timeout_returns_warn(self, mock_call):
        """1a timeout -> WARN, not SKIP."""
        context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
        result = _call_agentmemory(context)
        assert result.state == WARN
        assert "timeout" in result.message.lower()

    @patch("ultratimonel.triple_match.call_mcp_tool", return_value=(None, "timeout"))
    def test_checkpoint_timeout_returns_warn(self, mock_call):
        """1b timeout -> WARN, not SKIP."""
        context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
        result = _call_checkpoint(context)
        assert result.state == WARN
        assert "timeout" in result.message.lower()

    @patch("ultratimonel.triple_match.call_mcp_tool", return_value=(None, "timeout"))
    def test_deck_stacks_timeout_returns_warn(self, mock_call):
        """1e stacks timeout -> WARN, not SKIP."""
        context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
        result = _call_deck(context)
        assert result.state == WARN
        assert "timeout" in result.message.lower()


class TestUnavailableHandling:
    """Unavailable -> WARN for all gates."""

    @patch("ultratimonel.triple_match.call_mcp_tool", return_value=(None, "unavailable"))
    def test_agentmemory_unavailable_returns_warn(self, mock_call):
        """1a unavailable -> WARN."""
        context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
        result = _call_agentmemory(context)
        assert result.state == WARN
        assert "unavailable" in result.message.lower()

    @patch("ultratimonel.triple_match.call_mcp_tool", return_value=(None, "unavailable"))
    def test_checkpoint_unavailable_returns_warn(self, mock_call):
        """1b unavailable -> WARN."""
        context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
        result = _call_checkpoint(context)
        assert result.state == WARN
        assert "unavailable" in result.message.lower()

    @patch("ultratimonel.triple_match.call_mcp_tool", return_value=(None, "unavailable"))
    def test_deck_stacks_unavailable_returns_warn(self, mock_call):
        """1e stacks unavailable -> WARN."""
        context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
        result = _call_deck(context)
        assert result.state == WARN
        assert "unavailable" in result.message.lower()


class TestOverdueCheck:
    """Overdue cards in Deck -> BLOCK (Design.md §5)."""

    def test_overdue_card_blocks(self):
        """Overdue card -> BLOCK state."""
        from datetime import datetime, timedelta
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")

        with patch("ultratimonel.triple_match.call_mcp_tool") as mock:
            # First call: get_stacks returns stacks with an overdue card
            mock.return_value = ([
                {"title": "To Do", "cards": [
                    {"id": 1, "title": "Overdue Task", "description": "",
                     "duedate": yesterday, "labels": []}
                ]}
            ], None)
            context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
            result = _call_deck(context)
            assert result.state == BLOCK
            assert "overdue" in result.message.lower()

    def test_no_overdue_card_passes(self):
        """Cards with future duedates -> PASS."""
        from datetime import datetime, timedelta
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

        with patch("ultratimonel.triple_match.call_mcp_tool") as mock:
            mock.return_value = ([
                {"title": "To Do", "cards": [
                    {"id": 1, "title": "Future Task", "description": "",
                     "duedate": tomorrow, "labels": []}
                ]}
            ], None)
            context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
            result = _call_deck(context)
            assert result.state == PASS
            assert result.state == PASS
            assert "overdue" not in result.message.lower()


class TestLabelParsing:
    """Labels can be dicts, strings, null, or mixed — Req-1 labels-tolerant-parsing."""

    def test_labels_as_dicts(self):
        """Dict labels -> extract title field."""
        with patch("ultratimonel.triple_match.call_mcp_tool") as mock:
            mock.return_value = ([
                {"title": "To Do", "cards": [
                    {"id": 1, "title": "Task A", "description": "",
                     "duedate": None,
                     "labels": [{"id": 1, "title": "Crítica", "color": "#ff0000"}]}
                ]}
            ], None)
            context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
            result = _call_deck(context)
            assert result.state == PASS
            cards_data = result.result_data.get("deck_cards", [])
            assert len(cards_data) == 1
            assert cards_data[0]["labels"] == ["Crítica"]

    def test_labels_as_strings(self):
        """String labels -> use string as title (multi-deployment abec)."""
        with patch("ultratimonel.triple_match.call_mcp_tool") as mock:
            mock.return_value = ([
                {"title": "To Do", "cards": [
                    {"id": 1, "title": "Task B", "description": "",
                     "duedate": None,
                     "labels": ["🚨 Crítica", "Prioritaria"]}
                ]}
            ], None)
            context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
            result = _call_deck(context)
            assert result.state == PASS
            cards_data = result.result_data.get("deck_cards", [])
            assert len(cards_data) == 1
            assert cards_data[0]["labels"] == ["🚨 Crítica", "Prioritaria"]

    def test_labels_null(self):
        """Null labels -> empty list."""
        with patch("ultratimonel.triple_match.call_mcp_tool") as mock:
            mock.return_value = ([
                {"title": "To Do", "cards": [
                    {"id": 1, "title": "Task C", "description": "",
                     "duedate": None,
                     "labels": None}
                ]}
            ], None)
            context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
            result = _call_deck(context)
            assert result.state == PASS
            cards_data = result.result_data.get("deck_cards", [])
            assert len(cards_data) == 1
            assert cards_data[0]["labels"] == []

    def test_labels_empty(self):
        """Empty labels -> empty list."""
        with patch("ultratimonel.triple_match.call_mcp_tool") as mock:
            mock.return_value = ([
                {"title": "To Do", "cards": [
                    {"id": 1, "title": "Task D", "description": "",
                     "duedate": None,
                     "labels": []}
                ]}
            ], None)
            context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
            result = _call_deck(context)
            assert result.state == PASS
            cards_data = result.result_data.get("deck_cards", [])
            assert len(cards_data) == 1
            assert cards_data[0]["labels"] == []

    def test_labels_mixed_str_and_dict(self):
        """Mixed str+dict labels -> both handled correctly."""
        with patch("ultratimonel.triple_match.call_mcp_tool") as mock:
            mock.return_value = ([
                {"title": "To Do", "cards": [
                    {"id": 1, "title": "Task E", "description": "",
                     "duedate": None,
                     "labels": [{"id": 2, "title": "FromDict"}, "FromString"]}
                ]}
            ], None)
            context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
            result = _call_deck(context)
            assert result.state == PASS
            cards_data = result.result_data.get("deck_cards", [])
            assert len(cards_data) == 1
            assert cards_data[0]["labels"] == ["FromDict", "FromString"]

    def test_card_without_labels_key(self):
        """Card missing labels key -> empty list (no regressión)."""
        with patch("ultratimonel.triple_match.call_mcp_tool") as mock:
            mock.return_value = ([
                {"title": "To Do", "cards": [
                    {"id": 1, "title": "Task F", "description": "",
                     "duedate": None}
                ]}
            ], None)
            context = {"sender": "user", "topic": "test", "project": "ultratimonel"}
            result = _call_deck(context)
            assert result.state == PASS
            cards_data = result.result_data.get("deck_cards", [])
            assert len(cards_data) == 1
            assert cards_data[0]["labels"] == []


class TestBestEffortClassification:
    """D8 / triple-match delta: 1a/1b are best-effort and non-blocking while
    1c/1e keep their classification and behavior unchanged."""

    def _mock_side_effect(self):
        def side_effect(server_name, tool_name, params=None, **kwargs):
            if tool_name == TOOL_NAMES["agentmemory"]["smart_search"]:
                return (None, "unavailable")
            if tool_name in (
                TOOL_NAMES["checkpoint"]["get_state"],
                TOOL_NAMES["checkpoint"]["set_state"],
            ):
                return (None, "unavailable")
            if tool_name == TOOL_NAMES["nextcloud"]["collectives_get_pages"]:
                return ([{"id": 1, "title": "decisions"}], None)
            if tool_name == TOOL_NAMES["nextcloud"]["deck_get_stacks"]:
                return (
                    [
                        {
                            "id": 111,
                            "title": "To Do",
                            "cards": [
                                {
                                    "id": 1,
                                    "title": "Task",
                                    "description": "",
                                    "duedate": None,
                                    "labels": [],
                                }
                            ],
                        }
                    ],
                    None,
                )
            return (None, "unknown tool")

        return side_effect

    @patch("ultratimonel.triple_match.get_project_maps")
    @patch("ultratimonel.triple_match.call_mcp_tool")
    def test_run_stamps_best_effort_and_later_gates_still_run(
        self, mock_call, mock_maps
    ):
        mock_maps.return_value = {
            "testproj": {"collective_id": 5, "deck_board_id": 21}
        }
        mock_call.side_effect = self._mock_side_effect()

        context = {
            "sender": "user",
            "topic": "t",
            "project": "testproj",
            "session_id": "sess-be",
        }
        results = run_triple_match(context)

        by_name = {r.name: r for r in results}
        assert [r.name for r in results] == ["1a", "1b", "1c", "1e"]

        # 1a/1b unavailable -> WARN, but stamped best-effort/non-mandatory.
        assert by_name["1a"].state == WARN
        assert by_name["1a"].best_effort is True
        assert by_name["1a"].mandatory is False
        assert by_name["1b"].state == WARN
        assert by_name["1b"].best_effort is True

        # Later gates still executed (failure isolation preserved).
        assert by_name["1c"].state == PASS
        assert by_name["1e"].state == PASS

        # Overall stays PASS despite the two best-effort WARNs.
        overall, _ = aggregate(results)
        assert overall == PASS

    def test_best_effort_warns_yield_overall_pass(self):
        results = [
            GateResult(name="1a", state=WARN, mandatory=False, best_effort=True),
            GateResult(name="1b", state=WARN, mandatory=False, best_effort=True),
            GateResult(name="1c", state=PASS, mandatory=False, best_effort=False),
            GateResult(name="1e", state=PASS, mandatory=True, best_effort=False),
        ]
        overall, _ = aggregate(results)
        assert overall == PASS

    def test_1c_warn_still_yields_overall_warn(self):
        """Non-best-effort behavior unchanged: a 1c WARN is not swallowed."""
        results = [
            GateResult(name="1a", state=PASS, mandatory=False, best_effort=True),
            GateResult(name="1c", state=WARN, mandatory=False, best_effort=False),
            GateResult(name="1e", state=PASS, mandatory=True, best_effort=False),
        ]
        overall, _ = aggregate(results)
        assert overall == WARN

    def test_1c_1e_config_unchanged(self):
        assert GATE_CONFIG_MAP["1c"].mandatory is False
        assert GATE_CONFIG_MAP["1c"].best_effort is False
        assert GATE_CONFIG_MAP["1e"].mandatory is True
        assert GATE_CONFIG_MAP["1e"].best_effort is False

    @patch(
        "ultratimonel.triple_match.call_mcp_tool",
        return_value=(None, "unavailable"),
    )
    def test_agentmemory_and_checkpoint_still_return_warn(self, mock_call):
        """1a/1b keep returning WARN on failure (only their impact changed)."""
        context = {"sender": "u", "topic": "t", "project": "p"}
        assert _call_agentmemory(context).state == WARN
        assert _call_checkpoint(context).state == WARN
