"""
triple_match.py — Coordinated 1a (AgentMemory) → 1b (Checkpoint) → 1e (Deck)
sequential execution with error isolation.

Each gate calls external MCP tools via HTTP JSON-RPC with 2s timeout.
All calls wrapped in try/except → SKIP/WARN fallback.  Ultratimonel
never crashes from an external tool failure.
"""

import json
import logging
import time
from typing import Any, Optional

import httpx

from .gate_engine import GateConfig, GateResult, PASS, SKIP, WARN, BLOCK

logger = logging.getLogger(__name__)

# ── MCP server endpoint configuration ───────────────────────────────────
# Override via env vars: ULTRATIMONEL_MEMORY_URL, ULTRATIMONEL_CHECKPOINT_URL,
# ULTRATIMONEL_DECK_URL

import os

MCP_ENDPOINTS: dict[str, str] = {
    "memory": os.environ.get(
        "ULTRATIMONEL_MEMORY_URL", "http://localhost:8085/json-rpc"
    ),
    "checkpoint": os.environ.get(
        "ULTRATIMONEL_CHECKPOINT_URL", "http://localhost:8086/json-rpc"
    ),
    "deck": os.environ.get(
        "ULTRATIMONEL_DECK_URL", "http://localhost:8087/json-rpc"
    ),
}

HTTP_TIMEOUT = 2.0  # per-gate timeout


# ── JSON-RPC client ─────────────────────────────────────────────────────


