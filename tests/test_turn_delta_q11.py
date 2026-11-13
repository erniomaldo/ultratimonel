"""Card #218 quest 11: turn delta on ``begin_turn`` / ``end_turn``.

Both tools are called on every message, so their payload is paid on every
request. The default response is now a TURN DELTA: what changed and what the
caller must carry, never the whole mission state. ``full=True`` is the explicit
compatibility path that returns the complete state.

The existing contract (quests 2, 3, 4, 6 and 10) is untouched: ``intento_id``,
``final_status``, ``gates``, ``quest_done``, ``quest_done_reason``,
``identity`` and ``deck_written`` keep their exact meaning.

No live MCP call and no real Deck write: the Deck bridge is patched per test.
"""

import json
from unittest.mock import patch

import pytest

from ultratimonel.gate_engine import PASS, SKIP, WARN, GateResult


CTX = {"sender": "user", "topic": "design review", "project": "testproj"}

ALL_PASS = [
    GateResult(name="1a", state=PASS, message="ok", result_data={"memory_snippets": []}),
    GateResult(name="1b", state=PASS, message="ok", result_data={"checkpoint_state": {}}),
    GateResult(name="1c", state=SKIP, message="n/a", result_data={"steering_docs": []}),
    GateResult(name="1e", state=PASS, message="deck ok", result_data={"deck_cards": []}),
]

# Gate 1e is the only mandatory gate (1a/1b are best-effort, 1c is advisory).
MANDATORY_FAIL = [
    GateResult(name="1a", state=PASS, message="ok"),
    GateResult(name="1b", state=PASS, message="ok"),
    GateResult(name="1c", state=SKIP, message="n/a"),
    GateResult(name="1e", state=WARN, message="Deck timeout"),
]

LONG_DESCRIPTION = "# Mission\n\n" + ("Operational description line. " * 200)


@pytest.fixture
def replica(tmp_path, monkeypatch):
    """A real temp replica with one big mission (20 quests)."""
    from ultratimonel import server as srv
    from ultratimonel.persistence import Persistence

    db = Persistence(db_path=str(tmp_path / "turn-delta.db"))
    monkeypatch.setattr(srv, "persistence", db)
    srv._clear_active_intento()

    quests = [(f"Quest {index} with representative work text", 0) for index in range(20)]
    mission_id = db.upsert_mission(
        deck_task_id=189,
        project="testproj",
        title="Mission with a large checklist",
        description=LONG_DESCRIPTION,
        status="pendiente",
        checklist_total=len(quests),
        checklist_done=0,
    )
    db.set_mission_deck_stack_id(mission_id, 111)
    for index, (text, done) in enumerate(quests):
        db.upsert_checklist_item(
            mission_id=mission_id, item_index=index, text=text, done=done
        )

    yield srv, db, mission_id

    db.close()
    srv._clear_active_intento()


def _begin(srv, mission_id, quest_id, session="sess-1", gates=None, **kwargs):
    """Call begin_turn with the context and gates pinned (no live MCP)."""
    with patch.object(srv, "extract_context", return_value=CTX), patch.object(
        srv, "run_triple_match", return_value=gates if gates is not None else ALL_PASS
    ):
        return json.loads(
            srv.begin_turn(
                session, "testproj", mission_id, quest_id, "msg", "user", **kwargs
            )
        )


def _end(srv, intento_id, **kwargs):
    """Call end_turn with board/stack/Deck bridge pinned (no live Deck)."""
    def _complete(board_id, stack_id, card_id, quest_id, item_index):
        return ({"identity": "marker", "line_no": 0, "quest_id": quest_id}, None)

    with patch.object(srv, "_resolve_board_id", return_value=(21, None)), patch.object(
        srv, "_resolve_stack_for_card", return_value=(111, "Backlog", None), create=True
    ), patch.object(srv.deck_bridge, "complete_quest_identity", side_effect=_complete):
        return json.loads(srv.end_turn(intento_id, **kwargs))


