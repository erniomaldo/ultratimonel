"""
Unit tests for mcp_client.py — Deck tool-name registration (WU1).

The Nextcloud MCP exposes deck_create_card / deck_create_stack; they must be
registered in TOOL_NAMES["nextcloud"] so callers resolve them through the
existing call_mcp_tool("nextcloud", ...) path (design D1).
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import patch

from ultratimonel.mcp_client import TOOL_NAMES, call_mcp_tool


class TestNextcloudDeckToolRegistration:
    """deck_create_card / deck_create_stack resolve for the nextcloud server."""

    def test_deck_create_card_is_mapped(self):
        assert TOOL_NAMES["nextcloud"]["deck_create_card"] == "deck_create_card"

    def test_deck_create_stack_is_mapped(self):
        assert TOOL_NAMES["nextcloud"]["deck_create_stack"] == "deck_create_stack"

    def test_resolved_names_flow_through_call_mcp_tool(self):
        """The mapped names reach the connection layer unchanged."""
        with patch("ultratimonel.mcp_client._MCPConnection") as mock_conn_cls, \
                patch.dict(
                    "ultratimonel.mcp_client._connection_cache", {}, clear=True
                ):
            mock_conn_cls.return_value.call_tool.return_value = ({"id": 7}, None)

            for mapped in ("deck_create_card", "deck_create_stack"):
                result, err = call_mcp_tool(
                    "nextcloud",
                    TOOL_NAMES["nextcloud"][mapped],
                    {"board_id": 21, "stack_id": 111, "title": "t"},
                )
                assert err is None
                assert result == {"id": 7}

            called_names = [
                c.args[0]
                for c in mock_conn_cls.return_value.call_tool.call_args_list
            ]
            assert called_names == ["deck_create_card", "deck_create_stack"]
