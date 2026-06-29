"""
ultratimonel — MCP Mission Server for Hermes pre-flight gate enforcement.

Provides three MCP tools (assert_gates, check_gate, complete_gate) that
enforce a deterministic pre-flight gate protocol: AgentMemory recall (1a),
Checkpoint state (1b), and Deck scan (1e).  Gate state is persisted in
SQLite at ~/.hermes/ultratimonel.db.
"""

__version__ = "1.0.0"
