"""Unit tests for compact.py — pure output serializers (WU2, D4).

The serializers must drop the verbose fields (``result_data`` — the ~91 KB
culprit — plus ``message``/``duration_ms``/descriptions) and return the exact
compact shapes from the design.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ultratimonel.compact import (
    compact_gate,
    compact_gates,
    compact_mission,
    compact_quest,
)
from ultratimonel.gate_engine import GateResult


class TestCompactGate:
    def test_returns_only_essential_fields(self):
        gate = {
            "name": "1e",
            "state": "PASS",
            "mandatory": True,
            "duration_ms": 12.5,
            "message": "ok",
            "result_data": {"cards": ["huge"] * 1000},
        }
        result = compact_gate(gate)
        assert result == {"name": "1e", "state": "PASS", "mandatory": True}

    def test_drops_result_data_and_verbose_fields(self):
        gate = {
            "name": "1a",
            "state": "WARN",
            "mandatory": False,
            "duration_ms": 2.0,
            "message": "agentmemory unavailable",
            "result_data": {"raw": "x" * 5000},
        }
        result = compact_gate(gate)
        assert "result_data" not in result
        assert "message" not in result
        assert "duration_ms" not in result
        assert set(result) == {"name", "state", "mandatory"}

    def test_accepts_gate_result_dataclass(self):
        gate = GateResult(
            name="1c",
            state="WARN",
            mandatory=False,
            duration_ms=1.0,
            message="collectives down",
            result_data={"pages": ["p1", "p2"]},
        )
        assert compact_gate(gate) == {
            "name": "1c",
            "state": "WARN",
            "mandatory": False,
        }

    def test_mandatory_defaults_true_when_absent(self):
        assert compact_gate({"name": "1b", "state": "PASS"})["mandatory"] is True


class TestCompactGates:
    def test_compacts_each_gate_in_order(self):
        gates = [
            {
                "name": "1a",
                "state": "WARN",
                "mandatory": False,
                "result_data": {"a": 1},
            },
            {
                "name": "1e",
                "state": "PASS",
                "mandatory": True,
                "result_data": {"description": "big"},
            },
        ]
        result = compact_gates(gates)
        assert result == [
            {"name": "1a", "state": "WARN", "mandatory": False},
            {"name": "1e", "state": "PASS", "mandatory": True},
        ]
        assert all("result_data" not in g for g in result)

    def test_empty_list(self):
        assert compact_gates([]) == []


class TestCompactMission:
    def test_returns_id_title_status_only(self):
        mission = {
            "id": 189,
            "deck_task_id": 42,
            "project": "voy-rojo",
            "title": "Ship the thing",
            "description": "d" * 10000,
            "status": "en_progreso",
            "checklist_total": 3,
            "checklist_items": [{"id": 1, "text": "a"}],
        }
        assert compact_mission(mission) == {
            "id": 189,
            "title": "Ship the thing",
            "status": "en_progreso",
        }

    def test_drops_description_and_checklist_items(self):
        result = compact_mission(
            {
                "id": 1,
                "title": "t",
                "status": "pendiente",
                "description": "x",
                "checklist_items": [{"id": 9}],
            }
        )
        assert set(result) == {"id", "title", "status"}


class TestCompactQuest:
    def test_returns_id_text_done(self):
        assert compact_quest(
            {"id": 7, "item_index": 0, "text": "do it", "done": 1}
        ) == {"id": 7, "text": "do it", "done": True}

    def test_done_is_normalized_to_bool(self):
        assert compact_quest({"id": 1, "text": "a", "done": 0})["done"] is False
        assert compact_quest({"id": 2, "text": "b", "done": 1})["done"] is True

    def test_drops_extra_fields(self):
        result = compact_quest(
            {"id": 3, "mission_id": 9, "item_index": 2, "text": "c", "done": 0}
        )
        assert set(result) == {"id", "text", "done"}
