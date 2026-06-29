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
        assert ctx["project"] == "general"
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

    def test_known_project_nocturno(self):
        ctx = extract_context("Working on nocturno design", "sess-001")
        assert ctx["project"] == "nocturno"

    def test_known_project_messagens(self):
        ctx = extract_context("Fix bug in messagens", "sess-001")
        assert ctx["project"] == "messagens"

    def test_unknown_project_falls_to_topic(self):
        ctx = extract_context("Building a new thing", "sess-001")
        assert ctx["project"] == "Building a new thing"

    def test_project_case_insensitive(self):
        ctx = extract_context("ULTRATIMONEL deployment", "sess-001")
        assert ctx["project"] == "ultratimonel"

    def test_project_first_mention_wins(self):
        ctx = extract_context(
            "Working on nocturno and ultratimonel together", "sess-001"
        )
        assert ctx["project"] == "nocturno"  # first occurrence

    def test_session_id_preserved(self):
        ctx = extract_context("Hello", "my-session-42")
        assert ctx["session_id"] == "my-session-42"
