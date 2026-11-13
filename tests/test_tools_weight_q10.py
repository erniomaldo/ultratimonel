"""Card #218 quest 10: tool payload weight (batch writes, compact output, paging).

Covers the three required blocks without touching real Deck:

* ``quest_add(quests=[...])`` — one Deck description write, one replica refresh,
  ids returned in request order.
* ``map_list`` — compact by default, full payload only with ``full=True``.
* ``mission_list`` — ``limit`` / ``offset`` with a real ``total``.
"""

import json
from unittest.mock import patch

import pytest

from ultratimonel import deck_bridge
from ultratimonel import mcp_client
from ultratimonel import server as srv_module
from ultratimonel.persistence import Persistence


class FakeDeck:
    """Minimal stateful Deck over the MCP tool surface (one card per test)."""

    def __init__(self, description="", title="Mission", card_id=189):
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

    def writes(self):
        return [params for name, params in self.calls if name == "deck_update_card"]


@pytest.fixture
def replica(tmp_path, monkeypatch):
    import ultratimonel.server as srv

    db = Persistence(db_path=str(tmp_path / "q10.db"))
    monkeypatch.setattr(srv, "persistence", db)
    srv._clear_active_intento()
    yield srv, db
    db.close()
    srv._clear_active_intento()


@pytest.fixture
def project_maps():
    with patch("ultratimonel.context_extractor.get_project_maps") as mock_maps:
        mock_maps.return_value = {
            "testproj": {
                "patterns": ["test", "testproj"],
                "deck_board_id": 21,
                "collective_id": 17,
            }
        }
        yield mock_maps


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


def _many_missions(db, count, project="testproj"):
    mission_ids = []
    for index in range(count):
        mission_ids.append(
            db.upsert_mission(
                deck_task_id=1000 + index,
                project=project,
                title=f"Mission {index}",
                description=f"description {index}",
                status="pendiente",
                checklist_total=0,
                checklist_done=0,
            )
        )
    return mission_ids


# ── quest_add batch ─────────────────────────────────────────────────────


def test_quest_add_batch_of_seven_uses_one_write_and_one_refresh(
    replica, project_maps, monkeypatch
):
    srv, db = replica
    mission_id = _mission(
        db, description="- [ ] existing", quests=[("existing", 0)]
    )
    deck = FakeDeck(description="- [ ] existing")

    refresh_calls = []
    original_upsert = db.upsert_mission

    def spy_upsert(*args, **kwargs):
        refresh_calls.append(1)
        return original_upsert(*args, **kwargs)

    monkeypatch.setattr(db, "upsert_mission", spy_upsert)

    titles = [f"batch quest {index}" for index in range(7)]
    with patch.object(mcp_client, "call_mcp_tool", deck):
        result = json.loads(srv.quest_add(mission_id, quests=titles))

    assert result["mission_id"] == mission_id
    assert result["count"] == 7
    assert result["identity"] == "marker"
    quest_ids = result["quest_ids"]
    assert len(quest_ids) == 7
    assert quest_ids == sorted(quest_ids)

    # ONE Deck description write for the whole batch.
    assert len(deck.writes()) == 1
    # No N round-trips: exactly one card read + one description write.
    assert [name for name, _ in deck.calls] == [
        "deck_get_card",
        "deck_update_card",
    ]
    # ONE replica refresh for the whole batch.
    assert len(refresh_calls) == 1

    # Every new line carries its server-composed marker, in request order.
    written = deck_bridge.extract_quests(deck.description)
    assert [quest["text"] for quest in written[1:]] == titles
    assert [quest["quest_id"] for quest in written[1:]] == quest_ids

    # Replica rows use the returned ids in the same order.
    rows = db.list_checklist_items(mission_id)
    assert [row["text"] for row in rows[1:]] == titles
    assert [row["id"] for row in rows[1:]] == quest_ids
    assert all(row["done"] == 0 for row in rows[1:])


def test_quest_add_batch_rejects_title_and_quests_together(
    replica, project_maps
):
    srv, db = replica
    mission_id = _mission(db)
    deck = FakeDeck()

    with patch.object(mcp_client, "call_mcp_tool", deck):
        result = json.loads(
            srv.quest_add(mission_id, title="one", quests=["two"])
        )

    assert result["code"] == "quest_add_ambiguous_input"
    assert result["deck_written"] is False
    assert deck.calls == []
    assert db.list_checklist_items(mission_id) == []


