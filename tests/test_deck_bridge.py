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


