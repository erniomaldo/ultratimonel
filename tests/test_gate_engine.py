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
        assert len(DEFAULT_GATES) == 3
        names = [g.name for g in DEFAULT_GATES]
        assert "1a" in names
        assert "1b" in names
        assert "1e" in names

    def test_default_gates_all_mandatory(self):
        assert all(g.mandatory for g in DEFAULT_GATES)

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

    def test_executor_exception_falls_to_skip(self):
        def broken_exec(cfg, ctx):
            raise RuntimeError("connection refused")

        config = GateConfig(name="1a")
        result = run_gate(config, {}, executor=broken_exec)
        assert result.state == SKIP
        assert "connection refused" in result.message

    def test_duration_tracked(self):
        import time

        def slow_exec(cfg, ctx):
            time.sleep(0.01)
            return GateResult(name=cfg.name, state=PASS)

        config = GateConfig(name="slow")
        result = run_gate(config, {}, executor=slow_exec)
        assert result.duration_ms >= 5  # at least 5ms
