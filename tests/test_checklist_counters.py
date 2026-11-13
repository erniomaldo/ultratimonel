"""Quest 19 (#218): mission checklist counters stay truthful.

``missions.checklist_total`` / ``checklist_done`` are denormalized copies of the
``checklist_items`` rows. Every path that mutates a checklist must leave both
counters matching the rows in the same operation, and the explicit repair tool
must fix counters that an older write path already froze.

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
                [{"id": 111, "title": "Backlog", "cards": [{"id": self.card_id}]}],
                None,
            )
        return (None, "unavailable")


def _make_replica(tmp_path, monkeypatch, quests, counters=None):
    from ultratimonel import server as srv
    from ultratimonel.persistence import Persistence

    db = Persistence(db_path=str(tmp_path / "checklist-counters.db"))
    monkeypatch.setattr(srv, "persistence", db)
    if counters is None:
        counters = (len(quests), sum(done for _, done in quests))
    mission_id = db.upsert_mission(
        deck_task_id=189,
        project="testproj",
        title="Mission",
        description="",
        status="pendiente",
        checklist_total=counters[0],
        checklist_done=counters[1],
    )
    db.set_mission_deck_stack_id(mission_id, 111)
    for index, (text, done) in enumerate(quests):
        db.upsert_checklist_item(
            mission_id=mission_id, item_index=index, text=text, done=done
        )
    return srv, db, mission_id


def _marked(db, mission_id):
    """Build the marked Deck description for the replica's current quests."""
    lines = []
    for quest in db.list_checklist_items(mission_id):
        state = "x" if quest["done"] else " "
        lines.append(f"- [{state}] {quest['text']} [](#q:{quest['id']})")
    return "\n".join(lines)


def _counters(db, mission_id):
    mission = db.get_mission(mission_id)
    return mission["checklist_total"], mission["checklist_done"]


def _rows(db, mission_id):
    return len(db.list_checklist_items(mission_id)), sum(
        1 for q in db.list_checklist_items(mission_id) if q["done"]
    )


@pytest.fixture
def project_maps():
    with patch("ultratimonel.context_extractor.get_project_maps") as mock_maps:
        mock_maps.return_value = {"testproj": {"deck_board_id": 21}}
        yield mock_maps


# ── each write path keeps both counters in sync with the rows ───────────


def test_quest_add_single_refreshes_counters(tmp_path, monkeypatch, project_maps):
    srv, db, mission_id = _make_replica(tmp_path, monkeypatch, [("one", 0)])
    deck = FakeDeck(description=_marked(db, mission_id))
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)

    result = json.loads(srv.quest_add(mission_id, "two"))

    assert result["quest_id"] > 0
    assert _counters(db, mission_id) == _rows(db, mission_id) == (2, 0)


def test_quest_add_batch_refreshes_counters(tmp_path, monkeypatch, project_maps):
    srv, db, mission_id = _make_replica(tmp_path, monkeypatch, [("one", 0)])
    deck = FakeDeck(description=_marked(db, mission_id))
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)

    result = json.loads(srv.quest_add(mission_id, quests=["two", "three"]))

    assert result["count"] == 2
    assert _counters(db, mission_id) == _rows(db, mission_id) == (3, 0)


def test_quest_update_refreshes_counters(tmp_path, monkeypatch, project_maps):
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, [("one", 1), ("two", 0)]
    )
    deck = FakeDeck(description=_marked(db, mission_id))
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    target = db.list_checklist_items(mission_id)[0]

    result = json.loads(srv.quest_update(target["id"], title="one rewritten"))

    assert result["done"] is False
    # quest_update always resets done, and the counter must follow.
    assert _counters(db, mission_id) == _rows(db, mission_id) == (2, 0)


def test_quest_delete_refreshes_counters(tmp_path, monkeypatch, project_maps):
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, [("one", 0), ("two", 1), ("three", 0)]
    )
    deck = FakeDeck(description=_marked(db, mission_id))
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    target = db.list_checklist_items(mission_id)[0]

    result = json.loads(
        srv.quest_delete(target["id"], confirm=True, reason="drop a quest")
    )

    assert result["status"] == "deleted"
    assert _counters(db, mission_id) == _rows(db, mission_id) == (2, 1)


