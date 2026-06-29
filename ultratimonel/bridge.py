"""
bridge.py — mcp-capabilities bridge stub (post-MVP).

In a future release this module will register Ultratimonel's capabilities
with the mcp-capabilities-server so that Hermes can discover gates
dynamically.  For MVP, Ultratimonel is discovered via MCP tool list +
SOUL.md hard rules.
"""

import logging

logger = logging.getLogger(__name__)

# Post-MVP capability descriptor (informational stub)
CAPABILITY_DESCRIPTOR = {
    "name": "ultratimonel",
    "gates": ["mission-gate", "triple-match", "soul-enforce"],
    "tools": ["assert_gates", "check_gate", "complete_gate"],
}


def register_capabilities() -> None:
    """Stub: register Ultratimonel with mcp-capabilities-server.

    Post-MVP this will call the mcp-capabilities-server's register_tool
    or equivalent discovery endpoint.  Currently a no-op.
    """
    logger.info(
        "mcp-capabilities bridge stub: would register %s",
        CAPABILITY_DESCRIPTOR,
    )


def get_capability_descriptor() -> dict:
    """Return the capability descriptor dict (idempotent, no side-effects)."""
    return dict(CAPABILITY_DESCRIPTOR)
