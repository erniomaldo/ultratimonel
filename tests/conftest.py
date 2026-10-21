"""Shared pytest fixtures.

Unit tests MUST NOT touch live MCP servers. The gate engine and the Deck bridge
call ``call_mcp_tool``, which spawns real stdio servers (agentmemory,
checkpoint, nextcloud) with 30 s initialize timeouts and one retry — a single
accidental call turns the suite into a 60 s hang.

This autouse fixture pins ``call_mcp_tool`` to ``(None, "unavailable")`` for
every test that is not marked ``integration``. Tests that exercise a specific
external behaviour override it with their own ``patch``; live end-to-end tests
opt out through the ``integration`` marker.
"""

import pytest


def _unavailable(server_name, tool_name, params=None, timeout=8.0):
    """Stand-in for a live MCP call: the server is simply not there."""
    return None, "unavailable"


@pytest.fixture(autouse=True)
def _no_live_mcp(request, monkeypatch):
    if request.node.get_closest_marker("integration"):
        yield
        return

    from ultratimonel import mcp_client

    monkeypatch.setattr(mcp_client, "call_mcp_tool", _unavailable, raising=False)

    # ``triple_match`` imported the symbol directly, so patching the module
    # attribute is not enough — the alias must be replaced too.
    try:
        from ultratimonel import triple_match

        monkeypatch.setattr(triple_match, "call_mcp_tool", _unavailable, raising=False)
    except Exception:  # pragma: no cover - module always exists
        pass

    yield