def test_quest_reorder_refreshes_counters(tmp_path, monkeypatch, project_maps):
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, [("one", 0), ("two", 1)]
    )
    deck = FakeDeck(description=_marked(db, mission_id))
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    ids = [q["id"] for q in db.list_checklist_items(mission_id)]

    result = json.loads(srv.quest_reorder(mission_id, list(reversed(ids))))

    assert result["status"] == "ok"
    assert _counters(db, mission_id) == _rows(db, mission_id) == (2, 1)


def test_end_turn_refreshes_frozen_counters(tmp_path, monkeypatch, project_maps):
    """end_turn recomputes counters from the rows even when they were frozen."""
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, [("one", 0), ("two", 0)], counters=(0, 0)
    )
    deck = FakeDeck(description=_marked(db, mission_id))
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    srv._clear_active_intento()

    quest = db.list_checklist_items(mission_id)[0]
    intento_id = db.create_intento("sess-1", "testproj", mission_id, quest["id"])
    db.capture_gates_for_intento(
        intento_id, [{"gate_name": "1a", "state": "PASS", "mandatory": 1}]
    )

    result = json.loads(srv.end_turn(intento_id))

    assert result["final_status"] == "success"
    assert result["quest_done"] is True
    assert _counters(db, mission_id) == _rows(db, mission_id) == (2, 1)


# ── the frozen-counter write path cannot zero the counters ──────────────


def test_sync_tasks_does_not_zero_counters_when_deck_parse_is_empty(
    tmp_path, monkeypatch, project_maps
):
    """Regression: a Deck read with no quest lines must not zero live counters.

    This is how the replica froze at 0/0 while it still had 19 quest rows: the
    bulk sync wrote counters from its own parse and left the rows in place.
    """
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, [("one", 0), ("two", 1)]
    )
    calls = []

    def deck_read(server_name, tool_name, params=None, timeout=8.0):
        calls.append(tool_name)
        if tool_name == "deck_get_stacks":
            return (
                [{"id": 111, "title": "Backlog", "cards": [{"id": 189}]}],
                None,
            )
        if tool_name == "deck_get_card":
            return ({"id": 189, "title": "Mission", "description": "prose only"}, None)
        return (None, "unavailable")

    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck_read)

    result = json.loads(srv.sync_tasks("testproj"))

    assert result["synced"] == 1
    assert result["total_errors"] == 0
    # Rows survive (the bulk path never prunes quests) and the counters agree
    # with them instead of being overwritten with the empty parse.
    assert _rows(db, mission_id) == (2, 1)
    assert _counters(db, mission_id) == (2, 1)


# ── explicit repair of already-frozen counters ──────────────────────────


def test_repair_fixes_only_the_drifted_mission(tmp_path, monkeypatch):
    srv, db, drifted = _make_replica(
        tmp_path, monkeypatch, [("a", 1), ("b", 0), ("c", 0)], counters=(0, 0)
    )
    healthy = db.upsert_mission(
        deck_task_id=190,
        project="testproj",
        title="Healthy",
        checklist_total=1,
        checklist_done=1,
    )
    db.upsert_checklist_item(healthy, item_index=0, text="done", done=1)
    before_healthy = db.get_mission(healthy)

    result = json.loads(
        srv.mission_repair_checklist_counts(
            mission_id=drifted, confirm=True, reason="counters frozen at 0"
        )
    )

    assert result["status"] == "ok"
    assert result["checked"] == 1
    assert result["changed_count"] == 1
    assert result["changed"] == [
        {
            "mission_id": drifted,
            "before": {"checklist_total": 0, "checklist_done": 0},
            "after": {"checklist_total": 3, "checklist_done": 1},
        }
    ]
    assert _counters(db, drifted) == (3, 1)
    # A mission that already matched its rows is not touched at all.
    assert db.get_mission(healthy) == before_healthy


def test_repair_is_idempotent_and_reports_unchanged(tmp_path, monkeypatch):
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, [("a", 1), ("b", 0)], counters=(0, 0)
    )

    first = json.loads(
        srv.mission_repair_checklist_counts(
            mission_id=mission_id, confirm=True, reason="repair"
        )
    )
    second = json.loads(
        srv.mission_repair_checklist_counts(
            mission_id=mission_id, confirm=True, reason="repair again"
        )
    )

    assert first["status"] == "ok"
    assert second["status"] == "unchanged"
    assert second["changed"] == []
    assert second["changed_count"] == 0
    assert _counters(db, mission_id) == (2, 1)


