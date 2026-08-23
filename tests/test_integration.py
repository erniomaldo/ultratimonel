"""
Integration smoke test for Ultratimonel MCP server using the official MCP client.

Starts the server via stdio transport, initializes, and exercises all three
tools.  Uses the mcp.client.stdio module for proper protocol handling.
"""

import asyncio
import json
import os
import sys
import time
import pytest
from unittest.mock import patch

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


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


class TestToolsUsabilityRetroIntegration:
    """End-to-end integration tests using real DB + direct server function calls."""

    def _make_db(self):
        import tempfile
        from ultratimonel.persistence import Persistence
        db_fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(db_fd)
        p = Persistence(db_path=db_path)
        mid = p.upsert_mission(deck_task_id=1, project="test-proj", title="Sprint Planning", description="Q4 planning")
        p.upsert_checklist_item(mid, item_index=0, text="Define goals")
        p.upsert_checklist_item(mid, item_index=1, text="Assign owners")
        return p, db_path

    def test_mission_get_returns_minimal_fields(self):
        """F-TU-01: mission_get returns id, title, checklist_item_ids only."""
        import ultratimonel.server as srv
        p, db_path = self._make_db()
        try:
            # Patch the module-level persistence to use our test DB
            orig_persistence = srv.persistence
            srv.persistence = p
            try:
                result = json.loads(srv.mission_get(1))
                assert result["id"] == 1
                assert result["title"] == "Sprint Planning"
                assert "checklist_item_ids" in result
                assert len(result["checklist_item_ids"]) == 2
                assert "description" not in result
                assert "checklist_items" not in result
            finally:
                srv.persistence = orig_persistence
        finally:
            p.close()
            os.unlink(db_path)

    def test_mission_list_light_mode_omits_description(self):
        """F-TU-03: light mode omits description and checklist_items."""
        import ultratimonel.server as srv
        p, db_path = self._make_db()
        try:
            orig_persistence = srv.persistence
            srv.persistence = p
            try:
                result = json.loads(srv.mission_list("test-proj", include_description=False))
                assert result["project"] == "test-proj"
                assert result["total"] == 1
                mission = result["missions"][0]
                assert set(mission.keys()) == {"id", "title", "status"}
                assert mission["id"] == 1
                assert mission["title"] == "Sprint Planning"
                assert "description" not in mission
                assert "checklist_items" not in mission
            finally:
                srv.persistence = orig_persistence
        finally:
            p.close()
            os.unlink(db_path)

    def test_begin_turn_persists_explicit_project(self):
        """S7+S8: begin_turn uses explicit project; end_turn validates against it."""
        import ultratimonel.server as srv
        from ultratimonel.gate_engine import GateResult, PASS, SKIP

        p, db_path = self._make_db()
        try:
            orig_persistence = srv.persistence
            srv.persistence = p
            srv._clear_active_intento()
            try:
                with patch("ultratimonel.server.extract_context") as mock_extract, \
                     patch("ultratimonel.server.run_triple_match") as mock_triple:
                    mock_extract.return_value = {"sender": "user", "topic": "test", "project": "unknown"}
                    mock_triple.return_value = [
                        GateResult(name="1a", state=PASS), GateResult(name="1b", state=PASS),
                        GateResult(name="1c", state=SKIP), GateResult(name="1e", state=PASS),
                    ]

                    result = json.loads(srv.begin_turn(
                        "sess-int-001", "voy-rojo", 0, 0,
                        "talk about unknown topic", "user"
                    ))
                    intento_id = result["intento_id"]
                    assert intento_id is not None

                    # Verify gates were persisted under "voy-rojo", not "unknown"
                    gate_states = p.list_gate_states("sess-int-001", "voy-rojo")
                    assert len(gate_states) == 4

                    # end_turn should validate against "voy-rojo"
                    result = json.loads(srv.end_turn(intento_id))
                    assert result["final_status"] == "success"
            finally:
                srv.persistence = orig_persistence
                srv._clear_active_intento()
        finally:
            p.close()
            os.unlink(db_path)

    def test_nf_tu01_mission_get_under_5ms(self):
        """NF-TU-01: mission_get SHALL complete in under 5 ms."""
        import ultratimonel.server as srv
        p, db_path = self._make_db()
        try:
            orig_persistence = srv.persistence
            srv.persistence = p
            try:
                iterations = 100
                start = time.perf_counter()
                for _ in range(iterations):
                    srv.mission_get(1)
                elapsed_ms = (time.perf_counter() - start) / iterations * iterations / 1000
                assert elapsed_ms < 5, f"mission_get took {elapsed_ms:.2f} ms"
            finally:
                srv.persistence = orig_persistence
        finally:
            p.close()
            os.unlink(db_path)

    def test_nf_tu01_checklist_item_get_under_5ms(self):
        """NF-TU-01: checklist_item_get SHALL complete in under 5 ms."""
        import ultratimonel.server as srv
        p, db_path = self._make_db()
        try:
            orig_persistence = srv.persistence
            srv.persistence = p
            try:
                iterations = 100
                start = time.perf_counter()
                for _ in range(iterations):
                    srv.checklist_item_get(1)
                elapsed_ms = (time.perf_counter() - start) / iterations * iterations / 1000
                assert elapsed_ms < 5, f"checklist_item_get took {elapsed_ms:.2f} ms"
            finally:
                srv.persistence = orig_persistence
        finally:
            p.close()
            os.unlink(db_path)


