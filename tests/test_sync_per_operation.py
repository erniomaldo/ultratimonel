"""Quest 6 (#218): native, per-operation, fail-closed replica sync.

Every write tool that mutates a Deck card refreshes THAT mission's replica in
the same operation. When Deck accepted the write but the replica refresh fails,
the operation reports an explicit failure that says what Deck holds and that
the replica is behind — never a clean ``ok`` over a stale replica.

These tests use a real temporary SQLite replica and a simulated Deck bridge
(no live MCP call, no real card is written).
"""

import json
from unittest.mock import patch

import pytest


class FakeDeck:
    """Minimal stateful Deck: one card, answered over the MCP tool surface."""

    def __init__(self, description="- [ ] one", title="Mission", card_id=189):
        self.title = title
        self.description = description
        self.card_id = card_id
        self.calls = []

    def __call__(self, server_name, tool_name, params=None, timeout=8.0):
        self.calls.append((tool_name, dict(params or {})))
        if tool_name == "deck_get_card":
            return (
                {
                    "id": self.card_id,
                    "title": self.title,
                    "description": self.description,
                },
                None,
            )
        if tool_name == "deck_update_card":
            self.title = params["title"]
            self.description = params["description"]
            return ({"id": self.card_id}, None)
        if tool_name == "deck_get_stacks":
            return (
                [
                    {
                        "id": 111,
                        "title": "Backlog",
                        "cards": [{"id": self.card_id}],
                    }
                ],
                None,
            )
        return (None, "unavailable")

    def tool_names(self):
        return [name for name, _ in self.calls]


def _make_replica(tmp_path, monkeypatch, description="- [ ] one", quests=(("one", 0),)):
    from ultratimonel import server as srv
    from ultratimonel.persistence import Persistence

    db = Persistence(db_path=str(tmp_path / "sync-per-op.db"))
    monkeypatch.setattr(srv, "persistence", db)
    mission_id = db.upsert_mission(
        deck_task_id=189,
        project="testproj",
        title="Mission",
        description=description,
        status="pendiente",
        checklist_total=len(quests),
        checklist_done=sum(done for _, done in quests),
    )
    db.set_mission_deck_stack_id(mission_id, 111)
    for index, (text, done) in enumerate(quests):
        db.upsert_checklist_item(
            mission_id=mission_id, item_index=index, text=text, done=done
        )
    return srv, db, mission_id


@pytest.fixture
def project_maps():
    with patch("ultratimonel.context_extractor.get_project_maps") as mock_maps:
        mock_maps.return_value = {"testproj": {"deck_board_id": 21}}
        yield mock_maps


def test_total_bridge_failure_is_distinguishable_from_a_stale_replica(
    tmp_path, monkeypatch, project_maps
):
    """No Deck write at all: deck_written=false, no replica_refresh_failed code."""
    srv, db, mission_id = _make_replica(tmp_path, monkeypatch, "- [ ] one")
    monkeypatch.setattr(
        "ultratimonel.mcp_client.call_mcp_tool",
        lambda *args, **kwargs: (None, "unavailable"),
    )

    result = json.loads(srv.quest_add(mission_id, "two"))

    assert result["deck_written"] is False
    assert result["error"] == "Deck bridge unavailable: unavailable"
    assert "code" not in result
    assert db.get_mission(mission_id)["description"] == "- [ ] one"
    assert len(db.list_checklist_items(mission_id)) == 1


# ── Refresh OK: the replica mirrors Deck, read back from the DB ──────────


def test_quest_add_refreshes_replica_from_the_acknowledged_card(
    tmp_path, monkeypatch, project_maps
):
    srv, db, mission_id = _make_replica(tmp_path, monkeypatch, "- [ ] one")
    deck = FakeDeck(description="- [ ] one")
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)

    result = json.loads(srv.quest_add(mission_id, "two"))

    assert result["done"] is False
    assert result["quest_id"] > 0

    # Replica read back from the DB, never trusted from the response payload.
    mission = db.get_mission(mission_id)
    assert mission["description"] == deck.description
    assert mission["description"].endswith("[](#q:%d)" % result["quest_id"])
    assert mission["checklist_total"] == 2
    assert mission["checklist_done"] == 0
    replica = db.list_checklist_items(mission_id)
    assert [(q["item_index"], q["text"], q["done"]) for q in replica] == [
        (0, "one", 0),
        (1, "two", 0),
    ]