def _json_rpc_call(
    endpoint: str,
    method: str,
    params: Optional[dict] = None,
    timeout: float = HTTP_TIMEOUT,
) -> tuple[Optional[dict], Optional[str]]:
    """Make a JSON-RPC 2.0 call to an MCP server.

    Args:
        endpoint: http(s)://host:port/path for JSON-RPC
        method:   MCP tool method name
        params:   dict of parameters
        timeout:  seconds before raising

    Returns:
        Tuple of (parsed_result, error_type):
          - (result, None) on success
          - (None, "timeout") on timeout
          - (None, "unavailable") on connection or protocol error
    """
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or {},
        }
        with httpx.Client(timeout=timeout) as client:
            resp = client.post(endpoint, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                logger.warning(
                    "JSON-RPC error from %s/%s: %s",
                    endpoint, method, data["error"],
                )
                return None, "unavailable"
            return data.get("result"), None
    except httpx.TimeoutException:
        logger.warning("Timeout (%.1fs) calling %s/%s", timeout, endpoint, method)
        return None, "timeout"
    except Exception as exc:
        logger.warning("Failed to call %s/%s: %s", endpoint, method, exc)
        return None, "unavailable"


# ── Domain helpers ──────────────────────────────────────────────────────


def _call_agentmemory(context: dict) -> GateResult:
    """Gate 1a: recall AgentMemory via smart_search.

    Query = sender + " " + topic, limit=10.
    """
    query = f"{context.get('sender', '')} {context.get('topic', '')}".strip()
    if not query:
        query = context.get("project", "general")

    result, error = _json_rpc_call(
        MCP_ENDPOINTS["memory"],
        "mcp_agentmemory_memory_smart_search",
        {"query": query, "limit": 10},
    )

    if result is None:
        msg = "AgentMemory timeout" if error == "timeout" else "AgentMemory unavailable"
        return GateResult(
            name="1a",
            state=WARN,
            message=msg,
            result_data={"memory_snippets": []},
        )

    snippets = result if isinstance(result, list) else result.get("results", [])
    if not snippets:
        return GateResult(
            name="1a",
            state=PASS,
            message="No matching memories found (first contact)",
            result_data={"memory_snippets": []},
        )

    # Limit to top 3 for the envelope
    top = snippets[:3]
    return GateResult(
        name="1a",
        state=PASS,
        message=f"{len(snippets)} relevant memories found",
        result_data={"memory_snippets": top},
    )


def _call_checkpoint(context: dict) -> GateResult:
    """Gate 1b: get checkpoint state for the project key.

    Key = project name.  If missing, create default.
    """
    project = context.get("project", "general")
    key = project

    result, error = _json_rpc_call(
        MCP_ENDPOINTS["checkpoint"],
        "mcp_checkpoint_get_state",
        {"key": key},
    )

    if result is None:
        if error == "timeout":
            # Timeout → WARN, don't attempt fallback
            return GateResult(
                name="1b",
                state=WARN,
                message="Checkpoint timeout",
                result_data={"checkpoint_state": {"status": "new", "key": key}},
            )

        # Unavailable — try to create default checkpoint
        create_result, create_error = _json_rpc_call(
            MCP_ENDPOINTS["checkpoint"],
            "mcp_checkpoint_set_state",
            {"key": key, "value": json.dumps({"status": "new"})},
        )
        if create_result is None:
            return GateResult(
                name="1b",
                state=WARN,
                message="Checkpoint unavailable (server not reachable)",
                result_data={"checkpoint_state": {"status": "new", "key": key}},
            )

        return GateResult(
            name="1b",
            state=PASS,
            message=f"Created default checkpoint for '{key}'",
            result_data={"checkpoint_state": {"status": "new", "key": key}},
        )

    return GateResult(
        name="1b",
        state=PASS,
        message=f"Checkpoint '{key}' found",
        result_data={"checkpoint_state": result},
    )


def _call_deck(context: dict) -> GateResult:
    """Gate 1e: scan Deck boards for project match, then get stacks/cards.

    Filtering: case-insensitive substring match of board title against project.
    """
    project = context.get("project", "").lower()

    boards, error = _json_rpc_call(
        MCP_ENDPOINTS["deck"],
        "mcp_nextcloud_deck_get_boards",
    )

    if boards is None:
        state = WARN if error == "timeout" else SKIP
        msg = (
            "Deck scan timeout"
            if error == "timeout"
            else "Deck scan unavailable (server not reachable)"
        )
        return GateResult(
            name="1e",
            state=state,
            message=msg,
            result_data={"deck_cards": []},
        )

    # boards may be a list or dict with 'boards' key
    board_list = boards if isinstance(boards, list) else boards.get("boards", [])

    # Find matching board
    matched = None
    for b in board_list:
        title = b.get("title", "").lower()
        if project and project in title:
            matched = b
            break

    if matched is None:
        return GateResult(
            name="1e",
            state=SKIP,
            message=f"No Deck board found for project '{context.get('project')}'",
            result_data={"deck_cards": []},
        )

    # Get stacks for matched board
    stacks, stack_error = _json_rpc_call(
        MCP_ENDPOINTS["deck"],
        "mcp_nextcloud_deck_get_stacks",
        {"board_id": matched["id"], "include_cards": True},
    )

    if stacks is None:
        msg = "Board found but stacks timeout" if stack_error == "timeout" else f"Board '{matched.get('title')}' found but stacks unavailable"
        return GateResult(
            name="1e",
            state=WARN,
            message=msg,
            result_data={"deck_cards": []},
        )

    # Extract cards from stacks
    stack_list = stacks if isinstance(stacks, list) else stacks.get("stacks", [])
    cards = []
    for stack in stack_list:
        stack_name = stack.get("title", "")
        for card in stack.get("cards", []):
            card_info = {
                "id": card.get("id"),
                "title": card.get("title"),
                "stack": stack_name,
                "description": card.get("description", ""),
                "duedate": card.get("duedate"),
                "labels": [l.get("title", "") for l in card.get("labels", [])],
            }
            cards.append(card_info)

    # Sort by duedate (cards with duedate first)
    cards.sort(key=lambda c: (c["duedate"] or "") if c["duedate"] else "9999-12-31")

    # Check for overdue cards (past duedate → BLOCK per Design.md §5)
    from datetime import date, datetime

    today = date.today()
    overdue_cards = []
    for c in cards:
        dd = c.get("duedate")
        if dd:
            try:
                # Handle various date formats (ISO 8601 date or datetime)
                dd_date = dd[:10] if len(dd) >= 10 else dd
                due = datetime.strptime(dd_date, "%Y-%m-%d").date()
                if due < today:
                    overdue_cards.append(c["title"])
            except (ValueError, IndexError):
                pass  # unparseable duedate — ignore

    if overdue_cards:
        return GateResult(
            name="1e",
            state=BLOCK,
            message=f"Board '{matched.get('title')}' has {len(overdue_cards)} overdue card(s): {', '.join(overdue_cards[:3])}",
            result_data={"deck_cards": cards},
        )

    if not cards:
        return GateResult(
            name="1e",
            state=WARN,
            message=f"Board '{matched.get('title')}' has no cards",
            result_data={"deck_cards": []},
        )

    return GateResult(
        name="1e",
        state=PASS,
        message=f"{len(cards)} cards in '{matched.get('title')}'",
        result_data={"deck_cards": cards},
    )


# ── Executor registry ───────────────────────────────────────────────────

GATE_EXECUTORS: dict[str, callable] = {
    "1a": _call_agentmemory,
    "1b": _call_checkpoint,
    "1e": _call_deck,
}


# ── Orchestrator ────────────────────────────────────────────────────────


def run_triple_match(context: dict) -> list[GateResult]:
    """Execute all three gates sequentially with error isolation.

    Args:
        context: Extracted context dict (sender, topic, project, session_id).

    Returns:
        List of GateResult, one per gate, in order 1a → 1b → 1e.
    """
    results: list[GateResult] = []

    for gate_name in ("1a", "1b", "1e"):
        start = time.monotonic()
        try:
            executor = GATE_EXECUTORS.get(gate_name)
            if executor:
                result = executor(context)
            else:
                result = GateResult(
                    name=gate_name,
                    state=SKIP,
                    message=f"No executor for gate {gate_name}",
                )
        except Exception as exc:
            logger.exception("Gate %s raised unexpected error", gate_name)
            result = GateResult(
                name=gate_name,
                state=SKIP,
                message=f"Gate {gate_name} error: {exc}",
            )

        result.duration_ms = round((time.monotonic() - start) * 1000, 1)
        results.append(result)

    return results


def build_context_envelope(results: list[GateResult]) -> dict:
    """Compile a unified context envelope from all gate results.

    Args:
        results: Gate results from run_triple_match().

    Returns:
        dict with memory_snippets, checkpoint_state, deck_cards.
    """
    envelope: dict[str, Any] = {
        "memory_snippets": [],
        "checkpoint_state": {},
        "deck_cards": [],
    }

    for r in results:
        rd = r.result_data or {}
        if r.name == "1a":
            envelope["memory_snippets"] = rd.get("memory_snippets", [])
        elif r.name == "1b":
            envelope["checkpoint_state"] = rd.get("checkpoint_state", {})
        elif r.name == "1e":
            envelope["deck_cards"] = rd.get("deck_cards", [])

    return envelope
