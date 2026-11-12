"""Quest delete / reorder (#218, quest 7): identity-preserving checklist edits.

The tests use a real temporary SQLite replica and a simulated Deck bridge: no
live MCP call, no real card is written.

The central invariant is the ``(id, text)`` pair: deleting or reordering must
never rename a surviving quest, even though Deck quest lines carry no id and the
replica's upsert key is positional.
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

    def tool_names(self):
        return [name for name, _ in self.calls]


def _make_replica(tmp_path, monkeypatch, description, quests):
    from ultratimonel import server as srv
    from ultratimonel.persistence import Persistence

    db = Persistence(db_path=str(tmp_path / "quest-delete-reorder.db"))
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


def _pairs(db, mission_id):
    return [
        {"id": q["id"], "text": q["text"], "done": q["done"], "index": q["item_index"]}
        for q in db.list_checklist_items(mission_id)
    ]


# ── quest_delete guards ─────────────────────────────────────────────────


def test_delete_requires_confirm_and_reason(tmp_path, monkeypatch, project_maps):
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, "- [ ] one\n- [ ] two", [("one", 0), ("two", 0)]
    )
    deck = FakeDeck(description="- [ ] one\n- [ ] two")
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    quest = db.list_checklist_items(mission_id)[0]
    before = _pairs(db, mission_id)

    no_confirm = json.loads(srv.quest_delete(quest["id"], reason="cleanup"))
    no_reason = json.loads(srv.quest_delete(quest["id"], confirm=True))

    for result in (no_confirm, no_reason):
        assert "error" in result
        assert result["deck_written"] is False
    assert deck.calls == []
    assert deck.description == "- [ ] one\n- [ ] two"
    assert _pairs(db, mission_id) == before


# ── quest_delete happy path ─────────────────────────────────────────────


def test_delete_removes_only_target_and_keeps_surviving_ids(
    tmp_path, monkeypatch, project_maps
):
    description = "- [ ] one\n- [ ] two\n- [x] three"
    srv, db, mission_id = _make_replica(
        tmp_path,
        monkeypatch,
        description,
        [("one", 0), ("two", 0), ("three", 1)],
    )
    deck = FakeDeck(description=description)
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    quests = db.list_checklist_items(mission_id)
    target = quests[1]
    before = _pairs(db, mission_id)

    result = json.loads(
        srv.quest_delete(target["id"], confirm=True, reason="recompose checklist")
    )

    assert result["status"] == "deleted"
    assert result["quest_id"] == target["id"]
    assert result["deck_written"] is True
    assert deck.description == "- [ ] one\n- [x] three"
    after = _pairs(db, mission_id)
    # Same ids and texts for every survivor, only item_index shifts.
    assert [(p["id"], p["text"]) for p in after] == [
        (p["id"], p["text"]) for p in before if p["id"] != target["id"]
    ]
    assert [p["index"] for p in after] == [0, 1]
    assert db.get_mission(mission_id)["checklist_total"] == 2


def test_delete_last_quest_keeps_mission_alive(tmp_path, monkeypatch, project_maps):
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, "- [ ] only", [("only", 0)]
    )
    deck = FakeDeck(description="- [ ] only")
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    target = db.list_checklist_items(mission_id)[0]

    result = json.loads(
        srv.quest_delete(target["id"], confirm=True, reason="empty the checklist")
    )

    assert result["status"] == "deleted"
    assert db.list_checklist_items(mission_id) == []
    mission = db.get_mission(mission_id)
    assert mission is not None
    assert mission["checklist_total"] == 0
    assert mission["checklist_done"] == 0


# ── quest_delete with history ───────────────────────────────────────────


def test_delete_with_history_is_refused_then_forced_with_audit(
    tmp_path, monkeypatch, project_maps
):
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, "- [ ] one\n- [ ] two", [("one", 0), ("two", 0)]
    )
    deck = FakeDeck(description="- [ ] one\n- [ ] two")
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    target = db.list_checklist_items(mission_id)[0]
    intento_id = db.create_intento("sess-1", "testproj", mission_id, target["id"])
    db.grant_attempts(mission_id, target["id"], 2, "hermes")
    db.append_bitacora(
        intento_id, "sess-1", "testproj", mission_id, target["id"], "success", 4
    )
    before = _pairs(db, mission_id)

    refused = json.loads(
        srv.quest_delete(target["id"], confirm=True, reason="cleanup")
    )

    assert refused["code"] == "quest_has_history"
    assert refused["deck_written"] is False
    assert deck.calls == []
    assert _pairs(db, mission_id) == before

    forced = json.loads(
        srv.quest_delete(
            target["id"], confirm=True, reason="cleanup", force=True
        )
    )

    assert forced["status"] == "deleted"
    assert forced["forced"] is True
    assert forced["deleted"] == {
        "intentos": 1,
        "attempt_grants": 1,
        "turn_bitacora": 1,
    }
    assert forced["deleted_ids"]["quest_ids"] == [target["id"]]
    assert forced["deleted_ids"]["intento_ids"] == [intento_id]
    assert len(forced["deleted_ids"]["attempt_grant_ids"]) == 1
    assert len(forced["deleted_ids"]["turn_bitacora_ids"]) == 1

    with db._conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM intentos WHERE checklist_item_id = ?",
            (target["id"],),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM attempt_grants WHERE checklist_item_id = ?",
            (target["id"],),
        ).fetchone()[0] == 0
        assert conn.execute(
            "SELECT COUNT(*) FROM turn_bitacora WHERE checklist_item_id = ?",
            (target["id"],),
        ).fetchone()[0] == 0
        audit = conn.execute(
            "SELECT * FROM quest_deletions WHERE id = ?",
            (forced["audit_id"],),
        ).fetchone()
        assert audit is not None
        assert audit["quest_id"] == target["id"]
        assert audit["intentos_deleted"] == 1
        assert audit["forced"] == 1
        assert target["id"] in json.loads(audit["deleted_ids"])["quest_ids"]


# ── quest_reorder ───────────────────────────────────────────────────────


def test_reorder_applies_exact_order_with_same_pairs(
    tmp_path, monkeypatch, project_maps
):
    description = "- [ ] one\n- [x] two\n- [ ] three"
    srv, db, mission_id = _make_replica(
        tmp_path,
        monkeypatch,
        description,
        [("one", 0), ("two", 1), ("three", 0)],
    )
    deck = FakeDeck(description=description)
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    quests = db.list_checklist_items(mission_id)
    before = {(q["id"], q["text"]) for q in quests}
    ordered = [quests[2]["id"], quests[0]["id"], quests[1]["id"]]

    result = json.loads(srv.quest_reorder(mission_id, ordered))

    assert result["status"] == "ok"
    assert result["ordered_ids"] == ordered
    after = db.list_checklist_items(mission_id)
    assert [q["id"] for q in after] == ordered
    assert {(q["id"], q["text"]) for q in after} == before
    assert deck.description == "- [ ] three\n- [ ] one\n- [x] two"
    # One read + one write, never N calls.
    assert deck.tool_names() == ["deck_get_card", "deck_update_card"]


def test_reorder_rejects_foreign_missing_and_duplicate_ids(
    tmp_path, monkeypatch, project_maps
):
    description = "- [ ] one\n- [ ] two"
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, description, [("one", 0), ("two", 0)]
    )
    deck = FakeDeck(description=description)
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    quests = db.list_checklist_items(mission_id)
    before = _pairs(db, mission_id)
    ida, idb = quests[0]["id"], quests[1]["id"]

    missing = json.loads(srv.quest_reorder(mission_id, [ida]))
    extra = json.loads(srv.quest_reorder(mission_id, [ida, idb, 999999]))
    repeated = json.loads(srv.quest_reorder(mission_id, [ida, ida]))

    for result in (missing, extra, repeated):
        assert result["code"] == "quest_reorder_mismatch"
        assert result["deck_written"] is False
    assert extra["extra"] == [999999]
    assert missing["missing"] == [idb]
    assert repeated["duplicates"] == [ida]
    assert deck.calls == []
    assert _pairs(db, mission_id) == before


# ── fail-closed replica refresh ─────────────────────────────────────────


def test_delete_refresh_failure_reports_deck_written(
    tmp_path, monkeypatch, project_maps
):
    description = "- [ ] one\n- [ ] two"
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, description, [("one", 0), ("two", 0)]
    )
    deck = FakeDeck(description=description)
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    target = db.list_checklist_items(mission_id)[0]

    def replica_down(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "delete_checklist_item", replica_down)

    result = json.loads(
        srv.quest_delete(target["id"], confirm=True, reason="cleanup")
    )

    assert result["status"] == "error"
    assert result["code"] == "replica_refresh_failed"
    assert result["deck_written"] is True
    assert "disk full" in result["replica_refresh_error"]
    # Deck really changed; the replica really did not.
    assert deck.description == "- [ ] two"
    assert len(db.list_checklist_items(mission_id)) == 2


def test_reorder_refresh_failure_reports_deck_written(
    tmp_path, monkeypatch, project_maps
):
    description = "- [ ] one\n- [ ] two"
    srv, db, mission_id = _make_replica(
        tmp_path, monkeypatch, description, [("one", 0), ("two", 0)]
    )
    deck = FakeDeck(description=description)
    monkeypatch.setattr("ultratimonel.mcp_client.call_mcp_tool", deck)
    quests = db.list_checklist_items(mission_id)
    ordered = [quests[1]["id"], quests[0]["id"]]

    def replica_down(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(db, "reorder_checklist_items", replica_down)

    result = json.loads(srv.quest_reorder(mission_id, ordered))

    assert result["status"] == "error"
    assert result["code"] == "replica_refresh_failed"
    assert result["deck_written"] is True
    assert "disk full" in result["replica_refresh_error"]
    assert deck.description == "- [ ] two\n- [ ] one"
    assert [q["text"] for q in db.list_checklist_items(mission_id)] == ["one", "two"]
