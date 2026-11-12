"""Card #218 quest 4: stable quest identity through a server-owned marker.

Format (invisible in Deck's markdown-it renderer, survives the ``href``):

    - [ ] text [](#q:11403)

The marker is composed by the server, never by the model. It is not part of
the quest text returned to the user, and delete / reorder / end_turn use it
instead of positional arithmetic.
"""

import json
from unittest.mock import patch

import pytest

from ultratimonel import deck_bridge


class FakeDeck:
    """Minimal stateful Deck over the MCP tool surface."""

    def __init__(self, description="", title="Mission", card_id=189):
        self.title = title
        self.description = description
        self.card_id = card_id
        self.calls = []

    def __call__(self, server_name, tool_name, params=None, timeout=8.0):
        self.calls.append((tool_name, dict(params or {})))
        if tool_name == "deck_get_card":
            return (
                {"id": self.card_id, "title": self.title, "description": self.description},
                None,
            )
        if tool_name == "deck_update_card":
            self.title = params["title"]
            self.description = params["description"]
            return ({"id": self.card_id}, None)
        if tool_name == "deck_get_stacks":
            return ([{"id": 111, "title": "Backlog", "cards": [{"id": self.card_id}]}], None)
        return (None, "unavailable")

    def tool_names(self):
        return [name for name, _ in self.calls]


@pytest.fixture
def project_maps():
    with patch("ultratimonel.context_extractor.get_project_maps") as mock_maps:
        mock_maps.return_value = {"testproj": {"deck_board_id": 21}}
        yield mock_maps


@pytest.fixture
def replica(tmp_path, monkeypatch):
    from ultratimonel import server as srv
    from ultratimonel.persistence import Persistence

    db = Persistence(db_path=str(tmp_path / "marker-identity.db"))
    monkeypatch.setattr(srv, "persistence", db)
    srv._clear_active_intento()
    yield srv, db
    db.close()
    srv._clear_active_intento()