def test_each_write_op_uses_one_card_read_and_one_write_no_n_plus_one(
    tmp_path, monkeypatch, project_maps
):
    """A card with several quests costs the same 2 Deck calls as a card with one."""
    three_quests = "\n".join(f"- [ ] q{i}" for i in range(3))
    srv, db, mission_id = _make_replica(
        tmp_path,
        monkeypatch,
        three_quests,
        quests=(("q0", 0), ("q1", 0), ("q2", 0)),
    )

    deck = FakeDeck(description=three_quests)
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    assert json.loads(srv.quest_add(mission_id, "q3"))["done"] is False
    assert deck.tool_names() == ["deck_get_card", "deck_update_card"]

    deck.calls.clear()
    quest = db.list_checklist_items(mission_id)[1]
    assert json.loads(srv.quest_update(quest["id"], title="renamed"))["done"] is False
    assert deck.tool_names() == ["deck_get_card", "deck_update_card"]

    deck.calls.clear()
    assert "error" not in json.loads(srv.mission_update_title(mission_id, "New"))
    assert deck.tool_names() == ["deck_get_card", "deck_update_card"]


def test_card_update_description_refreshes_the_resolved_mission(
    tmp_path, monkeypatch, project_maps
):
    """The legacy raw tool also refreshes when a mission is resolved (mission_id)."""
    srv, db, mission_id = _make_replica(tmp_path, monkeypatch, "- [ ] one")
    deck = FakeDeck(description="- [ ] one")
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)

    result = json.loads(
        srv.card_update_description(
            description="New prose\n- [ ] sneaky", mission_id=mission_id
        )
    )

    assert result["status"] == "ok"
    assert result["mission_id"] == mission_id
    # Replica read from the DB mirrors the sanitized write Deck acknowledged.
    mission = db.get_mission(mission_id)
    assert mission["description"] == deck.description == "New prose"
    assert mission["checklist_total"] == 0
    assert db.list_checklist_items(mission_id) == []


# ── Refresh failure: explicit, never a clean success ─────────────────────


def test_quest_add_reports_deck_written_and_replica_stale(
    tmp_path, monkeypatch, project_maps
):
    srv, db, mission_id = _make_replica(tmp_path, monkeypatch, "- [ ] one")
    deck = FakeDeck(description="- [ ] one")
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)

    def replica_down(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "upsert_mission", replica_down)

    result = json.loads(srv.quest_add(mission_id, "two"))

    assert result["status"] == "error"
    assert result["code"] == "replica_refresh_failed"
    assert result["deck_written"] is True
    assert "quest appended" in result["deck_written_what"]
    assert "disk full" in result["replica_refresh_error"]
    # The message distinguishes "Deck written" from "replica not updated".
    assert "Deck" in result["error"]
    assert "replica" in result["error"]
    assert "sync_task" in result["error"]

    # Deck really changed; the replica really did not.
    assert deck.description.startswith("- [ ] one\n- [ ] two [](#q:")
    assert db.get_mission(mission_id)["description"] == "- [ ] one"


