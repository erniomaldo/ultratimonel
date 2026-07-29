"""
Unit tests for gate_engine.py — state transitions, aggregation, config.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ultratimonel.gate_engine import (
    GateConfig,
    GateResult,
    aggregate,
    can_complete,
    run_gate,
    DEFAULT_GATES,
    PASS,
    SKIP,
    WARN,
    BLOCK,
)

import pytest


class TestGateConfig:
    def test_default_gates_loaded(self):
        assert len(DEFAULT_GATES) == 4
        names = [g.name for g in DEFAULT_GATES]
        assert "1a" in names
        assert "1b" in names
        assert "1c" in names
        assert "1e" in names

    def test_default_gates_all_mandatory_except_1c(self):
        """Gate 1c (collectives) is optional; all others are mandatory."""
        mandatory = [g for g in DEFAULT_GATES if g.mandatory]
        optional = [g for g in DEFAULT_GATES if not g.mandatory]
        assert len(mandatory) == 3
        assert len(optional) == 1
        assert optional[0].name == "1c"

    def test_default_gates_timeout_2s(self):
        assert all(g.timeout_s == 2.0 for g in DEFAULT_GATES)


class TestGateResult:
    def test_default_state_is_block(self):
        r = GateResult(name="1a")
        assert r.state == BLOCK

    def test_repr(self):
        r = GateResult(name="1a", state=PASS, duration_ms=150)
        assert r.name == "1a"
        assert r.duration_ms == 150.0


class TestAggregation:
    def test_all_pass(self):
        results = [
            GateResult(name="1a", state=PASS),
            GateResult(name="1b", state=PASS),
            GateResult(name="1e", state=PASS),
        ]
        overall, gates = aggregate(results)
        assert overall == PASS
        assert len(gates) == 3

    def test_any_block_blocks(self):
        results = [
            GateResult(name="1a", state=PASS),
            GateResult(name="1b", state=BLOCK, message="key missing"),
            GateResult(name="1e", state=PASS),
        ]
        overall, gates = aggregate(results)
        assert overall == BLOCK
        assert gates[1]["state"] == BLOCK

    def test_warn_not_block(self):
        results = [
            GateResult(name="1a", state=PASS),
            GateResult(name="1b", state=WARN, message="slow"),
            GateResult(name="1e", state=PASS),
        ]
        overall, gates = aggregate(results)
        assert overall == WARN

    def test_skip_is_soft_pass(self):
        results = [
            GateResult(name="1a", state=PASS),
            GateResult(name="1b", state=SKIP),
            GateResult(name="1e", state=PASS),
        ]
        overall, gates = aggregate(results)
        assert overall == PASS

    def test_block_overrides_warn(self):
        results = [
            GateResult(name="1a", state=WARN),
            GateResult(name="1b", state=BLOCK),
            GateResult(name="1e", state=PASS),
        ]
        overall, gates = aggregate(results)
        assert overall == BLOCK

    def test_gate_dicts_have_required_fields(self):
        results = [
            GateResult(name="1a", state=PASS, mandatory=True, duration_ms=50.0),
        ]
        overall, gates = aggregate(results)
        entry = gates[0]
        assert "name" in entry
        assert "state" in entry
        assert "mandatory" in entry
        assert "duration_ms" in entry
        assert "message" in entry


class TestCanComplete:
    def test_can_complete_block(self):
        assert can_complete(BLOCK) is True

    def test_can_complete_warn(self):
        assert can_complete(WARN) is True

    def test_cannot_complete_pass(self):
        assert can_complete(PASS) is False

    def test_cannot_complete_skip(self):
        assert can_complete(SKIP) is False


class TestRunGate:
    def test_no_executor_returns_pass(self):
        config = GateConfig(name="test", mandatory=True)
        result = run_gate(config, {"topic": "test"}, executor=None)
        assert result.state == PASS
        assert result.name == "test"
        assert result.duration_ms >= 0

    def test_executor_called(self):
        def fake_exec(cfg, ctx):
            return GateResult(name=cfg.name, state=PASS, message="ok")

        config = GateConfig(name="1a")
        result = run_gate(config, {}, executor=fake_exec)
        assert result.state == PASS
        assert result.message == "ok"

    def test_executor_exception_falls_to_block_if_mandatory(self):
        """Mandatory gates that fail should return BLOCK (updated behavior)."""
        def broken_exec(cfg, ctx):
            raise RuntimeError("connection refused")

        config = GateConfig(name="1a")
        result = run_gate(config, {}, executor=broken_exec)
        assert result.state == BLOCK
        assert "connection refused" in result.message

    def test_duration_tracked(self):
        import time

        def slow_exec(cfg, ctx):
            time.sleep(0.01)
            return GateResult(name=cfg.name, state=PASS)

        config = GateConfig(name="slow")
        result = run_gate(config, {}, executor=slow_exec)
        assert result.duration_ms >= 5  # at least 5ms

    def test_mandatory_gate_failure_returns_block(self):
        """Mandatory gates that fail should return BLOCK, not WARN."""
        def broken_exec(cfg, ctx):
            raise RuntimeError("connection refused")

        config = GateConfig(name="1a", mandatory=True)
        result = run_gate(config, {}, executor=broken_exec)
        assert result.state == BLOCK
        assert "connection refused" in result.message
        assert result.mandatory is True

    def test_non_mandatory_gate_failure_returns_warn(self):
        """Non-mandatory gates that fail should return WARN, not SKIP."""
        def broken_exec(cfg, ctx):
            raise RuntimeError("collectives unavailable")

        config = GateConfig(name="1c", mandatory=False)
        result = run_gate(config, {}, executor=broken_exec)
        assert result.state == WARN
        assert "collectives unavailable" in result.message
        assert result.mandatory is False

    def test_aggregate_mandatory_block_prevents_pass(self):
        """When a mandatory gate fails (BLOCK), overall should be BLOCK."""
        results = [
            GateResult(name="1a", state=BLOCK, message="AgentMemory unavailable"),
            GateResult(name="1b", state=PASS, message="Checkpoint OK"),
            GateResult(name="1e", state=PASS, message="Deck OK"),
        ]
        overall, gates = aggregate(results)
        assert overall == BLOCK
        assert gates[0]["state"] == BLOCK

    def test_aggregate_non_mandatory_warn_returns_warn(self):
        """When only non-mandatory gate fails (WARN), overall should be WARN."""
        results = [
            GateResult(name="1a", state=PASS, message="AgentMemory OK"),
            GateResult(name="1b", state=PASS, message="Checkpoint OK"),
            GateResult(name="1c", state=WARN, message="Collectives unavailable"),
            GateResult(name="1e", state=PASS, message="Deck OK"),
        ]
        overall, gates = aggregate(results)
        assert overall == WARN
        assert gates[2]["state"] == WARN

    def test_aggregate_mandatory_warn_returns_warn(self):
        """When mandatory gate is WARN (failed), overall is WARN."""
        results = [
            GateResult(name="1a", state=WARN, message="AgentMemory slow"),
            GateResult(name="1b", state=PASS, message="Checkpoint OK"),
            GateResult(name="1e", state=PASS, message="Deck OK"),
        ]
        overall, gates = aggregate(results)
        assert overall == WARN

    def test_plugin_gates_bouncer_blocks_on_mandatory_block(self):
        """Plugin should block tools when mandatory gates are BLOCK."""
        from unittest.mock import MagicMock

        # Mock the missing ultratimonel_client dependency
        mock_client = MagicMock()
        sys.modules["ultratimonel.ultratimonel_client"] = mock_client

        from ultratimonel.plugin_preflight import _gates_all_pass

        gates = [
            {"name": "1a", "state": BLOCK, "mandatory": True, "message": "unavailable"},
            {"name": "1b", "state": PASS, "mandatory": True, "message": "OK"},
            {"name": "1e", "state": PASS, "mandatory": True, "message": "OK"},
        ]
        all_pass, failed = _gates_all_pass(gates)
        assert all_pass is False
        assert len(failed) == 1
        assert "1a" in failed[0]

    def test_plugin_gates_bouncer_allows_on_non_mandatory_warn(self):
        """Plugin should allow tools when only non-mandatory gates are WARN."""
        from unittest.mock import MagicMock

        # Mock the missing ultratimonel_client dependency
        mock_client = MagicMock()
        sys.modules["ultratimonel.ultratimonel_client"] = mock_client

        from ultratimonel.plugin_preflight import _gates_all_pass

        gates = [
            {"name": "1a", "state": PASS, "mandatory": True, "message": "OK"},
            {"name": "1b", "state": PASS, "mandatory": True, "message": "OK"},
            {"name": "1c", "state": WARN, "mandatory": False, "message": "unavailable"},
            {"name": "1e", "state": PASS, "mandatory": True, "message": "OK"},
        ]
        all_pass, failed = _gates_all_pass(gates)
        assert all_pass is True
        assert len(failed) == 0