def _mission(db, description="", quests=(), deck_task_id=189):
    mission_id = db.upsert_mission(
        deck_task_id=deck_task_id,
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
    return mission_id


def _marked(db, mission_id):
    lines = []
    for quest in db.list_checklist_items(mission_id):
        state = "x" if quest["done"] else " "
        lines.append(f"- [{state}] {quest['text']} [](#q:{quest['id']})")
    return "\n".join(lines)


# ── parser ──────────────────────────────────────────────────────────────


def test_parser_marker_line_returns_its_id_and_clean_text():
    description = "- [ ] deploy [](#q:11403)"
    assert deck_bridge.extract_quests(description) == [
        {
            "line_no": 0,
            "done": False,
            "text": "deploy",
            "quest_id": 11403,
        }
    ]


def test_parser_unmarked_line_never_invents_an_id():
    description = "- [x] legacy line"
    parsed = deck_bridge.extract_quests(description)
    assert parsed == [
        {"line_no": 0, "done": True, "text": "legacy line", "quest_id": None}
    ]


def test_parser_marker_not_at_end_is_plain_text():
    parsed = deck_bridge.extract_quests("- [ ] x [](#q:7) trailing")
    assert parsed[0]["quest_id"] is None
    assert parsed[0]["text"] == "x [](#q:7) trailing"


def test_classify_identity_marker_legacy_mixed_empty():
    assert deck_bridge.classify_identity("- [ ] a [](#q:1)") == "marker"
    assert deck_bridge.classify_identity("- [ ] a") == "legacy"
    assert (
        deck_bridge.classify_identity("- [ ] a [](#q:1)\n- [ ] b") == "mixed"
    )
    assert deck_bridge.classify_identity("just prose") == "empty"


# ── quest_add composes the marker ───────────────────────────────────────


def test_quest_add_writes_marker_with_the_returned_id(replica, project_maps):
    srv, db = replica
    mission_id = _mission(db, "", [("one", 0)])
    deck = FakeDeck(description=_marked(db, mission_id))
    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        result = json.loads(srv.quest_add(mission_id, "two"))

    quest_id = result["quest_id"]
    assert result["identity"] == "marker"
    assert deck.description.split("\n")[-1] == f"- [ ] two [](#q:{quest_id})"
    # The marker is not part of the user-facing / replica text.
    replica_quests = db.list_checklist_items(mission_id)
    assert replica_quests[-1]["text"] == "two"
    assert replica_quests[-1]["id"] == quest_id


def test_quest_add_on_legacy_mission_appends_a_marker(replica, project_maps):
    srv, db = replica
    mission_id = _mission(db, "- [ ] one", [("one", 0)])
    deck = FakeDeck(description="- [ ] one")
    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        result = json.loads(srv.quest_add(mission_id, "two"))

    lines = deck.description.split("\n")
    assert lines[0] == "- [ ] one"
    assert lines[1] == f"- [ ] two [](#q:{result['quest_id']})"
    # The mission is now mixed: delete/reorder still refuse, by design.
    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        deleted = json.loads(
            srv.quest_delete(result["quest_id"], confirm=True, reason="cleanup")
        )
    assert deleted["code"] == "legacy_identity"


def test_round_trip_description_is_byte_identical(replica, project_maps):
    srv, db = replica
    mission_id = _mission(db, "", [("one", 0)])
    deck = FakeDeck(description=_marked(db, mission_id))
    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        result = json.loads(srv.quest_add(mission_id, "two"))

    written = deck.description
    quest_id = result["quest_id"]
    expected_line = f"- [ ] two [](#q:{quest_id})"
    assert written.split("\n")[-1] == expected_line
    parsed = deck_bridge.extract_quests(written)[-1]
    assert parsed["quest_id"] == quest_id
    assert parsed["text"] == "two"
    # Re-composition from the parsed parts reproduces the exact bytes.
    assert deck_bridge.compose_quest_line(parsed["text"], parsed["quest_id"]) == expected_line


def test_quest_update_keeps_the_existing_marker(replica, project_maps):
    srv, db = replica
    mission_id = _mission(db, "", [("one", 0)])
    deck = FakeDeck(description=_marked(db, mission_id))
    quest = db.list_checklist_items(mission_id)[0]

    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        result = json.loads(srv.quest_update(quest["id"], title="renamed"))

    assert result["done"] is False
    assert deck.description == f"- [ ] renamed [](#q:{quest['id']})"


def test_clean_prose_recognizes_marked_and_unmarked_quests():
    prose = "Intro\n- [ ] marked [](#q:1)\n- [x] legacy\nOutro"
    assert deck_bridge.clean_prose(prose) == "Intro\nOutro"


def test_marker_is_not_part_of_user_facing_text(replica, project_maps):
    srv, db = replica
    mission_id = _mission(db, "", [("one", 0)])
    deck = FakeDeck(description=_marked(db, mission_id))
    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        added = json.loads(srv.quest_add(mission_id, "two [](#q:999) injected"))

    # A forged marker in the input is stripped; the server-owned one wins.
    assert added["title"] == "two injected"
    assert deck.description.split("\n")[-1].count("[](#q:") == 1
    quest = db.list_checklist_items(mission_id)[-1]
    assert quest["text"] == "two injected"
    assert added["title"] == quest["text"]


# ── end_turn identity ───────────────────────────────────────────────────


def _turn(db, mission_id, quest_id):
    intento_id = db.create_intento("sess-1", "testproj", mission_id, quest_id)
    db.capture_gates_for_intento(
        intento_id,
        [{"name": "1a", "state": "PASS", "mandatory": 1}],
    )
    return intento_id


def test_end_turn_closes_by_marker_after_manual_reorder(
    replica, monkeypatch
):
    srv, db = replica
    mission_id = _mission(db, "", [("one", 0), ("two", 0), ("three", 0)])
    quests = db.list_checklist_items(mission_id)
    target = quests[0]
    marked = _marked(db, mission_id)
    # Human reorders the Deck lines before the turn closes: the old positional
    # path would close "three" instead of the target.
    reordered = "\n".join(
        [marked.split("\n")[2], marked.split("\n")[0], marked.split("\n")[1]]
    )
    deck = FakeDeck(description=reordered)
    intento_id = _turn(db, mission_id, target["id"])
    srv._set_active_intento(intento_id, "sess-1", "testproj")
    monkeypatch.setattr(srv, "_resolve_board_id", lambda project: (21, None))
    monkeypatch.setattr(
        srv, "_resolve_stack_for_card", lambda board_id, mission=None: (111, None, None)
    )
    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        result = json.loads(srv.end_turn(intento_id))

    assert result["status"] == "ok"
    assert result["identity"] == "marker"
    assert result["quest_done"] is True
    lines = deck.description.split("\n")
    # The target marker was reordered to the middle; end_turn followed it.
    assert lines[0].startswith("- [ ] three")
    assert lines[1] == f"- [x] one [](#q:{target['id']})"
    assert lines[2].startswith("- [ ] two")
    assert db.get_checklist_item_by_id(target["id"])["done"] == 1


def test_end_turn_legacy_mission_reports_positional(replica, monkeypatch):
    srv, db = replica
    mission_id = _mission(db, "- [ ] one\n- [ ] two", [("one", 0), ("two", 0)])
    target = db.list_checklist_items(mission_id)[0]
    deck = FakeDeck(description="- [ ] one\n- [ ] two")
    intento_id = _turn(db, mission_id, target["id"])
    srv._set_active_intento(intento_id, "sess-1", "testproj")
    monkeypatch.setattr(srv, "_resolve_board_id", lambda project: (21, None))
    monkeypatch.setattr(
        srv, "_resolve_stack_for_card", lambda board_id, mission=None: (111, None, None)
    )
    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        result = json.loads(srv.end_turn(intento_id))

    assert result["status"] == "ok"
    assert result["identity"] == "positional"
    assert deck.description == "- [x] one\n- [ ] two"
    assert db.get_checklist_item_by_id(target["id"])["done"] == 1


def test_end_turn_marker_mission_missing_marker_fails_closed(replica, monkeypatch):
    srv, db = replica
    mission_id = _mission(db, "", [("one", 0)])
    target = db.list_checklist_items(mission_id)[0]
    # The Deck card no longer carries the target marker.
    deck = FakeDeck(description="- [ ] one [](#q:999999)")
    intento_id = _turn(db, mission_id, target["id"])
    srv._set_active_intento(intento_id, "sess-1", "testproj")
    monkeypatch.setattr(srv, "_resolve_board_id", lambda project: (21, None))
    monkeypatch.setattr(
        srv, "_resolve_stack_for_card", lambda board_id, mission=None: (111, None, None)
    )
    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        result = json.loads(srv.end_turn(intento_id))

    assert result["quest_done"] is False
    assert result["quest_done_reason"] == "marker_not_found"
    assert deck.description == "- [ ] one [](#q:999999)"
    assert db.get_checklist_item_by_id(target["id"])["done"] == 0


# ── explicit, versioned migration ───────────────────────────────────────


def _migrate(srv, mission_id, **kwargs):
    with patch("ultratimonel.mcp_client.call_mcp_tool", kwargs.pop("deck")):
        return json.loads(
            srv.quest_migrate_identity(
                mission_id,
                confirm=kwargs.pop("confirm", True),
                reason=kwargs.pop("reason", "adopt marker identity"),
                **kwargs,
            )
        )


def test_migrate_adds_markers_and_preserves_every_id(replica, project_maps):
    srv, db = replica
    mission_id = _mission(
        db, "- [ ] one\n- [x] two", [("one", 0), ("two", 1)]
    )
    before = [(q["id"], q["text"], q["done"]) for q in db.list_checklist_items(mission_id)]
    deck = FakeDeck(description="- [ ] one\n- [x] two")

    result = _migrate(srv, mission_id, deck=deck)

    assert result["status"] == "migrated"
    assert result["deck_written"] is True
    assert deck.description == "\n".join(
        [
            f"- [ ] one [](#q:{before[0][0]})",
            f"- [x] two [](#q:{before[1][0]})",
        ]
    )
    after = [(q["id"], q["text"], q["done"]) for q in db.list_checklist_items(mission_id)]
    assert after == before
    assert result["quest_ids"] == [before[0][0], before[1][0]]

    with db._conn() as conn:
        audit = conn.execute(
            "SELECT * FROM quest_identity_migrations WHERE id = ?",
            (result["audit_id"],),
        ).fetchone()
        assert audit is not None
        assert audit["mission_id"] == mission_id
        assert audit["quests_migrated"] == 2
        assert json.loads(audit["quest_ids"]) == [before[0][0], before[1][0]]


def test_migrate_is_idempotent(replica, project_maps):
    srv, db = replica
    mission_id = _mission(db, "- [ ] one", [("one", 0)])
    deck = FakeDeck(description="- [ ] one")

    first = _migrate(srv, mission_id, deck=deck)
    assert first["status"] == "migrated"
    migrated_description = deck.description
    before = [(q["id"], q["text"]) for q in db.list_checklist_items(mission_id)]

    calls_before = len(deck.calls)
    second = _migrate(srv, mission_id, deck=deck)

    assert second["status"] == "already_migrated"
    assert second["deck_written"] is False
    assert deck.description == migrated_description
    assert deck.description.count("[](#q:") == 1
    assert [(q["id"], q["text"]) for q in db.list_checklist_items(mission_id)] == before
    # A read to classify, but no deck_update_card on the second run.
    assert "deck_update_card" not in deck.tool_names()[calls_before:]


def test_migrate_requires_confirm_and_reason(replica, project_maps):
    srv, db = replica
    mission_id = _mission(db, "- [ ] one", [("one", 0)])
    deck = FakeDeck(description="- [ ] one")

    no_confirm = _migrate(srv, mission_id, confirm=False, deck=deck)
    no_reason = _migrate(srv, mission_id, reason="", deck=deck)

    for result in (no_confirm, no_reason):
        assert result["deck_written"] is False
    assert deck.calls == []
    assert deck.description == "- [ ] one"


def test_migrate_mixed_preserves_existing_marker(replica, project_maps):
    srv, db = replica
    mission_id = _mission(db, "", [("one", 0), ("two", 0)])
    quests = db.list_checklist_items(mission_id)
    mixed = f"- [ ] one [](#q:{quests[0]['id']})\n- [ ] two"
    deck = FakeDeck(description=mixed)

    result = _migrate(srv, mission_id, deck=deck)

    assert result["status"] == "migrated"
    assert deck.description == "\n".join(
        [
            f"- [ ] one [](#q:{quests[0]['id']})",
            f"- [ ] two [](#q:{quests[1]['id']})",
        ]
    )
    assert result["migrated_ids"] == [quests[1]["id"]]


def test_migrate_write_failure_leaves_mission_untouched(replica, project_maps):
    srv, db = replica
    mission_id = _mission(db, "- [ ] one", [("one", 0)])
    deck = FakeDeck(description="- [ ] one")
    before = db.get_mission(mission_id)["description"]

    def write_down(*args, **kwargs):
        return (None, "unavailable")

    with patch.object(deck_bridge, "_write_card", write_down):
        result = _migrate(srv, mission_id, deck=deck)

    assert result["deck_written"] is False
    assert result["code"] == "unavailable"
    assert db.get_mission(mission_id)["description"] == before
    with db._conn() as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM quest_identity_migrations WHERE mission_id = ?",
            (mission_id,),
        ).fetchone()[0] == 0


def test_migrated_mission_enables_delete_and_reorder(replica, project_maps):
    srv, db = replica
    mission_id = _mission(db, "- [ ] one\n- [ ] two", [("one", 0), ("two", 0)])
    deck = FakeDeck(description="- [ ] one\n- [ ] two")
    _migrate(srv, mission_id, deck=deck)
    quests = db.list_checklist_items(mission_id)

    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        deleted = json.loads(
            srv.quest_delete(quests[0]["id"], confirm=True, reason="after migration")
        )

    assert deleted["status"] == "deleted"
    assert deleted["identity"] == "marker"
    assert [q["id"] for q in db.list_checklist_items(mission_id)] == [quests[1]["id"]]