def test_repair_requires_confirm_and_reason(tmp_path, monkeypatch):
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, [("a", 0)], counters=(0, 0)
    )

    no_confirm = json.loads(
        srv.mission_repair_checklist_counts(mission_id=mission_id, reason="x")
    )
    no_reason = json.loads(
        srv.mission_repair_checklist_counts(mission_id=mission_id, confirm=True)
    )
    blank_reason = json.loads(
        srv.mission_repair_checklist_counts(
            mission_id=mission_id, confirm=True, reason="   "
        )
    )

    assert no_confirm["code"] == "confirmation_required"
    assert no_reason["code"] == "reason_required"
    assert blank_reason["code"] == "reason_required"
    for payload in (no_confirm, no_reason, blank_reason):
        assert payload["written"] is False
    # Nothing was written by the rejected calls.
    assert _counters(db, mission_id) == (0, 0)


def test_repair_rejects_ambiguous_or_missing_scope(tmp_path, monkeypatch):
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, [("a", 0)], counters=(0, 0)
    )

    both = json.loads(
        srv.mission_repair_checklist_counts(
            mission_id=mission_id, project="testproj", confirm=True, reason="x"
        )
    )
    neither = json.loads(
        srv.mission_repair_checklist_counts(confirm=True, reason="x")
    )

    assert both["code"] == "invalid_scope"
    assert neither["code"] == "invalid_scope"
    assert _counters(db, mission_id) == (0, 0)


def test_repair_unknown_mission_writes_nothing(tmp_path, monkeypatch):
    srv, db, _ = _make_replica(tmp_path, monkeypatch, [("a", 0)], counters=(0, 0))

    result = json.loads(
        srv.mission_repair_checklist_counts(
            mission_id=99999, confirm=True, reason="cleanup"
        )
    )

    assert result["written"] is False
    assert "not found" in result["error"]


def test_repair_project_scope_leaves_other_projects_alone(tmp_path, monkeypatch):
    srv, db, one = _make_replica(
        tmp_path, monkeypatch, [("a", 1)], counters=(0, 0)
    )
    two = db.upsert_mission(
        deck_task_id=191, project="testproj", title="Two", checklist_total=0
    )
    db.upsert_checklist_item(two, item_index=0, text="b", done=0)
    other = db.upsert_mission(
        deck_task_id=192, project="other", title="Other", checklist_total=0
    )
    db.upsert_checklist_item(other, item_index=0, text="c", done=1)

    result = json.loads(
        srv.mission_repair_checklist_counts(
            project="testproj", confirm=True, reason="project repair"
        )
    )

    assert result["checked"] == 2
    assert result["changed_count"] == 2
    assert {c["mission_id"] for c in result["changed"]} == {one, two}
    assert _counters(db, one) == (1, 1)
    assert _counters(db, two) == (1, 0)
    # Another project is never touched by a project-scoped repair.
    assert _counters(db, other) == (0, 0)


def test_repair_does_not_touch_any_other_column(tmp_path, monkeypatch):
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, [("a", 0)], counters=(7, 3)
    )
    before = db.get_mission(mission_id)

    json.loads(
        srv.mission_repair_checklist_counts(
            mission_id=mission_id, confirm=True, reason="columns"
        )
    )

    after = db.get_mission(mission_id)
    assert set(after) == set(before)
    for key in before:
        if key in ("checklist_total", "checklist_done"):
            continue
        assert after[key] == before[key], key
    assert (after["checklist_total"], after["checklist_done"]) == (1, 0)


def test_mission_without_checklist_stays_zero_zero(tmp_path, monkeypatch):
    srv, db, _ = _make_replica(tmp_path, monkeypatch, [], counters=(0, 0))
    empty = db.upsert_mission(
        deck_task_id=193, project="testproj", title="Empty", checklist_total=0,
        checklist_done=0,
    )
    # Deliberately wrong counters on a mission with no rows at all.
    wrong = db.upsert_mission(
        deck_task_id=194, project="testproj", title="Wrong", checklist_total=5,
        checklist_done=3,
    )

    result = json.loads(
        srv.mission_repair_checklist_counts(
            project="testproj", confirm=True, reason="zero rows"
        )
    )

    assert _counters(db, empty) == (0, 0)
    assert _counters(db, wrong) == (0, 0)
    assert {c["mission_id"] for c in result["changed"]} == {wrong}
