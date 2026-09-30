"""Unit tests for deck_bridge.py — Deck-first write bridge (WU2).

The bridge is exercised with ``mcp_client.call_mcp_tool`` monkeypatched, so no
real MCP subprocess is spawned. The tests assert:

* markdown checkbox parsing (``- [ ]`` / ``- [x]`` / ``* [ ]``);
* ``update_description`` preserves quest lines byte-identical, in order, and
  never lets incoming prose introduce a quest (D3);
* ``complete_quest`` flips exactly one position;
* a bridge failure returns an error and performs NO local persistence.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest

from ultratimonel import deck_bridge, mcp_client


class FakeMCP:
    """Records calls and serves canned Deck responses by tool name."""

    def __init__(self):
        self.calls = []
        self.responses = {}

    def __call__(self, server_name, tool_name, params=None, timeout=8.0):
        self.calls.append(
            {
                "server_name": server_name,
                "tool_name": tool_name,
                "params": dict(params or {}),
                "timeout": timeout,
            }
        )
        return self.responses.get(tool_name, (None, "unavailable"))

    def calls_for(self, tool_name):
        return [c for c in self.calls if c["tool_name"] == tool_name]


@pytest.fixture
def fake_mcp(monkeypatch):
    fake = FakeMCP()
    monkeypatch.setattr(mcp_client, "call_mcp_tool", fake)
    return fake


class TestExtractQuests:
    def test_parses_dash_and_star_checkboxes(self):
        description = (
            "Intro line\n"
            "\n"
            "- [ ] first\n"
            "- [x] second\n"
            "* [ ] third\n"
            "- [X] fourth\n"
            "plain text\n"
        )
        quests = deck_bridge.extract_quests(description)
        assert [q["text"] for q in quests] == [
            "first",
            "second",
            "third",
            "fourth",
        ]
        assert [q["done"] for q in quests] == [False, True, False, True]
        assert [q["line_no"] for q in quests] == [2, 3, 4, 5]

    def test_ignores_non_checkbox_lines(self):
        quests = deck_bridge.extract_quests(
            "# Heading\nprose\n- not a checkbox\n- [ ] real\n"
        )
        assert [q["text"] for q in quests] == ["real"]

    def test_line_no_indexes_original_lines(self):
        description = "a\n- [ ] b\nc"
        lines = description.split("\n")
        quests = deck_bridge.extract_quests(description)
        assert lines[quests[0]["line_no"]] == "- [ ] b"


class TestCleanProse:
    """FIX 1: sanitization drops every quest-like line, including dangerous
    checkbox-like variants any tolerant consumer could count."""

    @pytest.mark.parametrize(
        "payload",
        [
            "- [TODO] x",
            "- [] x",
            "- [  ] x",
            "* [ ] x",
            "+ [x] x",
            "  - [ ] indented",
        ],
    )
    def test_dangerous_checkbox_variants_do_not_survive(self, payload):
        prose = f"Antes\n{payload}\nDespues"
        assert deck_bridge.clean_prose(prose) == "Antes\nDespues"

    def test_authoritative_forms_are_removed(self):
        prose = "Antes\n- [ ] open\n- [x] done\n* [ ] star\nDespues"
        assert deck_bridge.clean_prose(prose) == "Antes\nDespues"


class TestCreateCard:
    def test_returns_card_id(self, fake_mcp):
        fake_mcp.responses["deck_create_card"] = ({"id": 99}, None)
        card_id, err = deck_bridge.create_card(21, 111, "New mission", "desc")
        assert card_id == 99
        assert err is None
        call = fake_mcp.calls_for("deck_create_card")[0]
        assert call["server_name"] == "nextcloud"
        assert call["params"] == {
            "board_id": 21,
            "stack_id": 111,
            "title": "New mission",
            "description": "desc",
        }


class TestUpdateTitle:
    def test_preserves_description(self, fake_mcp):
        fake_mcp.responses["deck_get_card"] = (
            {"title": "Old", "description": "- [ ] keep me"},
            None,
        )
        fake_mcp.responses["deck_update_card"] = ({"id": 42}, None)

        ok, err = deck_bridge.update_title(21, 111, 42, "New")
        assert ok is True
        assert err is None

        update = fake_mcp.calls_for("deck_update_card")[0]
        assert update["params"]["title"] == "New"
        assert update["params"]["description"] == "- [ ] keep me"


class TestUpdateDescription:
    def _prime(self, fake_mcp, current_description):
        fake_mcp.responses["deck_get_card"] = (
            {"title": "Mission", "description": current_description},
            None,
        )
        fake_mcp.responses["deck_update_card"] = ({"id": 42}, None)

    def test_preserves_quests_byte_identical_and_in_order(self, fake_mcp):
        current = "Old prose\n\n- [ ] alpha\n- [x] beta\n* [ ] gamma"
        self._prime(fake_mcp, current)

        ok, err = deck_bridge.update_description(21, 111, 42, "New prose")
        assert ok is True
        assert err is None

        params = fake_mcp.calls_for("deck_update_card")[0]["params"]
        new_description = params["description"]
        assert params["title"] == "Mission"
        # byte-identical, original relative order
        assert "- [ ] alpha\n- [x] beta\n* [ ] gamma" in new_description
        assert "New prose" in new_description
        assert "Old prose" not in new_description

    def test_incoming_prose_cannot_introduce_a_quest(self, fake_mcp):
        current = "- [ ] alpha"
        self._prime(fake_mcp, current)

        ok, err = deck_bridge.update_description(
            21, 111, 42, "New prose\n- [ ] sneaky\n* [x] also sneaky"
        )
        assert ok is True
        assert err is None

        new_description = fake_mcp.calls_for("deck_update_card")[0]["params"][
            "description"
        ]
        assert "- [ ] sneaky" not in new_description
        assert "* [x] also sneaky" not in new_description
        assert deck_bridge.extract_quests(new_description) == [
            {"line_no": 2, "done": False, "text": "alpha"}
        ]

    def test_no_quests_writes_clean_prose(self, fake_mcp):
        self._prime(fake_mcp, "just prose")
        ok, err = deck_bridge.update_description(21, 111, 42, "Only prose")
        assert ok is True
        assert err is None
        new_description = fake_mcp.calls_for("deck_update_card")[0]["params"][
            "description"
        ]
        assert new_description == "Only prose"


class TestAppendQuest:
    def test_returns_position_and_appends_line(self, fake_mcp):
        fake_mcp.responses["deck_get_card"] = (
            {"title": "M", "description": "- [ ] one\n- [x] two"},
            None,
        )
        fake_mcp.responses["deck_update_card"] = ({"id": 42}, None)

        position, err = deck_bridge.append_quest(21, 111, 42, "three")
        assert position == 2
        assert err is None

        new_description = fake_mcp.calls_for("deck_update_card")[0]["params"][
            "description"
        ]
        assert new_description == "- [ ] one\n- [x] two\n- [ ] three"

    def test_appends_to_empty_description(self, fake_mcp):
        fake_mcp.responses["deck_get_card"] = (
            {"title": "M", "description": ""},
            None,
        )
        fake_mcp.responses["deck_update_card"] = ({"id": 42}, None)

        position, err = deck_bridge.append_quest(21, 111, 42, "first")
        assert position == 0
        assert err is None
        new_description = fake_mcp.calls_for("deck_update_card")[0]["params"][
            "description"
        ]
        assert new_description == "- [ ] first"


class TestUpdateQuest:
    def test_surgical_edit_keeps_done_false(self, fake_mcp):
        fake_mcp.responses["deck_get_card"] = (
            {"title": "M", "description": "- [ ] one\n- [x] two\n- [ ] three"},
            None,
        )
        fake_mcp.responses["deck_update_card"] = ({"id": 42}, None)

        ok, err = deck_bridge.update_quest(21, 111, 42, 1, "TWO")
        assert ok is True
        assert err is None
        new_description = fake_mcp.calls_for("deck_update_card")[0]["params"][
            "description"
        ]
        assert new_description == "- [ ] one\n- [ ] TWO\n- [ ] three"

    def test_out_of_range_position_errors(self, fake_mcp):
        fake_mcp.responses["deck_get_card"] = (
            {"title": "M", "description": "- [ ] one"},
            None,
        )
        ok, err = deck_bridge.update_quest(21, 111, 42, 5, "nope")
        assert ok is None
        assert err == "quest_position_out_of_range"
        assert fake_mcp.calls_for("deck_update_card") == []


class TestCompleteQuest:
    def test_flips_only_target_position(self, fake_mcp):
        fake_mcp.responses["deck_get_card"] = (
            {"title": "M", "description": "- [ ] alpha\n- [ ] beta\n- [ ] gamma"},
            None,
        )
        fake_mcp.responses["deck_update_card"] = ({"id": 42}, None)

        ok, err = deck_bridge.complete_quest(21, 111, 42, 1)
        assert ok is True
        assert err is None
        new_description = fake_mcp.calls_for("deck_update_card")[0]["params"][
            "description"
        ]
        assert new_description == "- [ ] alpha\n- [x] beta\n- [ ] gamma"

    def test_preserves_star_bullet(self, fake_mcp):
        fake_mcp.responses["deck_get_card"] = (
            {"title": "M", "description": "* [ ] alpha\n* [ ] beta"},
            None,
        )
        fake_mcp.responses["deck_update_card"] = ({"id": 42}, None)

        ok, err = deck_bridge.complete_quest(21, 111, 42, 1)
        assert ok is True
        assert err is None
        new_description = fake_mcp.calls_for("deck_update_card")[0]["params"][
            "description"
        ]
        assert new_description == "* [ ] alpha\n* [x] beta"


class TestQuestTextSingleLine:
    """W-d: quest text can never compose an extra checkbox line."""

    def test_append_quest_rejects_newline(self, fake_mcp):
        fake_mcp.responses["deck_get_card"] = (
            {"title": "M", "description": "- [ ] one"},
            None,
        )
        position, err = deck_bridge.append_quest(
            21, 111, 42, "two\n- [x] injected"
        )
        assert position is None
        assert err == "quest_text_multiline"
        # No Deck write happened, so no injected checkbox line exists.
        assert fake_mcp.calls_for("deck_update_card") == []

    def test_append_quest_rejects_carriage_return(self, fake_mcp):
        fake_mcp.responses["deck_get_card"] = (
            {"title": "M", "description": ""},
            None,
        )
        position, err = deck_bridge.append_quest(21, 111, 42, "one\r- [x] injected")
        assert position is None
        assert err == "quest_text_multiline"
        assert fake_mcp.calls_for("deck_update_card") == []

    def test_update_quest_rejects_newline(self, fake_mcp):
        fake_mcp.responses["deck_get_card"] = (
            {"title": "M", "description": "- [ ] one"},
            None,
        )
        ok, err = deck_bridge.update_quest(
            21, 111, 42, 0, "one\n- [x] injected"
        )
        assert ok is None
        assert err == "quest_text_multiline"
        assert fake_mcp.calls_for("deck_update_card") == []


class TestUnexpectedResponseShape:
    """A non-card Deck payload fails the read, never sends ``title=''``."""

    _NON_CARD_PAYLOADS = [
        {"type": "text", "text": "Deck unavailable"},
        {"content": [{"type": "text", "text": "<html>502</html>"}]},
    ]

    @pytest.mark.parametrize("payload", _NON_CARD_PAYLOADS)
    def test_update_description_rejects_non_card_payload(self, fake_mcp, payload):
        fake_mcp.responses["deck_get_card"] = (payload, None)

        ok, err = deck_bridge.update_description(21, 111, 42, "prose")

        assert ok is None
        assert err == "unexpected Deck response shape"
        assert fake_mcp.calls_for("deck_update_card") == []

    @pytest.mark.parametrize("payload", _NON_CARD_PAYLOADS)
    def test_update_title_rejects_non_card_payload(self, fake_mcp, payload):
        fake_mcp.responses["deck_get_card"] = (payload, None)

        ok, err = deck_bridge.update_title(21, 111, 42, "New")

        assert ok is None
        assert err == "unexpected Deck response shape"
        assert fake_mcp.calls_for("deck_update_card") == []

    def test_card_without_description_field_is_rejected(self, fake_mcp):
        fake_mcp.responses["deck_get_card"] = ({"title": "Only title"}, None)

        ok, err = deck_bridge.update_description(21, 111, 42, "prose")

        assert ok is None
        assert err == "unexpected Deck response shape"
        assert fake_mcp.calls_for("deck_update_card") == []


class TestBridgeUnavailable:
    """A dead bridge must fail loudly and never touch local persistence."""

    def test_read_failure_returns_error(self, fake_mcp):
        card, err = deck_bridge.create_card(21, 111, "t")
        assert card is None
        assert err == "unavailable"

    def test_update_description_failure_returns_error(self, fake_mcp):
        ok, err = deck_bridge.update_description(21, 111, 42, "prose")
        assert ok is None
        assert err == "unavailable"
        assert fake_mcp.calls_for("deck_update_card") == []

    def test_all_operations_fail_without_local_write(self, fake_mcp, monkeypatch):
        calls = [
            lambda: deck_bridge.create_card(21, 111, "t"),
            lambda: deck_bridge.update_title(21, 111, 42, "t"),
            lambda: deck_bridge.update_description(21, 111, 42, "prose"),
            lambda: deck_bridge.append_quest(21, 111, 42, "q"),
            lambda: deck_bridge.update_quest(21, 111, 42, 0, "q"),
            lambda: deck_bridge.complete_quest(21, 111, 42, 0),
        ]
        for call in calls:
            value, err = call()
            assert value is None
            assert err is not None

    def test_bridge_does_not_reference_persistence(self):
        """The bridge has no local-persistence dependency at all."""
        assert not hasattr(deck_bridge, "persistence")