def test_quest_add_batch_rejects_empty_batch_and_empty_entry(
    replica, project_maps
):
    srv, db = replica
    mission_id = _mission(db)
    deck = FakeDeck()

    with patch.object(mcp_client, "call_mcp_tool", deck):
        empty = json.loads(srv.quest_add(mission_id, quests=[]))
        blank = json.loads(srv.quest_add(mission_id, quests=["ok", "   "]))

    assert empty["code"] == "quests_empty"
    assert blank["code"] == "quest_text_empty"
    assert deck.calls == []
    assert db.list_checklist_items(mission_id) == []


def test_quest_add_batch_reports_deck_written_when_replica_fails(
    replica, project_maps, monkeypatch
):
    srv, db = replica
    mission_id = _mission(
        db, description="- [ ] existing", quests=[("existing", 0)]
    )
    deck = FakeDeck(description="- [ ] existing")

    def boom(*args, **kwargs):
        raise RuntimeError("replica down")

    monkeypatch.setattr(db, "upsert_mission", boom)

    with patch.object(mcp_client, "call_mcp_tool", deck):
        result = json.loads(srv.quest_add(mission_id, quests=["a", "b"]))

    assert result["code"] == "replica_refresh_failed"
    assert result["deck_written"] is True
    assert result["positions"] == [1, 2]
    assert len(result["quest_ids"]) == 2
    assert len(deck.writes()) == 1


# ── map_list compact ────────────────────────────────────────────────────


def test_map_list_compact_omits_patterns_and_full_restores_them():
    maps = {
        "alpha": {
            "patterns": ["a", "aa"],
            "deck_board_id": 7,
            "collective_id": 6,
        },
        "beta": {"patterns": ["b"], "deck_board_id": 8, "collective_id": 7},
    }

    with patch(
        "ultratimonel.context_extractor.get_project_maps", return_value=maps
    ):
        compact = json.loads(srv_module.map_list())
        full = json.loads(srv_module.map_list(full=True))

    assert compact["alpha"] == {"deck_board_id": 7, "collective_id": 6}
    assert "patterns" not in compact["alpha"]
    assert compact["beta"] == {"deck_board_id": 8, "collective_id": 7}
    assert full["alpha"]["patterns"] == ["a", "aa"]
    assert full["beta"]["patterns"] == ["b"]


# ── mission_list pagination ─────────────────────────────────────────────


def test_mission_list_pagination_returns_page_and_real_total(replica):
    srv, db = replica
    _many_missions(db, count=25)

    everything = json.loads(srv.mission_list("testproj"))
    page = json.loads(srv.mission_list("testproj", limit=10, offset=5))

    assert everything["total"] == 25
    assert len(everything["missions"]) == 25
    assert page["total"] == 25
    assert len(page["missions"]) == 10
    assert page["missions"] == everything["missions"][5:15]


def test_mission_list_pagination_offset_past_total_is_empty(replica):
    srv, db = replica
    _many_missions(db, count=3)

    result = json.loads(srv.mission_list("testproj", limit=10, offset=10))

    assert result["missions"] == []
    assert result["total"] == 3


@pytest.mark.parametrize("bad_limit", [0, -1, "5", 1.5, True])
def test_mission_list_pagination_rejects_invalid_limit(replica, bad_limit):
    srv, db = replica
    _many_missions(db, count=2)

    result = json.loads(srv.mission_list("testproj", limit=bad_limit))

    assert result["code"] == "invalid_limit"
    assert "missions" not in result


# ── backwards compatibility ─────────────────────────────────────────────


def test_legacy_signatures_still_work_after_compact_pagination_batch(
    replica, project_maps
):
    srv, db = replica
    mission_id = _mission(
        db, description="- [ ] existing", quests=[("existing", 0)]
    )
    deck = FakeDeck(description="- [ ] existing")

    with patch.object(mcp_client, "call_mcp_tool", deck):
        added = json.loads(srv.quest_add(mission_id, "legacy single"))

    assert added["title"] == "legacy single"
    assert added["done"] is False
    assert added["identity"] == "marker"

    listed = json.loads(srv.mission_list("testproj"))
    assert listed["total"] == 1

    maps = json.loads(srv.map_list())
    assert "testproj" in maps
    assert maps["testproj"]["deck_board_id"] == 21
