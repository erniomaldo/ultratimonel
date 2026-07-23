"""
Unit tests for context_extractor.py — parsing edge cases.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ultratimonel.context_extractor import extract_context

import pytest


class TestExtractContext:
    def test_empty_message(self):
        ctx = extract_context("", "sess-001")
        assert ctx["sender"] == "user"
        assert ctx["topic"] == "general"
        assert ctx["project"] == "unknown"
        assert ctx["session_id"] == "sess-001"

    def test_sender_override(self):
        ctx = extract_context("Hello", "sess-001", sender="erniomaldo")
        assert ctx["sender"] == "erniomaldo"

    def test_topic_from_first_sentence(self):
        ctx = extract_context("Design the gate engine. Then test it.", "sess-001")
        assert ctx["topic"] == "Design the gate engine"

    def test_topic_capped_at_100_chars(self):
        long = "A" * 200
        ctx = extract_context(long, "sess-001")
        assert len(ctx["topic"]) <= 105  # 100 + ellipsis

    def test_known_project_ultratimonel(self):
        ctx = extract_context(
            "Implement gates for ultratimonel project", "sess-001"
        )
        assert ctx["project"] == "ultratimonel"

    def test_known_project_lectura_rapida(self):
        """Lectura rápida is one of the currently-mapped projects in
        project_maps.json. Tests against a real, live project name to ensure
        dynamic loading from JSON works."""
        ctx = extract_context("Working on lectura rapida dashboard", "sess-001")
        assert ctx["project"] == "lectura-rapida"

    def test_known_project_voy_rojo(self):
        """Voy-rojo is another mapped project. Multi-word pattern from JSON."""
        ctx = extract_context("Fix bug in voy rojo board", "sess-001")
        assert ctx["project"] == "voy-rojo"

    def test_unknown_project_falls_to_unknown(self):
        ctx = extract_context("Building a new thing", "sess-001")
        assert ctx["project"] == "unknown"

    def test_project_case_insensitive(self):
        ctx = extract_context("ULTRATIMONEL deployment", "sess-001")
        assert ctx["project"] == "ultratimonel"

    def test_project_first_mention_wins(self):
        """When multiple project patterns match, the first one in the message
        wins (positional priority)."""
        ctx = extract_context(
            "Working on voy rojo and ultratimonel together", "sess-001"
        )
        assert ctx["project"] == "voy-rojo"  # first occurrence

    def test_session_id_preserved(self):
        ctx = extract_context("Hello", "my-session-42")
        assert ctx["session_id"] == "my-session-42"