def _build_turn(tmp_path, monkeypatch, db_name="end-turn-per-op.db"):
    from ultratimonel import server as srv
    from ultratimonel.persistence import Persistence

    db = Persistence(db_path=str(tmp_path / db_name))
    monkeypatch.setattr(srv, "persistence", db)
    mission_id = db.upsert_mission(
        deck_task_id=189, project="testproj", title="Mission", status="pendiente"
    )
    quest_id = db.upsert_checklist_item(
        mission_id=mission_id, item_index=0, text="open", done=0
    )
    intento_id = db.create_intento("sess-1", "testproj", mission_id, quest_id)
    db.capture_gates_for_intento(
        intento_id,
        [{"name": "1a", "state": "PASS", "mandatory": 1}],
    )
    srv._set_active_intento(intento_id, "sess-1", "testproj")
    monkeypatch.setattr(srv, "_resolve_board_id", lambda project: (21, None))
    monkeypatch.setattr(
        srv, "_resolve_stack_for_card", lambda board_id, mission=None: (111, None, None)
    )
    writes = []
    monkeypatch.setattr(
        srv.deck_bridge,
        "complete_quest_identity",
        lambda board_id, stack_id, card_id, quest_id, item_index: writes.append(
            (board_id, stack_id, card_id, quest_id, item_index)
        )
        or (
            {"identity": "positional", "line_no": 0, "quest_id": quest_id},
            None,
        ),
    )
    return srv, db, mission_id, quest_id, intento_id, writes


def test_end_turn_replica_failure_is_not_a_clean_closure(tmp_path, monkeypatch):
    srv, db, mission_id, quest_id, intento_id, writes = _build_turn(
        tmp_path, monkeypatch
    )

    def replica_down(*args, **kwargs):
        raise RuntimeError("replica locked")

    monkeypatch.setattr(db, "set_quest_done", replica_down)

    result = json.loads(srv.end_turn(intento_id))

    # Deck accepted the closure; the operation must NOT read as a clean close.
    assert writes == [(21, 111, 189, quest_id, 0)]
    assert result["status"] == "error"
    assert result["code"] == "replica_refresh_failed"
    assert result["deck_written"] is True
    assert result["quest_done"] is False
    assert result["quest_done_reason"] == "replica_refresh_failed"
    assert "replica locked" in result["replica_refresh_error"]
    assert "sync_task" in result["error"]

    # The turn is still finalized (never left running) and the replica is stale.
    assert db.get_intento(intento_id)["status"] == "success"
    assert db.get_checklist_item_by_id(quest_id)["done"] == 0
    srv._clear_active_intento()


def test_end_turn_success_refreshes_mission_counters(tmp_path, monkeypatch):
    srv, db, mission_id, quest_id, intento_id, writes = _build_turn(
        tmp_path, monkeypatch
    )

    result = json.loads(srv.end_turn(intento_id))

    assert result["status"] == "ok"
    assert result["quest_done"] is True
    assert result["quest_done_reason"] == "refreshed"
    assert result["deck_written"] is True
    mission = db.get_mission(mission_id)
    assert mission["checklist_total"] == 1
    assert mission["checklist_done"] == 1
    assert db.get_checklist_item_by_id(quest_id)["done"] == 1
    srv._clear_active_intento()


# ── end_turn honest policy outcomes: not errors, clearly readable ────────


def test_end_turn_quest_done_false_by_policy_is_not_an_error(tmp_path, monkeypatch):
    srv, db, _mission_id, quest_id, intento_id, writes = _build_turn(
        tmp_path, monkeypatch
    )

    result = json.loads(srv.end_turn(intento_id, quest_done=False))

    assert result["status"] == "ok"
    assert result["final_status"] == "success"
    assert result["quest_done"] is False
    assert result["quest_done_reason"] == "vetoed"
    assert writes == []
    assert db.get_checklist_item_by_id(quest_id)["done"] == 0
    srv._clear_active_intento()


def test_end_turn_non_success_reports_not_success_without_error(tmp_path, monkeypatch):
    srv, db, _mission_id, quest_id, intento_id, writes = _build_turn(
        tmp_path, monkeypatch
    )

    result = json.loads(srv.end_turn(intento_id, status="aborted"))

    assert result["status"] == "ok"
    assert result["final_status"] == "aborted"
    assert result["quest_done"] is False
    assert result["quest_done_reason"] == "not_success"
    assert writes == []
    assert db.get_checklist_item_by_id(quest_id)["done"] == 0
    srv._clear_active_intento()
