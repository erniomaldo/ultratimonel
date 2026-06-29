"""triple_match.py — Coordinated 1a (AgentMemory) → 1b (Checkpoint) → 1e (Deck)
sequential execution with error isolation.

Each gate calls external MCP tools via **stdio** (same transport Hermes uses),
NOT HTTP.  Previously used HTTP JSON-RPC on hardcoded ports that didn't exist,
causing false-positive WARN states after gateway restarts.
"""

import json
import logging
import os
import time
from typing import Any, Optional

from .gate_engine import GateConfig, GateResult, PASS, SKIP, WARN, BLOCK
from .mcp_client import call_mcp_tool, TOOL_NAMES
from .context_extractor import PROJECT_COLLECTIVE_MAP, PROJECT_DECK_MAP

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 40.0  # overall timeout per gate (stdio spawn + handshake + call)


# ── Domain helpers ──────────────────────────────────────────────────────


def _call_agentmemory(context: dict) -> GateResult:
    """Gate 1a: recall AgentMemory via smart_search.

    Uses MCP stdio transport to call the agentmemory MCP server directly,
    matching how Hermes connects to it (npx -y @agentmemory/mcp).

    Query = sender + " " + topic, limit=10.
    """
    query = f"{context.get('sender', '')} {context.get('topic', '')}".strip()
    if not query:
        query = context.get("project", "general")

    result, error = call_mcp_tool(
        "agentmemory",
        TOOL_NAMES["agentmemory"]["smart_search"],
        {"query": query, "limit": 10},
        timeout=HTTP_TIMEOUT,
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
    # The agentmemory MCP server may wrap results differently
    if not snippets and isinstance(result, dict):
        # Try common response shapes
        snippets = result.get("data", result.get("memories", []))

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

    Uses MCP stdio transport to call the checkpoint MCP server directly.
    Key = project name.  If missing, create default.
    """
    project = context.get("project", "general")
    key = project

    result, error = call_mcp_tool(
        "checkpoint",
        TOOL_NAMES["checkpoint"]["get_state"],
        {"key": key},
        timeout=HTTP_TIMEOUT,
    )

    if result is None:
        if error == "timeout":
            return GateResult(
                name="1b",
                state=WARN,
                message="Checkpoint timeout",
                result_data={"checkpoint_state": {"status": "new", "key": key}},
            )

        # Unavailable — try to create default checkpoint
        create_result, create_error = call_mcp_tool(
            "checkpoint",
            TOOL_NAMES["checkpoint"]["set_state"],
            {"key": key, "value": json.dumps({"status": "new"})},
            timeout=HTTP_TIMEOUT,
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


# ── Steering documents to fetch from each collective ────────────────────

STEERING_DOC_TITLES = {
    "visión", "vision",
    "decisions",
    "arquitectura", "architecture",
    "roadmap",
    "página de inicio",
}


def _call_collective(context: dict) -> GateResult:
    """Gate 1c: fetch steering doc references from the project's collective.

    Looks up the matched project in PROJECT_COLLECTIVE_MAP, fetches the
    page list from the corresponding Nextcloud Collective, and returns
    the IDs + titles of steering docs (Visión, Decisions, Arquitectura,
    Roadmap, Home).

    The agent can then fetch content on demand via
    ``mcp_nextcloud_collectives_get_page``.
    """
    project = context.get("project", "")
    collective_id = PROJECT_COLLECTIVE_MAP.get(project)
    if collective_id is None:
        return GateResult(
            name="1c",
            state=SKIP,
            message=f"No collective mapped for project '{project}'",
            result_data={"steering_docs": []},
        )

    pages, error = call_mcp_tool(
        "nextcloud",
        TOOL_NAMES["nextcloud"]["collectives_get_pages"],
        {"collective_id": collective_id},
        timeout=HTTP_TIMEOUT,
    )

    if pages is None:
        return GateResult(
            name="1c",
            state=WARN,
            message=f"Collective {collective_id} unavailable: {error}",
            result_data={"steering_docs": []},
        )

    page_list = pages if isinstance(pages, list) else pages.get("pages", [])

    # Filter for steering docs by title (case-insensitive)
    steering = []
    for page in page_list:
        title = page.get("title", "")
        title_lower = title.lower().strip()
        if title_lower in STEERING_DOC_TITLES:
            steering.append({
                "page_id": page["id"],
                "title": page.get("title"),
                "collective_id": collective_id,
            })

    return GateResult(
        name="1c",
        state=PASS if steering else WARN,
        message=f"{len(steering)} steering doc(s) found in collective {collective_id}",
        result_data={"steering_docs": steering},
    )


def _call_deck(context: dict) -> GateResult:
    """Gate 1e: scan Deck boards for project match, then get stacks/cards.
    """
    try:
        return _call_deck_impl(context)
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        logger.error("_call_deck unhandled exception:\n%s", tb)
        return GateResult(
            name="1e", state=WARN,
            message=f"Deck error: {exc}",
            result_data={"deck_cards": []},
        )


def _call_deck_impl(context: dict) -> GateResult:
    """Gate 1e: look up board by PROJECT_DECK_MAP, then fetch stacks/cards.

    Uses the explicit PROJECT_DECK_MAP instead of scanning all boards
    and doing substring matching — faster and avoids false matches.
    """
    project = context.get("project", "").lower()

    # 1. Look up board ID directly from the map
    board_id = PROJECT_DECK_MAP.get(project)
    if board_id is None:
        return GateResult(
            name="1e",
            state=SKIP,
            message=f"No Deck board mapped for project '{context.get('project')}'",
            result_data={"deck_cards": []},
        )

    # 2. Get stacks for the known board (includes cards)
    try:
        stacks, stack_error = call_mcp_tool(
            "nextcloud",
            TOOL_NAMES["nextcloud"]["deck_get_stacks"],
            {"board_id": board_id, "include_cards": True},
            timeout=HTTP_TIMEOUT,
        )
    except Exception as exc:
        logger.exception("_call_deck stacks call_mcp_tool failed")
        return GateResult(
            name="1e", state=WARN,
            message=f"Deck stacks call failed: {exc}",
            result_data={"deck_cards": []},
        )

    if stacks is None:
        msg = "Board found but stacks timeout" if stack_error == "timeout" else f"Board {board_id} (project '{project}') found but stacks unavailable: {stack_error}"
        return GateResult(
            name="1e",
            state=WARN,
            message=msg,
            result_data={"deck_cards": []},
        )

    # stacks may be a list or a dict with a list key
    if isinstance(stacks, dict):
        for key in ("stacks", "result", "data", "items"):
            if key in stacks and isinstance(stacks[key], list):
                stack_list = stacks[key]
                break
        else:
            stack_list = []
    elif isinstance(stacks, list):
        stack_list = stacks
    else:
        logger.warning("_call_deck unexpected stacks type=%s", type(stacks))
        return GateResult(
            name="1e", state=WARN,
            message="Unable to parse stacks response",
            result_data={"deck_cards": []},
        )

    # Extract cards from stacks
    cards = []
    for stack in stack_list:
        stack_name = stack.get("title", "")
        for card in (stack.get("cards") or []):
            card_info = {
                "id": card.get("id"),
                "title": card.get("title"),
                "stack": stack_name,
                "description": card.get("description", ""),
                "duedate": card.get("duedate"),
                "labels": [l.get("title", "") for l in (card.get("labels") or [])],
            }
            cards.append(card_info)

    # Sort by duedate (cards with duedate first)
    cards.sort(key=lambda c: (c.get("duedate") or "") if c.get("duedate") else "9999-12-31")

    # Check for overdue cards (past duedate → BLOCK per Design.md §5)
    from datetime import date, datetime

    today = date.today()
    overdue_cards = []
    for c in cards:
        dd = c.get("duedate")
        if dd:
            try:
                dd_date = dd[:10] if len(dd) >= 10 else dd
                due = datetime.strptime(dd_date, "%Y-%m-%d").date()
                if due < today:
                    overdue_cards.append(c["title"])
            except (ValueError, IndexError):
                pass

    if overdue_cards:
        return GateResult(
            name="1e",
            state=BLOCK,
            message=f"Board {board_id} (project '{project}') has {len(overdue_cards)} overdue card(s): {', '.join(overdue_cards[:3])}",
            result_data={"deck_cards": cards},
        )

    if not cards:
        return GateResult(
            name="1e",
            state=WARN,
            message=f"Board {board_id} (project '{project}') has no cards",
            result_data={"deck_cards": []},
        )

    return GateResult(
        name="1e",
        state=PASS,
        message=f"{len(cards)} cards in board {board_id} (project '{project}')",
        result_data={"deck_cards": cards},
    )


# ── Executor registry ───────────────────────────────────────────────────

GATE_EXECUTORS: dict[str, callable] = {
    "1a": _call_agentmemory,
    "1b": _call_checkpoint,
    "1c": _call_collective,
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

    for gate_name in ("1a", "1b", "1c", "1e"):
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
        elif r.name == "1c":
            envelope["steering_docs"] = rd.get("steering_docs", [])
        elif r.name == "1e":
            envelope["deck_cards"] = rd.get("deck_cards", [])

    return envelope
