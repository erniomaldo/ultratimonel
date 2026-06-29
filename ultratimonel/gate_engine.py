"""
gate_engine.py — Gate state machine and per-gate execution logic.

Gate states: PASS (proceed), SKIP (proceed, N/A), WARN (proceed w/ note),
             BLOCK (halt generation).

Each gate is a dict with:
  - name:       unique gate id (e.g. "1a", "1b", "1e")
  - mandatory:  bool — whether BLOCK halts generation
  - timeout_s:  per-gate HTTP timeout in seconds
  - source:     external MCP tool name (informational)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Gate States ─────────────────────────────────────────────────────────

PASS = "PASS"
SKIP = "SKIP"
WARN = "WARN"
BLOCK = "BLOCK"

STATES = {PASS, SKIP, WARN, BLOCK}

# ── Data classes ────────────────────────────────────────────────────────


@dataclass
class GateConfig:
    """Configuration for a single gate."""

    name: str
    mandatory: bool = True
    timeout_s: float = 2.0
    source: str = ""


@dataclass
class GateResult:
    """Result of executing a single gate."""

    name: str
    state: str = BLOCK
    mandatory: bool = True
    duration_ms: float = 0.0
    message: str = ""
    result_data: Optional[dict] = None


# ── Default gate configuration ──────────────────────────────────────────

DEFAULT_GATES: list[GateConfig] = [
    GateConfig(
        name="1a",
        source="mcp_agentmemory_memory_smart_search",
        mandatory=True,
        timeout_s=2.0,
    ),
    GateConfig(
        name="1b",
        source="mcp_checkpoint_get_state",
        mandatory=True,
        timeout_s=2.0,
    ),
    GateConfig(
        name="1c",
        source="mcp_nextcloud_collectives_get_pages",
        mandatory=False,
        timeout_s=2.0,
    ),
    GateConfig(
        name="1e",
        source="mcp_nextcloud_deck_get_boards",
        mandatory=True,
        timeout_s=2.0,
    ),
]

GATE_CONFIG_MAP: dict[str, GateConfig] = {g.name: g for g in DEFAULT_GATES}


# ── Gate runner ─────────────────────────────────────────────────────────


def run_gate(
    config: GateConfig,
    context: dict,
    executor: Optional[callable] = None,
) -> GateResult:
    """Execute a single gate.

    Args:
        config:   GateConfig describing the gate.
        context:  Extracted context dict (sender, topic, project, session_id).
        executor: Optional callable that performs the actual work.
                  Signature: executor(config, context) -> GateResult.
                  If None, the gate returns PASS unconditionally (test/no-op).

    Returns:
        GateResult with state, duration, and details.
    """
    start = time.monotonic()
    result = GateResult(
        name=config.name,
        mandatory=config.mandatory,
    )

    try:
        if executor:
            inner = executor(config, context)
            result.state = inner.state
            result.message = inner.message
            result.result_data = inner.result_data
        else:
            # No executor → no-op pass (useful for testing)
            result.state = PASS
            result.message = "Gate not executed (no executor)"
    except Exception as exc:
        logger.warning("Gate %s failed: %s", config.name, exc)
        result.state = WARN if config.mandatory else SKIP
        result.message = f"Gate {config.name} unavailable: {exc}"
        result.result_data = None

    result.duration_ms = round((time.monotonic() - start) * 1000, 1)
    return result


# ── Aggregation ─────────────────────────────────────────────────────────


def aggregate(results: list[GateResult]) -> tuple[str, list[dict]]:
    """Aggregate individual gate results into an overall status.

    Args:
        results: List of GateResult from each gate execution.

    Returns:
        Tuple of (overall_status, gate_dicts) where:
          - overall_status is PASS|BLOCK|WARN
          - gate_dicts is a list of serializable gate dicts
    """
    gate_dicts = []
    has_block = False
    has_warn = False
    all_pass = True

    # Severity order: BLOCK > WARN > PASS/SKIP
    for r in results:
        entry = {
            "name": r.name,
            "state": r.state,
            "mandatory": r.mandatory,
            "duration_ms": r.duration_ms,
            "message": r.message,
        }
        gate_dicts.append(entry)

        if r.state == BLOCK:
            has_block = True
        elif r.state == WARN:
            has_warn = True
        elif r.state == SKIP:
            pass  # SKIP is a soft pass

    if has_block:
        overall = BLOCK
    elif has_warn:
        overall = WARN
    else:
        overall = PASS

    return overall, gate_dicts


# ── State transition validation ─────────────────────────────────────────


def can_complete(state: str) -> bool:
    """Check if a gate can be manually completed (BLOCK→PASS or WARN→PASS)."""
    return state in (BLOCK, WARN)


def transition_requires_reason(from_state: str, to_state: str) -> bool:
    """Whether a transition requires a human-readable reason."""
    return from_state == BLOCK or to_state == PASS