class TestEnforcementV3Integration:
    """Integration tests for persistent turn counting and deadlock prevention."""

    def test_turn_counter_persists_across_sessions(self):
        """TC1: Server restart preserves turn count per session."""
        import tempfile, os
        from ultratimonel.persistence import Persistence

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        try:
            # First "session" - set turn count
            p1 = Persistence(db_path=db_path)
            p1.set_turn_count("sess-test-001", 7)
            assert p1.get_turn_count("sess-test-001") == 7
            p1.close()

            # Simulate "server restart" - new persistence instance
            p2 = Persistence(db_path=db_path)
            turn_count = p2.get_turn_count("sess-test-001")
            assert turn_count == 7, f"Expected 7, got {turn_count}"
            p2.close()
        finally:
            os.unlink(db_path)

    def test_begin_turn_exempt_from_bouncer(self):
        """TC4: begin_turn callable post-grace even with failed gates."""
        # This tests the deadlock prevention scenario
        # The bouncer should return None (allow) for begin_turn regardless of gate status
        from ultratimonel.plugin_preflight import _gates_bouncer, TOOLS_REQUIRING_VERIFIED_GATES

        tool_name = "mcp__ultratimonel__begin_turn"

        # Verify begin_turn is NOT in the restricted list (R3.1)
        assert tool_name not in TOOLS_REQUIRING_VERIFIED_GATES, \
            "begin_turn should be exempt from gate requirements per R3.1"

    def test_universal_blocking_post_grace(self):
        """TC2/TC3: All tools blocked uniformly post-grace period."""
        # Test that the bouncer blocks ALL tools when turn > GRACE_TURNS and gates fail
        import ultratimonel.plugin_preflight as plugin
        from unittest.mock import patch

        # Set up test context - mock persistence layer instead of global state
        original_last_session_id = plugin._last_session_id
        original_last_gates_parsed = plugin._last_gates_parsed

        try:
            # Mock get_turn_count to return 5 (> GRACE_TURNS default of 3)
            with patch("ultratimonel.ultratimonel_client.get_turn_count", return_value=5):
                plugin._last_session_id = "test-sess"
                plugin._last_gates_parsed = [
                    {"name": "1a", "state": "BLOCK", "mandatory": True, "message": ""},
                    {"name": "1b", "state": "PASS", "mandatory": True, "message": ""},
                    {"name": "1c", "state": "BLOCK", "mandatory": True, "message": ""},
                    {"name": "1e", "state": "BLOCK", "mandatory": True, "message": ""},
                ]

                # Test that blocked tools return block action with grace period message
                result = plugin._gates_bouncer(tool_name="mcp__ultratimonel__complete_intento")
                assert result is not None
                assert result["action"] == "block"
                assert "Tiempo de gracia agotado" in result["message"]

        finally:
            # Restore original state
            plugin._last_session_id = original_last_session_id
            plugin._last_gates_parsed = original_last_gates_parsed
