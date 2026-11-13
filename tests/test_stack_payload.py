"""Card #218 quest 20: a text-shaped ``deck_get_stacks`` payload must not crash.

The nextcloud MCP is reached through the ``http-to-stdio`` proxy. When that
proxy hands the tool result back as text, ``mcp_client._parse_response``
returns the raw string (its documented contract) and the stack resolvers used
to call ``.get`` on it:

    AttributeError: 'str' object has no attribute 'get'

These tests pin the shape that reached production (a JSON string) and the
fail-closed behaviour for a payload that is not a stacks document.
"""

import json
from unittest.mock import patch

import pytest

from ultratimonel import deck_bridge, server as srv


STACKS = [{"id": 111, "title": "Backlog", "cards": [{"id": 189}]}]


class FakeDeck:
    """Minimal stateful Deck over the MCP tool surface."""

    def __init__(self, description="", title="Mission", card_id=189, stacks_payload=None):
        self.title = title
        self.description = description
        self.card_id = card_id
        self.stacks_payload = (
            STACKS if stacks_payload is None else stacks_payload
        )
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
            return (self.stacks_payload, None)
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
    from ultratimonel.persistence import Persistence

    db = Persistence(db_path=str(tmp_path / "stack-payload.db"))
    monkeypatch.setattr(srv, "persistence", db)
    srv._clear_active_intento()
    yield srv, db
    db.close()
    srv._clear_active_intento()


def _mission(db, description="", quests=(), deck_task_id=189):
    """A mission with ``deck_stack_id`` unset, like every pre-D9 replica row."""
    mission_id = db.upsert_mission(
        deck_task_id=deck_task_id,
        project="testproj",
        title="Mission",
        description=description,
        status="pendiente",
        checklist_total=len(quests),
        checklist_done=sum(done for _, done in quests),
    )
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


def _text_payload(stacks, *, double_encode=True):
    """The shape that reached production: the stacks document as text."""
    text = json.dumps(stacks, ensure_ascii=False)
    return json.dumps(text, ensure_ascii=False) if double_encode else text


# ── the exact failing call ─────────────────────────────────────────────


def test_quest_update_with_title_decodes_double_encoded_text_stacks(
    replica, project_maps
):
    """quest_update(quest_id, title=...) on a mission with no deck_stack_id."""
    srv_mod, db = replica
    mission_id = _mission(db, "", [("one", 0)])
    quest = db.list_checklist_items(mission_id)[0]
    deck = FakeDeck(
        description=_marked(db, mission_id),
        stacks_payload=_text_payload(STACKS, double_encode=True),
    )

    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        result = json.loads(srv_mod.quest_update(quest["id"], title="nuevo texto"))

    assert result == {"quest_id": quest["id"], "title": "nuevo texto", "done": False}
    # Marker preserved, done reset, only the text rewritten.
    assert deck.description == f"- [ ] nuevo texto [](#q:{quest['id']})"
    # The mission had no deck_stack_id, so the fallback read is what crashed.
    assert "deck_get_stacks" in deck.tool_names()
    assert "deck_update_card" in deck.tool_names()

    refreshed = db.get_checklist_item_by_id(quest["id"])
    assert refreshed["id"] == quest["id"]
    assert refreshed["text"] == "nuevo texto"
    assert refreshed["done"] == 0


def test_quest_update_with_title_decodes_single_encoded_text_stacks(
    replica, project_maps
):
    srv_mod, db = replica
    mission_id = _mission(db, "", [("one", 0)])
    quest = db.list_checklist_items(mission_id)[0]
    deck = FakeDeck(
        description=_marked(db, mission_id),
        stacks_payload=_text_payload(STACKS, double_encode=False),
    )

    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        result = json.loads(srv_mod.quest_update(quest["id"], title="nuevo texto"))

    assert result["title"] == "nuevo texto"
    assert deck.description == f"- [ ] nuevo texto [](#q:{quest['id']})"


def test_quest_update_without_title_still_works_on_a_text_stacks_payload(
    replica, project_maps
):
    """Regression: quest_update(quest_id) keeps today's behaviour."""
    srv_mod, db = replica
    mission_id = _mission(db, "", [("one", 1)])
    quest = db.list_checklist_items(mission_id)[0]
    deck = FakeDeck(
        description=_marked(db, mission_id),
        stacks_payload=_text_payload(STACKS),
    )

    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        result = json.loads(srv_mod.quest_update(quest["id"]))

    assert result == {"quest_id": quest["id"], "title": "one", "done": False}
    assert deck.description == f"- [ ] one [](#q:{quest['id']})"
    assert db.get_checklist_item_by_id(quest["id"])["done"] == 0


@pytest.mark.parametrize(
    ("title", "code"),
    [
        ("", "quest_text_empty"),
        ("   ", "quest_text_empty"),
        ("\t\n ", "quest_text_multiline"),
    ],
)
def test_quest_update_rejects_an_empty_title_before_any_deck_call(
    replica, project_maps, title, code
):
    srv_mod, db = replica
    mission_id = _mission(db, "", [("one", 0)])
    quest = db.list_checklist_items(mission_id)[0]
    deck = FakeDeck(description=_marked(db, mission_id))

    with patch("ultratimonel.mcp_client.call_mcp_tool", deck):
        result = json.loads(srv_mod.quest_update(quest["id"], title=title))

    assert result["deck_written"] is False
    assert result["code"] == code
    assert deck.tool_names() == []  # zero reads, zero writes
    stored = db.get_checklist_item_by_id(quest["id"])
    assert stored["text"] == "one"
    assert stored["done"] == 0


# ── shared helper: the payload normalizer and both stack resolvers ─────


@pytest.mark.parametrize(
    "payload",
    [
        STACKS,
        {"stacks": STACKS},
        {"result": STACKS},
        json.dumps(STACKS),
        json.dumps(json.dumps(STACKS)),
    ],
)
def test_normalize_stacks_payload_accepts_lists_dicts_and_text(payload):
    assert srv._normalize_stacks_payload(payload) == STACKS


@pytest.mark.parametrize(
    "payload",
    ["Backlog (3 cards)", 42, None, object()],
)
def test_normalize_stacks_payload_fails_closed_on_other_shapes(payload):
    assert srv._normalize_stacks_payload(payload) is None


def test_normalize_stacks_payload_empty_dict_yields_no_stacks():
    """A dict without stacks/result keeps the previous empty-list behaviour."""
    assert srv._normalize_stacks_payload({"unrelated": []}) == []


def test_resolve_stack_for_card_handles_a_text_payload(replica, project_maps):
    """sync_task's resolver shares the same contract and the same fix."""
    mission = {"deck_task_id": 189, "deck_stack_id": None}
    payload = _text_payload(STACKS)

    with patch("ultratimonel.mcp_client.call_mcp_tool", FakeDeck(stacks_payload=payload)):
        stack_id, stack_title, err = srv._resolve_stack_for_card(21, mission)

    assert (stack_id, stack_title, err) == (111, "Backlog", None)


def test_resolve_stack_for_card_fails_closed_on_non_json_text(replica, project_maps):
    mission = {"deck_task_id": 189, "deck_stack_id": None}

    with patch(
        "ultratimonel.mcp_client.call_mcp_tool", FakeDeck(stacks_payload="Backlog (3)")
    ):
        stack_id, stack_title, err = srv._resolve_stack_for_card(21, mission)

    assert stack_id is None
    assert stack_title is None
    assert err == "unexpected Deck response shape"
