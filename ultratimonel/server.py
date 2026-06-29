"""
server.py — FastMCP server with three registered tools.

Tools:
  - assert_gates(message, session_id)  → run all gates, return status
  - check_gate(name, session_id)       → read gate status from SQLite
  - complete_gate(name, session_id, reason) → BLOCK→PASS / WARN→PASS
"""

import json
import logging
import os
from datetime import datetime, timezone

from fastmcp import FastMCP

from .context_extractor import extract_context
from .gate_engine import (
    GATE_CONFIG_MAP,
    DEFAULT_GATES,
    GateConfig,
    GateResult,
    aggregate,
    can_complete,
    run_gate,
    PASS,
    BLOCK,
    WARN,
    SKIP,
)
from .persistence import Persistence
from .triple_match import (
    run_triple_match,
    build_context_envelope,
)

logger = logging.getLogger(__name__)

# ── Server setup ────────────────────────────────────────────────────────

app = FastMCP("ultratimonel")

# Persistence layer — shared across tools
db_path = os.environ.get(
    "ULTRATIMONEL_DB_PATH",
    os.path.expanduser("~/.hermes/ultratimonel.db"),
)
persistence = Persistence(db_path)


# ── Tool handlers ───────────────────────────────────────────────────────


@app.tool()
def assert_gates(
    message: str,
    session_id: str,
    sender: str = "user",
) -> str:
    """Run all pre-flight gates and return structured results.

    Executes:
      1. Context extraction (sender, topic, project)
      2. Triple-match (1a AgentMemory → 1b Checkpoint → 1e Deck)
      3. Aggregation (determine overall PASS/BLOCK/WARN)
      4. Persistence (store gate state, update mission)

    Args:
        message:    The user's raw message / query.
        session_id: Active Hermes session identifier.
        sender:     Optional sender name (default: "user").

    Returns:
        JSON string with:
          - gates:    list of per-gate results
          - overall:  PASS | BLOCK | WARN
          - context:  extracted sender, topic, project
          - context_envelope: aggregated memory, checkpoint, deck data
          - timestamp
    """
    # 1. Extract context
    context = extract_context(message, session_id, sender=sender)

    try:
        persistence.upsert_session(
            session_id=session_id,
            sender=context["sender"],
            topic=context["topic"],
            project=context["project"],
        )
    except Exception as exc:
        logger.warning("Session persistence failed (degraded): %s", exc)

    # 2. Run triple match
    gate_results = run_triple_match(context)

    # 3. Aggregate
    overall, gate_dicts = aggregate(gate_results)
    context_envelope = build_context_envelope(gate_results)

    # 4. Persist results
    project = context["project"]
    gates_passed = sum(
        1 for r in gate_results if r.state in (PASS, SKIP)
    )
    try:
        for r in gate_results:
            persistence.upsert_gate_state(
                session_id=session_id,
                project=project,
                gate_name=r.name,
                state=r.state,
                mandatory=r.mandatory,
                duration_ms=int(r.duration_ms),
                message=r.message,
                result_data=r.result_data,
            )
        persistence.upsert_mission(
            session_id=session_id,
            project=project,
            gates_passed=gates_passed,
            gates_total=len(DEFAULT_GATES),
        )
    except Exception as exc:
        logger.warning("Gate state persistence failed (degraded): %s", exc)

    # 5. Build response
    response = {
        "gates": gate_dicts,
        "status": overall,
        "context": {
            "sender": context["sender"],
            "topic": context["topic"],
            "project": context["project"],
        },
        "context_envelope": context_envelope,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    return json.dumps(response, ensure_ascii=False, default=str)


@app.tool()
def check_gate(
    name: str,
    session_id: str,
) -> str:
    """Return the current status of a single gate.

    Args:
        name:       Gate name, e.g. "1a", "1b", "1e".
        session_id: Active session identifier.

    Returns:
        JSON string with gate name, state, mandatory, message, updated_at.
    """
    if name not in GATE_CONFIG_MAP:
        return json.dumps({
            "error": f"Gate '{name}' not found",
            "valid_gates": list(GATE_CONFIG_MAP.keys()),
        })

    try:
        # We need the project — try from latest session
        session = persistence.get_session(session_id)
        project = session["project"] if session else "unknown"

        state = persistence.get_gate_state(session_id, project, name)
        if state is None:
            return json.dumps({
                "name": name,
                "state": "PENDING",
                "mandatory": GATE_CONFIG_MAP[name].mandatory,
                "message": "Gate has not been run yet in this session",
                "updated_at": "",
            })

        return json.dumps({
            "name": state["gate_name"],
            "state": state["state"],
            "mandatory": bool(state["mandatory"]),
            "message": state.get("message", ""),
            "updated_at": state.get("updated_at", ""),
        })
    except Exception as exc:
        logger.exception("check_gate failed")
        return json.dumps({
            "error": f"Failed to check gate: {exc}",
        })


@app.tool()
def complete_gate(
    name: str,
    session_id: str,
    reason: str = "",
) -> str:
    """Manually mark a gate as PASS.

    Only transitions BLOCK→PASS or WARN→PASS.  No-op on PASS/SKIP.

    Args:
        name:       Gate name to complete.
        session_id: Active session identifier.
        reason:     Human-readable reason for the transition.

    Returns:
        JSON string with from_state, to_state, name.
    """
    if name not in GATE_CONFIG_MAP:
        return json.dumps({
            "error": f"Gate '{name}' not found",
            "valid_gates": list(GATE_CONFIG_MAP.keys()),
        })

    try:
        session = persistence.get_session(session_id)
        project = session["project"] if session else "unknown"

        current = persistence.get_gate_state(session_id, project, name)
        current_state = current["state"] if current else BLOCK
        now = datetime.now(timezone.utc).isoformat()

        if current_state not in (BLOCK, WARN):
            return json.dumps({
                "name": name,
                "state": current_state,
                "message": f"Gate '{name}' is already {current_state} — no change needed",
                "updated_at": now,
            })

        # Persist transition
        persistence.upsert_gate_state(
            session_id=session_id,
            project=project,
            gate_name=name,
            state=PASS,
            mandatory=GATE_CONFIG_MAP[name].mandatory,
            message=reason or "Manually completed",
        )
        persistence.log_transition(
            session_id=session_id,
            gate_name=name,
            from_state=current_state,
            to_state=PASS,
            reason=reason,
        )

        return json.dumps({
            "name": name,
            "state": PASS,
            "message": f"Gate '{name}' transitioned {current_state} → PASS",
            "updated_at": now,
        })

    except Exception as exc:
        logger.exception("complete_gate failed")
        return json.dumps({
            "error": f"Failed to complete gate: {exc}",
        })
