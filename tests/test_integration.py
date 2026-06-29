"""
Integration smoke test for Ultratimonel MCP server using the official MCP client.

Starts the server via stdio transport, initializes, and exercises all three
tools.  Uses the mcp.client.stdio module for proper protocol handling.
"""

import asyncio
import json
import os
import sys
import pytest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

pytestmark = pytest.mark.asyncio

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
MAIN_PY = os.path.join(PROJECT_ROOT, "main.py")


@pytest.fixture(scope="function")
def event_loop():
    """Create a single event loop for the module scope."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def client_session():
    """Start Ultratimonel and return an MCP ClientSession."""
    env = os.environ.copy()
    env["ULTRATIMONEL_DB_PATH"] = ":memory:"
    env["PYTHONPATH"] = PROJECT_ROOT + ":" + env.get("PYTHONPATH", "")
    env["PYTHONUNBUFFERED"] = "1"

    server_params = StdioServerParameters(
        command=sys.executable,
        args=["-u", MAIN_PY],
        env=env,
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            result = await session.initialize()
            assert result.serverInfo.name == "ultratimonel"
            yield session


class TestIntegration:
    async def test_server_initializes(self, client_session):
        """Server responds to initialize (already done in fixture)."""
        assert client_session is not None

    async def test_tools_listed(self, client_session):
        """FastMCP should list the three tools."""
        tools = await client_session.list_tools()
        names = [t.name for t in tools.tools]
        assert "assert_gates" in names
        assert "check_gate" in names
        assert "complete_gate" in names

    async def test_assert_gates_returns_expected_shape(self, client_session):
        """assert_gates should return gates, overall, context, timestamp."""
        result = await client_session.call_tool(
            "assert_gates",
            {
                "message": "Implement gates for ultratimonel",
                "session_id": "test-sess-001",
            },
        )
        assert not result.isError, f"assert_gates failed: {result.content}"

        text = result.content[0].text
        data = json.loads(text)

        assert "gates" in data
        assert "status" in data
        assert data["status"] in ("PASS", "BLOCK", "WARN")
        assert "context" in data
        assert "timestamp" in data

        for gate in data["gates"]:
            assert "name" in gate
            assert "state" in gate
            assert gate["state"] in ("PASS", "SKIP", "WARN", "BLOCK")

        ctx = data["context"]
        assert ctx["sender"] == "user"
        assert ctx["project"] == "ultratimonel"

    async def test_check_gate_returns_status(self, client_session):
        """check_gate should return gate status."""
        await client_session.call_tool(
            "assert_gates",
            {
                "message": "Testing check_gate for ultratimonel",
                "session_id": "test-sess-002",
            },
        )

        result = await client_session.call_tool(
            "check_gate",
            {"name": "1a", "session_id": "test-sess-002"},
        )
        assert not result.isError

        data = json.loads(result.content[0].text)
        assert data["name"] == "1a"
        assert data["state"] in ("PASS", "SKIP", "WARN", "BLOCK", "PENDING")

    async def test_check_unknown_gate_returns_error(self, client_session):
        """check_gate with unknown name should return error."""
        result = await client_session.call_tool(
            "check_gate",
            {"name": "99z", "session_id": "test-sess-003"},
        )
        assert not result.isError

        data = json.loads(result.content[0].text)
        assert "error" in data

    async def test_complete_gate_transition(self, client_session):
        """complete_gate should transition BLOCK/WARN → PASS."""
        await client_session.call_tool(
            "assert_gates",
            {
                "message": "Testing complete_gate for ultratimonel",
                "session_id": "test-sess-004",
            },
        )

        result = await client_session.call_tool(
            "complete_gate",
            {
                "name": "1b",
                "session_id": "test-sess-004",
                "reason": "Reviewed and approved",
            },
        )
        assert not result.isError

        data = json.loads(result.content[0].text)
        assert data["name"] == "1b"
        assert data["state"] == "PASS"
        assert "updated_at" in data

    async def test_complete_unknown_gate_returns_error(self, client_session):
        """complete_gate with invalid name should error."""
        result = await client_session.call_tool(
            "complete_gate",
            {"name": "99z", "session_id": "test-sess-005", "reason": "test"},
        )
        assert not result.isError

        data = json.loads(result.content[0].text)
        assert "error" in data

    async def test_assert_gates_sender_override(self, client_session):
        """assert_gates should accept a custom sender."""
        result = await client_session.call_tool(
            "assert_gates",
            {
                "message": "Design review for ultratimonel",
                "session_id": "test-sess-006",
                "sender": "erniomaldo",
            },
        )
        assert not result.isError

        data = json.loads(result.content[0].text)
        assert data["context"]["sender"] == "erniomaldo"

    async def test_context_envelope_present(self, client_session):
        """assert_gates response should include context_envelope."""
        result = await client_session.call_tool(
            "assert_gates",
            {
                "message": "ultratimonel gates",
                "session_id": "test-sess-007",
            },
        )
        assert not result.isError

        data = json.loads(result.content[0].text)
        assert "context_envelope" in data
        env = data["context_envelope"]
        assert "memory_snippets" in env
        assert "checkpoint_state" in env
        assert "deck_cards" in env

    async def test_assert_no_error_on_empty_message(self, client_session):
        """assert_gates should handle empty message gracefully."""
        result = await client_session.call_tool(
            "assert_gates",
            {"message": "", "session_id": "test-sess-008"},
        )
        assert not result.isError

        data = json.loads(result.content[0].text)
        assert data["context"]["topic"] == "general"