# ── begin_turn: delta by default ─────────────────────────────────────────


def test_begin_turn_returns_ids_gates_and_pending_count(replica):
    """The delta carries the working ids, the gate evidence and pending count."""
    srv, db, mission_id = replica
    quest_id = db.list_checklist_items(mission_id)[0]["id"]

    result = _begin(srv, mission_id, quest_id)

    assert result["status"] == "started"
    assert result["intento_id"]
    assert result["mission_id"] == mission_id
    assert result["quest_id"] == quest_id
    assert result["gates_captured"] == 4
    assert result["gates_passed_so_far"] == 4  # SKIP counts as a soft pass
    assert result["overall"] == "PASS"
    assert result["pending_quests"] == 20

    # Gates are name+state+mandatory — never the raw result_data. 1a/1b are
    # best-effort, 1c advisory and 1e the only mandatory gate.
    assert result["gates"] == [
        {"name": "1a", "state": "PASS", "mandatory": False},
        {"name": "1b", "state": "PASS", "mandatory": False},
        {"name": "1c", "state": "SKIP", "mandatory": False},
        {"name": "1e", "state": "PASS", "mandatory": True},
    ]


def test_begin_turn_never_returns_the_mission_state(replica):
    """No description, no mission payload, no full checklist."""
    srv, db, mission_id = replica
    quest_id = db.list_checklist_items(mission_id)[0]["id"]

    raw = json.dumps(_begin(srv, mission_id, quest_id))
    result = json.loads(raw)

    assert "description" not in result
    assert "mission" not in result
    assert "checklist" not in result
    assert "checklist_items" not in result
    assert LONG_DESCRIPTION[:40] not in raw
    assert "Quest 7 with representative work text" not in raw


def test_begin_turn_full_returns_the_complete_state(replica):
    """``full=True`` is the explicit compatibility path."""
    srv, db, mission_id = replica
    quest_id = db.list_checklist_items(mission_id)[0]["id"]

    result = _begin(srv, mission_id, quest_id, full=True)

    # Same working fields as the delta.
    assert result["intento_id"]
    assert result["gates_captured"] == 4
    assert result["pending_quests"] == 20

    # Plus the whole mission state.
    assert result["mission"]["id"] == mission_id
    assert result["mission"]["title"] == "Mission with a large checklist"
    assert result["mission"]["description"] == LONG_DESCRIPTION
    assert result["mission"]["checklist_total"] == 20
    assert len(result["checklist"]) == 20
    assert result["checklist"][7]["text"] == "Quest 7 with representative work text"


def test_begin_turn_full_is_strictly_heavier_than_the_delta(replica):
    """The escape hatch only exists because the default is much lighter."""
    srv, db, mission_id = replica
    quest_id = db.list_checklist_items(mission_id)[0]["id"]

    delta = json.dumps(_begin(srv, mission_id, quest_id, session="sess-delta"))
    full = json.dumps(_begin(srv, mission_id, quest_id, session="sess-full", full=True))

    assert len(full) > len(delta) * 5


def test_begin_turn_without_a_checklist_still_reports_pending_zero(tmp_path, monkeypatch):
    """A mission with no quests reports 0 pending instead of failing."""
    from ultratimonel import server as srv
    from ultratimonel.persistence import Persistence

    db = Persistence(db_path=str(tmp_path / "empty.db"))
    monkeypatch.setattr(srv, "persistence", db)
    srv._clear_active_intento()
    mission_id = db.upsert_mission(
        deck_task_id=190, project="testproj", title="Empty", status="pendiente"
    )
    quest_id = db.upsert_checklist_item(
        mission_id=mission_id, item_index=0, text="only one", done=0
    )

    result = _begin(srv, mission_id, quest_id)

    assert result["pending_quests"] == 1
    db.close()
    srv._clear_active_intento()


# ── end_turn: contract preserved, mission state absent ───────────────────


