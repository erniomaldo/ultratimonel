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

    def test_default_gates_mandatory_and_best_effort_split(self):
        """D8: only 1e is mandatory; 1a/1b are best-effort; 1c stays optional."""
        by_name = {g.name: g for g in DEFAULT_GATES}
        assert by_name["1e"].mandatory is True
        assert by_name["1e"].best_effort is False
        for name in ("1a", "1b"):
            assert by_name[name].mandatory is False
            assert by_name[name].best_effort is True
        # 1c keeps its previous classification: optional but not best-effort.
        assert by_name["1c"].mandatory is False
        assert by_name["1c"].best_effort is False

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


class TestBestEffortAggregation:
    """D8: best-effort WARN/BLOCK never degrades the aggregate; 1c/1e unchanged."""

    def test_best_effort_warn_is_ignored(self):
        results = [
            GateResult(name="1a", state=WARN, mandatory=False, best_effort=True),
            GateResult(name="1e", state=PASS, mandatory=True),
        ]
        overall, gates = aggregate(results)
        assert overall == PASS
        # The best-effort entry is still reported for visibility.
        assert gates[0]["name"] == "1a"
        assert gates[0]["state"] == WARN

    def test_best_effort_block_is_ignored(self):
        results = [
            GateResult(name="1b", state=BLOCK, mandatory=False, best_effort=True),
            GateResult(name="1e", state=PASS, mandatory=True),
        ]
        overall, _ = aggregate(results)
        assert overall == PASS

    def test_non_best_effort_warn_still_aggregates_to_warn(self):
        """1c is optional but NOT best-effort: its WARN still yields WARN."""
        results = [
            GateResult(name="1c", state=WARN, mandatory=False, best_effort=False),
            GateResult(name="1e", state=PASS, mandatory=True),
        ]
        overall, _ = aggregate(results)
        assert overall == WARN

    def test_mandatory_block_still_blocks(self):
        results = [
            GateResult(name="1a", state=WARN, mandatory=False, best_effort=True),
            GateResult(name="1e", state=BLOCK, mandatory=True),
        ]
        overall, _ = aggregate(results)
        assert overall == BLOCK

    def test_run_gate_stamps_best_effort_from_config(self):
        config = GateConfig(name="1a", mandatory=False, best_effort=True)
        result = run_gate(config, {}, executor=None)
        assert result.best_effort is True
        assert result.mandatory is False


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

    def test_executor_exception_falls_to_warn_if_mandatory(self):
        def broken_exec(cfg, ctx):
            raise RuntimeError("connection refused")

        config = GateConfig(name="1a")
        result = run_gate(config, {}, executor=broken_exec)
        assert result.state == WARN
        assert "connection refused" in result.message

    def test_duration_tracked(self):
        import time

        def slow_exec(cfg, ctx):
            time.sleep(0.01)
            return GateResult(name=cfg.name, state=PASS)

        config = GateConfig(name="slow")
        result = run_gate(config, {}, executor=slow_exec)
        assert result.duration_ms >= 5  # at least 5ms