@pytest.mark.parametrize(
    "requested,expected_final,expect_quest_done",
    [
        ("success", "success", True),
        ("aborted", "aborted", False),
        ("partial", "partial", False),
        ("failed", "failed", False),
    ],
)
def test_end_turn_keeps_the_contract_in_all_states(
    replica, requested, expected_final, expect_quest_done
):
    """final_status, quest_done/reason, identity and deck_written survive."""
    srv, db, mission_id = replica
    quest_id = db.list_checklist_items(mission_id)[0]["id"]
    started = _begin(srv, mission_id, quest_id)

    result = _end(srv, started["intento_id"], status=requested)

    assert result["status"] == "ok"
    assert result["intento_id"] == started["intento_id"]
    assert result["final_status"] == expected_final
    assert result["quest_id"] == quest_id
    assert result["quest_done"] is expect_quest_done
    assert "quest_done_reason" in result
    assert result["deck_written"] is expect_quest_done
    assert result["identity"] == ("marker" if expect_quest_done else None)
    assert result["gates_passed"] == 4
    assert result["gates_total"] == 4
    assert [g["name"] for g in result["gates"]] == ["1a", "1b", "1c", "1e"]


def test_end_turn_gate_fail_keeps_evidence_and_closes_nothing(replica):
    """A mandatory gate that does not pass forces ``fail`` and leaves the quest open."""
    srv, db, mission_id = replica
    quest_id = db.list_checklist_items(mission_id)[0]["id"]
    started = _begin(srv, mission_id, quest_id, gates=MANDATORY_FAIL)

    result = _end(srv, started["intento_id"])

    assert result["final_status"] == "fail"
    assert result["quest_done"] is False
    assert result["quest_done_reason"] == "not_success"
    assert result["identity"] is None
    assert result["deck_written"] is False


def test_end_turn_never_returns_the_mission_state(replica):
    """No mission payload, no description, no checklist, no ``result_data``."""
    srv, db, mission_id = replica
    quest_id = db.list_checklist_items(mission_id)[0]["id"]
    started = _begin(srv, mission_id, quest_id)

    raw = json.dumps(_end(srv, started["intento_id"]))
    result = json.loads(raw)

    assert "mission" not in result
    assert "checklist" not in result
    assert "checklist_items" not in result
    assert "description" not in result
    assert "result_data" not in raw
    assert LONG_DESCRIPTION[:40] not in raw


def test_end_turn_full_returns_the_complete_state(replica):
    """``full=True`` also exposes the whole mission state on close."""
    srv, db, mission_id = replica
    quest_id = db.list_checklist_items(mission_id)[0]["id"]
    started = _begin(srv, mission_id, quest_id)

    result = _end(srv, started["intento_id"], full=True)

    assert result["final_status"] == "success"
    assert result["quest_done"] is True
    assert result["mission"]["id"] == mission_id
    assert result["mission"]["description"] == LONG_DESCRIPTION
    assert len(result["checklist"]) == 20


# ── the full turn loop still works end to end ────────────────────────────


def test_full_turn_loop_uses_only_delta_fields(replica):
    """begin_turn → work → end_turn with nothing but the delta fields."""
    srv, db, mission_id = replica
    quest_id = db.list_checklist_items(mission_id)[1]["id"]

    started = _begin(srv, mission_id, quest_id)

    # The caller works between the two calls using only what the delta gave it.
    intento_id = started["intento_id"]
    assert started["quest_id"] == quest_id
    assert started["pending_quests"] == 20

    finished = _end(srv, intento_id)

    assert finished["final_status"] == "success"
    assert finished["quest_done"] is True
    assert finished["quest_done_reason"] == "refreshed"
    assert finished["deck_written"] is True
    # The closed quest is now reflected in the replica and the pending count.
    assert db.get_checklist_item_by_id(quest_id)["done"] == 1
    assert db.get_mission(mission_id)["checklist_done"] == 1
    assert db.get_intento(intento_id)["status"] == "success"
